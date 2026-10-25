"""Retention (doc section 9).

Two lifetimes, deliberately different:

* **operational detail** — 90 days. The per-table rows and the JSON logs. Useful while a problem is
  fresh, and no longer.
* **audit summary** — 24 months. The run-level row. It is the evidence that a published figure was
  produced correctly, and a question about last year's numbers arrives long after anyone would think
  to check.

Deletion is automated rather than manual, so it cannot be forgotten — or done early by hand while a
run is still under investigation. Nothing here touches a run younger than its lifetime.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

__all__ = [
    "AUDIT_DAYS",
    "OPERATIONAL_DAYS",
    "prune_json_logs",
    "prune_pipeline_runs",
]

OPERATIONAL_DAYS = 90
AUDIT_DAYS = 730


def prune_json_logs(
    directory: Path | str,
    *,
    older_than_days: int = OPERATIONAL_DAYS,
    now: datetime | None = None,
) -> int:
    """Delete JSON logs older than the operational lifetime; return how many went."""
    directory = Path(directory)
    if not directory.is_dir():
        return 0

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=older_than_days)
    cutoff_epoch = cutoff.timestamp()

    removed = 0
    for path in directory.glob("*.json"):
        if path.stat().st_mtime < cutoff_epoch:
            path.unlink()
            removed += 1
    return removed


def prune_pipeline_runs(
    conn: psycopg.Connection,
    *,
    operational_days: int = OPERATIONAL_DAYS,
    audit_days: int = AUDIT_DAYS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Prune per-table rows at 90 days and run-level rows at 24 months.

    Returns the counts, so a retention job can say what it did rather than quietly deleting.
    """
    current = now or datetime.now(timezone.utc)
    operational_cutoff = current - timedelta(days=operational_days)
    audit_cutoff = current - timedelta(days=audit_days)

    with conn.cursor() as cursor:
        cursor.execute(
            "delete from public.pipeline_runs "
            "where table_name is not null and extraction_started_at < %s",
            (operational_cutoff,),
        )
        table_rows = cursor.rowcount

        cursor.execute(
            "delete from public.pipeline_runs "
            "where table_name is null and extraction_started_at < %s",
            (audit_cutoff,),
        )
        run_rows = cursor.rowcount

    return {"table_rows": table_rows, "run_rows": run_rows}
