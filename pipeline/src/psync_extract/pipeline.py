"""One extraction run, start to finish (doc sections 3, 4, 7).

This is the piece that turns the modules into a pipeline: resolve the day, run the pre-flight
checks, extract and write, reject what cannot be attributed, validate, decide, record, log, and
hand over — in that order, because each step depends on the one before it.

Two entry points use it: ``python -m psync_extract`` for a plain run, and the Prefect flow in
:mod:`psync_extract.flow` for orchestration. Neither contains logic of its own; both call
:func:`run_extraction`, so what you demo and what runs at 01:00 are the same code.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4

from psync_extract.config import Settings
from psync_extract.db.connection import connect_source
from psync_extract.db.target import connect_target
from psync_extract.decisions import Decision, decide, status_for
from psync_extract.extract import branches, business_settings, inventory, items, orders, payments, sales
from psync_extract.handover import HandoverPackage, build_handover, write_handover
from psync_extract.rejects import ORPHAN_REASON, reject_orphans
from psync_extract.runlog import build_log, write_log
from psync_extract.runs import RunRecord, TableRun, finish_run, start_run
from psync_extract.staging import reset_run, write_rows
from psync_extract.validation import (
    CheckResult,
    check_identifiers,
    check_non_empty,
    check_primary_key_uniqueness,
    check_row_parity,
    check_schema_drift,
    check_shop_settings,
    check_source_connection,
    check_window_resolution,
)
from psync_extract.validation.v3 import build_run_key
from psync_extract.window import ExtractionWindow, resolve_window

__all__ = ["EXTRACTORS", "Extractor", "RunResult", "run_extraction"]


@dataclass(frozen=True)
class Extractor:
    """One table's extractor, and whether it takes the window."""

    table: str
    columns: tuple[str, ...]
    run: Callable[..., Iterator[tuple]]
    windowed: bool


EXTRACTORS: tuple[Extractor, ...] = (
    Extractor(sales.TABLE, sales.COLUMNS, sales.extract_sales_transactions, True),
    Extractor(items.TABLE, items.COLUMNS, items.extract_sales_transaction_items, True),
    Extractor(payments.TABLE, payments.COLUMNS, payments.extract_payments, True),
    Extractor(orders.TABLE, orders.COLUMNS, orders.extract_orders, True),
    Extractor(inventory.TABLE, inventory.COLUMNS, inventory.extract_inventory_items, False),
    Extractor(
        business_settings.TABLE,
        business_settings.COLUMNS,
        business_settings.extract_business_settings,
        False,
    ),
    Extractor(branches.TABLE, branches.COLUMNS, branches.extract_branches, False),
)


@dataclass(frozen=True)
class RunResult:
    """What a caller needs to know afterwards."""

    run_id: str
    run_key: str
    business_date: date
    decision: Decision
    results: dict[str, CheckResult] = field(default_factory=dict)
    tables: tuple[TableRun, ...] = ()
    log_path: Path | None = None
    handover: HandoverPackage | None = None


def _summarise(results: dict[str, CheckResult]) -> dict[str, str]:
    return {check_id: result.status for check_id, result in results.items()}


def run_extraction(
    settings: Settings,
    business_date: date,
    *,
    log_directory: Path,
    handover_directory: Path,
) -> RunResult:
    """Run one business day through the whole pipeline."""
    started = datetime.now(timezone.utc)
    run_id = str(uuid4())
    run_key = build_run_key(settings.pipeline_name, business_date)
    window = resolve_window(
        business_date, time_zone=settings.run_timezone, lookback_days=settings.lookback_days
    )
    results: dict[str, CheckResult] = {}

    def stop_early(decision: Decision, tables: tuple[TableRun, ...] = ()) -> RunResult:
        """Record and log a run that never reached extraction, then return."""
        record = RunRecord(
            run_id=run_id, run_key=run_key, pipeline_name=settings.pipeline_name,
            business_date=business_date, window=window, status=status_for(decision.decision),
            tables=tables, validation_results=_summarise(results),
            error_code=next((r.error_code for r in results.values() if r.error_code), None),
            error_message=decision.reason, started_at=started,
        )
        with connect_target(settings) as conn:
            finish_run(conn, record)
        path = write_log(
            log_directory,
            build_log(
                run_id=run_id, run_key=run_key, business_date=business_date.isoformat(),
                window_start=window.window_start.isoformat(),
                window_end=window.window_end.isoformat(),
                lookback_days=window.lookback_days, decision=decision.decision,
                status=record.status,
                tables={t.table: {"rows_read": t.rows_read} for t in tables},
                validation_results=record.validation_results,
                error_code=record.error_code, error_message=record.error_message,
            ),
        )
        return RunResult(run_id, run_key, business_date, decision, results, tables, path, None)

    # --- pre-flight ---------------------------------------------------------------------------
    results["V1"] = check_source_connection(settings)
    if results["V1"].status == "FAIL":
        return stop_early(decide(results))

    results["V2"] = check_schema_drift(settings)
    if results["V2"].status == "FAIL":
        return stop_early(decide(results))

    settings_check = check_shop_settings(settings)
    results["V4"] = settings_check.result
    if settings_check.settings is None:
        return stop_early(decide(results))

    # The shop's own zone decides the day boundary (doc section 1.5 L5), so the window is resolved
    # again here rather than trusting the configured default.
    window = resolve_window(
        business_date,
        time_zone=settings_check.settings.time_zone,
        lookback_days=settings.lookback_days,
    )

    resolution = check_window_resolution(
        settings, business_date, time_zone=settings_check.settings.time_zone
    )
    results["V3"] = resolution.result
    if resolution.decision != "PROCEED":
        return stop_early(
            decide(results, already_completed=resolution.already_completed)
        )

    # --- extract and write --------------------------------------------------------------------
    tables: list[TableRun] = []
    with connect_target(settings) as target:
        start_run(
            target,
            RunRecord(
                run_id=run_id, run_key=run_key, pipeline_name=settings.pipeline_name,
                business_date=business_date, window=window, status="running",
                started_at=started,
            ),
        )

    with connect_source(settings) as source, connect_target(settings) as target:
        reset_run(target, run_id)

        for extractor in EXTRACTORS:
            table_started = time.perf_counter()
            rows = (
                extractor.run(source, window)
                if extractor.windowed
                else extractor.run(source)
            )
            written = write_rows(
                target, table=extractor.table, columns=extractor.columns, rows=rows,
                run_id=run_id, business_date=business_date,
            )
            tables.append(
                TableRun(
                    table=extractor.table,
                    rows_read=written,
                    rows_extracted=written,
                    duration_seconds=int(time.perf_counter() - table_started),
                )
            )

        removed = reject_orphans(target, run_id)

    # Rejected rows are subtracted from what was extracted, so V7's read = extracted + rejected
    # balances by construction rather than by assertion.
    tables = [
        TableRun(
            table=t.table,
            rows_read=t.rows_read,
            rows_extracted=t.rows_read - removed.get(f"stg_{t.table}", 0),
            rows_rejected=removed.get(f"stg_{t.table}", 0),
            reject_reason=ORPHAN_REASON if removed.get(f"stg_{t.table}") else None,
            duration_seconds=t.duration_seconds,
        )
        for t in tables
    ]

    # --- validation ---------------------------------------------------------------------------
    results["V5"] = check_identifiers(settings, run_id)
    results["V6"] = check_primary_key_uniqueness(settings, run_id)
    results["V7"] = check_row_parity(
        settings, run_id,
        read={t.table: t.rows_read for t in tables},
        rejected={t.table: t.rows_rejected for t in tables},
    )
    results["V8"] = check_non_empty(
        settings, run_id, window, closed_day=settings.closed_day == business_date
    )

    total_read = sum(t.rows_read for t in tables)
    total_rejected = sum(t.rows_rejected for t in tables)
    decision = decide(results, rows_read=total_read, rows_rejected=total_rejected)

    # --- record, log, hand over ---------------------------------------------------------------
    record = RunRecord(
        run_id=run_id, run_key=run_key, pipeline_name=settings.pipeline_name,
        business_date=business_date, window=window, status=status_for(decision.decision),
        tables=tuple(tables), validation_results=_summarise(results),
        error_code=next((r.error_code for r in results.values() if r.error_code), None),
        error_message=decision.reason, started_at=started,
    )
    with connect_target(settings) as target:
        finish_run(target, record)

    log_path = write_log(
        log_directory,
        build_log(
            run_id=run_id, run_key=run_key, business_date=business_date.isoformat(),
            window_start=window.window_start.isoformat(),
            window_end=window.window_end.isoformat(), lookback_days=window.lookback_days,
            decision=decision.decision, status=record.status,
            tables={
                t.table: {
                    "rows_read": t.rows_read,
                    "rows_extracted": t.rows_extracted,
                    "rows_rejected": t.rows_rejected,
                }
                for t in tables
            },
            validation_results=record.validation_results,
            rejects={t.table: t.rows_rejected for t in tables if t.rows_rejected},
            error_code=record.error_code, error_message=record.error_message,
        ),
    )

    package = build_handover(record, decision)
    if package is not None:
        write_handover(handover_directory, package)

    return RunResult(
        run_id=run_id, run_key=run_key, business_date=business_date, decision=decision,
        results=results, tables=tuple(tables), log_path=log_path, handover=package,
    )
