"""Recording a run in ``pipeline_runs`` (doc section 4).

One row per source table, plus one run-level summary row whose ``table_name`` is null. That grain
is what the unique index enforces and what section 4 describes, so it is not a choice made here.

The record is the run's evidence: without it a night leaves rows in staging and nothing that says
who read them, when, how many, or whether they were sound. Section 9 keeps these rows for 24 months
precisely because they are the proof a published figure was produced correctly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import psycopg

from psync_extract.window import ExtractionWindow

__all__ = ["RunRecord", "TableRun", "finish_run", "start_run"]


@dataclass(frozen=True)
class TableRun:
    """What happened for one source table."""

    table: str
    rows_read: int
    rows_extracted: int
    rows_rejected: int = 0
    reject_reason: str | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True)
class RunRecord:
    """Everything the run-level row needs."""

    run_id: str
    run_key: str
    pipeline_name: str
    business_date: date
    window: ExtractionWindow
    status: str
    tables: tuple[TableRun, ...] = ()
    validation_results: dict[str, str] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


def _totals(tables: tuple[TableRun, ...]) -> tuple[int, int, int]:
    return (
        sum(t.rows_read for t in tables),
        sum(t.rows_extracted for t in tables),
        sum(t.rows_rejected for t in tables),
    )


def start_run(conn: psycopg.Connection, record: RunRecord) -> None:
    """Write the run-level row as ``running``, before any data is read.

    Written first so that a run which dies mid-extract still leaves a row saying it started.
    """
    conn.execute(
        """
        insert into public.pipeline_runs (
            run_id, run_key, pipeline_name, business_date, table_name,
            extraction_started_at, extraction_window_start, extraction_window_end,
            lookback_days, extraction_status
        ) values (%s, %s, %s, %s, null, %s, %s, %s, %s, 'running')
        """,
        (
            record.run_id,
            record.run_key,
            record.pipeline_name,
            record.business_date,
            record.started_at or datetime.now(timezone.utc),
            record.window.window_start,
            record.window.window_end,
            record.window.lookback_days,
        ),
    )


def finish_run(conn: psycopg.Connection, record: RunRecord) -> None:
    """Write the run's full record: one row per table, then the run-level summary.

    Rewrites the run's own rows rather than appending, so calling it twice produces one record
    instead of two — the same "replace, do not accumulate" rule the staging tables follow.
    """
    rows_read, rows_extracted, rows_rejected = _totals(record.tables)
    ended = record.ended_at or datetime.now(timezone.utc)
    started = record.started_at

    with conn.cursor() as cursor:
        cursor.execute(
            "delete from public.pipeline_runs where run_id = %s", (record.run_id,)
        )

        for table in record.tables:
            cursor.execute(
                """
                insert into public.pipeline_runs (
                    run_id, run_key, pipeline_name, business_date, table_name,
                    extraction_started_at, extraction_ended_at, extraction_duration_seconds,
                    extraction_window_start, extraction_window_end, lookback_days,
                    extraction_status, rows_read, rows_extracted, rows_rejected, reject_reason
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.run_id,
                    record.run_key,
                    record.pipeline_name,
                    record.business_date,
                    table.table,
                    started,
                    ended,
                    table.duration_seconds,
                    record.window.window_start,
                    record.window.window_end,
                    record.window.lookback_days,
                    record.status,
                    table.rows_read,
                    table.rows_extracted,
                    table.rows_rejected,
                    table.reject_reason,
                ),
            )

        cursor.execute(
            """
            insert into public.pipeline_runs (
                run_id, run_key, pipeline_name, business_date, table_name,
                extraction_started_at, extraction_ended_at, extraction_duration_seconds,
                extraction_window_start, extraction_window_end, lookback_days,
                extraction_status, rows_read, rows_extracted, rows_rejected,
                validation_results, error_code, error_message
            ) values (%s, %s, %s, %s, null, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.run_id,
                record.run_key,
                record.pipeline_name,
                record.business_date,
                started,
                ended,
                int((ended - started).total_seconds()) if started else None,
                record.window.window_start,
                record.window.window_end,
                record.window.lookback_days,
                record.status,
                rows_read,
                rows_extracted,
                rows_rejected,
                psycopg.types.json.Jsonb(record.validation_results),
                record.error_code,
                record.error_message,
            ),
        )
