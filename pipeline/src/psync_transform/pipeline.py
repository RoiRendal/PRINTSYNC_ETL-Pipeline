"""One transformation batch, start to finish (doc sections 1.4, 7, 8 and 10).

This is the piece that turns the modules into a pipeline: resolve the batch, check the input, build
the dimensions, build the facts, validate, decide, clear on rejection, record, log. Each step depends
on the one before it.

Two entry points use it: ``python -m psync_transform`` for a plain run, and the Prefect flow in
:mod:`psync_transform.flow` for orchestration. Neither contains logic of its own; both call
:func:`run_transformation`, so what you demo and what runs at 01:30 are the same code.

The order of the checks is the order of the document. T1 and T2 gate the batch **before** a single
row is written, because a staging table built from an older revision must fail loudly rather than
produce a demand table with 93 % of its revenue unattributed (requirement D1). The remaining checks
run after the build, on committed state — which is also why a REJECTED verdict **clears the fact rows
for the window**: no wrong row stands, and a re-run after the fix republishes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from psync_transform.batch import Batch, resolve_batch
from psync_transform.config import Settings, code_version
from psync_transform.db import connect_target
from psync_transform.decisions import REJECTED, Decision, decide
from psync_transform.dimensions import build_dim_branch, build_dim_date, build_dim_item
from psync_transform.facts import (
    build_fct_daily_order_status,
    build_fct_daily_product_demand,
    build_fct_daily_sales,
    build_fct_daily_stock_snapshot,
)
from psync_transform.handover import HandoverError
from psync_transform.runlog import build_log, write_log
from psync_transform.runs import RuleCount, TableRecord, record_batch
from psync_transform.validation import (
    check_business_date_boundary,
    check_business_rules,
    check_cost_coverage,
    check_fact_reconciliation,
    check_handover_counts,
    check_input_contract,
    check_internal_money_arithmetic,
    check_item_identity,
    check_key_uniqueness,
    check_line_to_header_identity,
    check_non_empty_output,
    check_record_reconciliation,
    check_referential_integrity,
    check_required_columns,
    check_status_domain,
    check_version_continuity,
    check_vat_conformance,
)

__all__ = ["RunResult", "run_transformation"]


@dataclass(frozen=True)
class RunResult:
    """What a caller needs to know afterwards."""

    batch: Batch
    decision: Decision
    checks: dict[str, str]
    log_path: Path | None


def _clear_facts(conn: psycopg.Connection, batch: Batch) -> None:
    """Clear the published fact rows for the window, so no wrong row stands.

    The dimensions are left alone: they are cumulative history whose versions are correct snapshots
    of what the catalogue looked like, and reverting SCD2 would be destructive. The facts are what
    the Load stage reads, and they are what a rejected batch must not leave behind.
    """
    for table in (
        "fct_daily_sales",
        "fct_daily_product_demand",
        "fct_daily_order_status",
    ):
        conn.execute(
            f"delete from public.{table} where business_date between %s and %s",
            (batch.window_start, batch.window_end),
        )


def _write_log(
    log_directory: Path | str,
    batch: Batch,
    checks: Mapping[str, object],
    decision: Decision,
    tables: list[TableRecord],
    rule_counts: list[RuleCount],
    started: datetime,
    ended: datetime,
) -> Path:
    """Assemble and write the batch's log (doc section 8)."""
    status = "success" if "APPROVED" in decision.decision else "failed"
    return write_log(
        log_directory,
        build_log(
            batch_id=batch.batch_id,
            parent_run_id=str(batch.parent_run_id),
            business_date=batch.business_date.isoformat(),
            window_start=batch.window_start.isoformat(),
            window_end=batch.window_end.isoformat(),
            decision=decision.decision,
            status=status,
            tables={
                record.table: {
                    "records_read": record.records_read,
                    "records_output": record.records_output,
                    "records_rejected": record.records_rejected,
                    "records_modified": record.records_modified,
                }
                for record in tables
            },
            rule_counts={
                f"{count.table}:{count.rule_id}": count.records_affected
                for count in rule_counts
            },
            validation_results={
                check_id: result.status for check_id, result in checks.items()
            },
            code_version=code_version(),
        ),
    )


def run_transformation(
    settings: Settings, *, log_directory: Path | str = "logs"
) -> RunResult:
    """Run one transformation batch: resolve, check, build, validate, decide, record, log."""
    started = datetime.now(timezone.utc)
    batch = resolve_batch(settings)
    checks: dict[str, object] = {}
    rule_counts: list[RuleCount] = []

    def finish(
        decision: Decision, tables: list[TableRecord], error_code: str | None
    ) -> RunResult:
        ended = datetime.now(timezone.utc)
        with connect_target(settings) as conn:
            record_batch(
                conn,
                batch=batch,
                tables=tables,
                checks=checks,
                decision=decision,
                started_at=started,
                ended_at=ended,
                rule_counts=rule_counts,
                error_code=error_code,
            )
        log_path = _write_log(
            log_directory, batch, checks, decision, tables, rule_counts, started, ended
        )
        return RunResult(
            batch=batch,
            decision=decision,
            checks={check_id: result.status for check_id, result in checks.items()},
            log_path=log_path,
        )

    # --- the input gate: T1 and T2, before a single row is written -----------------------------
    with connect_target(settings) as conn:
        checks["T1"] = check_input_contract(settings, batch.handover)
        checks["T2"] = check_handover_counts(settings, batch.handover)

    gate_failed = [
        check_id for check_id in ("T1", "T2") if checks[check_id].is_critical_failure
    ]
    if gate_failed:
        return finish(
            Decision(
                REJECTED,
                f"the input contract is not met: {', '.join(gate_failed)}",
            ),
            tables=[],
            error_code="TRF_INPUT_CONTRACT",
        )

    # --- build: dimensions first, then facts (doc section 1.4) ---------------------------------
    with connect_target(settings) as conn:
        date_build = build_dim_date(conn, batch, settings.demand_window_days)
        branch_build = build_dim_branch(conn, batch)
        item_build = build_dim_item(conn, batch)

    with connect_target(settings) as conn:
        sales_build = build_fct_daily_sales(conn, batch, time_zone=settings.run_timezone)
        demand_build = build_fct_daily_product_demand(
            conn, batch, time_zone=settings.run_timezone,
            demand_window_days=settings.demand_window_days,
        )
        stock_build = build_fct_daily_stock_snapshot(conn, batch, time_zone=settings.run_timezone)
        order_build = build_fct_daily_order_status(conn, batch, time_zone=settings.run_timezone)

    tables = [
        TableRecord("dim_date", 0, date_build.rows_written, 0, 0),
        TableRecord("dim_branch", 0, branch_build.rows_written, 0, branch_build.rows_closed),
        TableRecord("dim_item", 0, item_build.rows_written, 0, item_build.rows_closed),
    ]
    counts: dict[str, object] = {}
    for build, sources in (
        (sales_build, ("sales_transactions", "sales_transaction_items", "payments")),
        (demand_build, ("sales_transactions", "sales_transaction_items")),
        (stock_build, ("inventory_items",)),
        (order_build, ("orders",)),
    ):
        read = sum(build.counts[source].read for source in sources)
        rejected = sum(build.counts[source].quarantined for source in sources)
        tables.append(
            TableRecord(build.table, read, build.rows_written, rejected, 0)
        )
        counts.update(build.counts)

    # The run-level totals count each source table ONCE, not once per fact that read it: the daily
    # fact and the product fact read the same sales rows independently, and summing their reads
    # would double both. The per-table rows keep their own reads, which overlap by design.
    total_read = sum(count.read for count in counts.values())
    total_rejected = sum(count.quarantined for count in counts.values())

    # --- validate on committed state ------------------------------------------------------------
    rule_counts = _rule_counts(settings, batch, (branch_build, item_build))
    checks["T3"] = check_record_reconciliation(settings, batch, counts)
    checks["T4"] = check_internal_money_arithmetic(settings, batch)
    checks["T5"] = check_line_to_header_identity(settings, batch)
    checks["T6"] = check_vat_conformance(settings, batch, settings.run_timezone)
    checks["T7"] = check_key_uniqueness(settings, batch)
    checks["T8"] = check_referential_integrity(settings, batch)
    checks["T9"] = check_required_columns(settings, batch)
    checks["T10"] = check_cost_coverage(settings, batch)
    checks["T11"] = check_business_rules(settings, batch)
    checks["T12"] = check_fact_reconciliation(settings, batch)
    checks["T13"] = check_business_date_boundary(settings, batch, settings.run_timezone)
    checks["T14"] = check_non_empty_output(settings, batch)
    checks["T15"] = check_version_continuity(settings)
    checks["T16"] = check_status_domain(settings, batch)
    checks["T17"] = check_item_identity(settings)

    decision = decide(
        checks,
        records_read=total_read,
        records_quarantined=total_rejected,
    )

    if decision.decision == REJECTED:
        with connect_target(settings) as conn:
            _clear_facts(conn, batch)

    return finish(decision, tables, None)


def _rule_counts(
    settings: Settings, batch: Batch, builds: tuple[object, ...]
) -> list[RuleCount]:
    """What each rule touched, derived from the quarantine and the dimension versions.

    The cleaning rules' counts are read from `quarantine_rows`, which already carries the rule that
    caught every rejected row — deriving them from recorded data means the counts cannot disagree
    with the quarantine. The dimension versions are counted by their builds.
    """
    counts: list[RuleCount] = []

    with connect_target(settings) as connection:
        rows = connection.execute(
            "select source_table, rule_id, count(*) "
            "from public.quarantine_rows where batch_id = %s group by 1, 2",
            (batch.batch_id,),
        ).fetchall()
    for source_table, rule_id, count in rows:
        counts.append(RuleCount(source_table, rule_id, batch.business_date, count))

    for build in builds:
        if build.rows_closed:
            rule = "M-02" if build.table == "dim_branch" else "M-03"
            counts.append(RuleCount(build.table, rule, batch.business_date, build.rows_closed))

    return counts
