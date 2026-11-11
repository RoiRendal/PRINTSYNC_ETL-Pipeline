"""The load ledger (doc section 6.1) — the run-level row.

It is written in its **own** autocommit connection, outside the data transaction, because it has to
survive a rollback: a failed load must leave evidence that it was attempted. The cost is that a
crash between the data commit and the ledger update leaves data with a `running` row; the next
attempt is idempotent, so it corrects itself.

Per-table rows, validation results and the decision engine arrive in batch 5.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg

from psync_load.config import Settings, code_version
from psync_load.handover import Handover

__all__ = ["record_finish", "record_start"]


def _connect(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(
        settings.psync_warehouse_dsn,
        connect_timeout=settings.connect_timeout_seconds,
        autocommit=True,
    )


def record_start(settings: Settings, handover: Handover, run_id: uuid.UUID) -> None:
    """Open the run-level row, reusing it when this batch has been attempted before.

    ``load_runs`` allows one run-level row per batch, so a retry cannot insert a second one: it
    resets the row it already has. The earlier attempt is not lost — it stays in the log narrative,
    which is written per attempt (doc sections 6.2 and 6.3). The ledger's job is to say what the
    batch's state *is*, not to enumerate every time it was tried.
    """
    with _connect(settings) as conn:
        conn.execute(
            """
            insert into public.load_runs (
                run_id, transformation_run_id, batch_id,
                batch_window_start, batch_window_end, table_name, load_type,
                load_start_ts, load_status, code_version
            ) values (%s, %s, %s, %s, %s, null, 'INCREMENTAL', %s, 'running', %s)
            on conflict (batch_id, coalesce(table_name, '__run__')) do update set
                run_id                = excluded.run_id,
                transformation_run_id = excluded.transformation_run_id,
                load_start_ts         = excluded.load_start_ts,
                load_end_ts           = null,
                load_duration_sec     = null,
                records_received      = 0,
                records_inserted      = 0,
                records_updated       = 0,
                records_rejected      = 0,
                load_status           = 'running',
                decision              = null,
                error_code            = null,
                error_message         = null,
                code_version          = excluded.code_version
            """,
            (
                run_id,
                handover.run_id,
                handover.batch_id,
                handover.window_start,
                handover.window_end,
                datetime.now(timezone.utc),
                code_version(),
            ),
        )


def record_finish(
    settings: Settings,
    run_id: uuid.UUID,
    *,
    status: str,
    loaded: dict[str, int] | None = None,
    rejected: int = 0,
    decision: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Close the run-level row: status, totals, duration and any error."""
    total = sum(loaded.values()) if loaded else 0
    with _connect(settings) as conn:
        conn.execute(
            """
            update public.load_runs
            set load_end_ts = %s,
                load_duration_sec = greatest(
                    0, extract(epoch from (%s - load_start_ts))::int
                ),
                records_received = %s,
                records_inserted = %s,
                records_rejected = %s,
                load_status = %s,
                decision = %s,
                error_code = %s,
                error_message = %s
            where run_id = %s and table_name is null
            """,
            (
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
                total + rejected,
                total,
                rejected,
                status,
                decision,
                error_code,
                error_message,
                run_id,
            ),
        )


def record_tables(
    settings: Settings,
    run_id: uuid.UUID,
    handover: Handover,
    loads: dict[str, "TableLoad"],
) -> None:
    """One ``load_runs`` row per target table (doc section 6.1).

    Written on the autocommit connection, like the run-level row, so a rolled-back batch still
    records what it attempted and how many rows each table carried.
    """
    from psync_load.loader import DIMENSION_TABLES

    now = datetime.now(timezone.utc)
    with _connect(settings) as conn:
        for table, load in loads.items():
            load_type = "FULL" if table in DIMENSION_TABLES else "INCREMENTAL"
            conn.execute(
                """
                insert into public.load_runs (
                    run_id, transformation_run_id, batch_id,
                    batch_window_start, batch_window_end, table_name, load_type,
                    load_start_ts, load_end_ts, load_duration_sec,
                    records_received, records_inserted, records_updated, records_rejected,
                    load_status, code_version
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, 0, %s, %s, %s)
                on conflict (batch_id, coalesce(table_name, '__run__')) do update set
                    run_id            = excluded.run_id,
                    load_start_ts     = excluded.load_start_ts,
                    load_end_ts       = excluded.load_end_ts,
                    records_received  = excluded.records_received,
                    records_inserted  = excluded.records_inserted,
                    records_rejected  = excluded.records_rejected,
                    load_status       = excluded.load_status,
                    code_version      = excluded.code_version
                """,
                (
                    run_id,
                    handover.run_id,
                    handover.batch_id,
                    handover.window_start,
                    handover.window_end,
                    table,
                    load_type,
                    now,
                    now,
                    load.received,
                    load.inserted,
                    load.rejected,
                    "success",
                    code_version(),
                ),
            )


def record_checks(
    settings: Settings, batch_id: str, checks: dict[str, "CheckResult"]
) -> None:
    """One ``load_validation_results`` row per check (doc section 6.1)."""
    with _connect(settings) as conn:
        for check_id, result in checks.items():
            conn.execute(
                """
                insert into public.load_validation_results (
                    batch_id, check_id, status, severity, message, error_code
                ) values (%s, %s, %s, %s, %s, %s)
                on conflict (batch_id, check_id) do update set
                    status     = excluded.status,
                    severity   = excluded.severity,
                    message    = excluded.message,
                    error_code = excluded.error_code
                """,
                (
                    batch_id,
                    check_id,
                    result.status,
                    result.severity,
                    result.message,
                    result.error_code,
                ),
            )
