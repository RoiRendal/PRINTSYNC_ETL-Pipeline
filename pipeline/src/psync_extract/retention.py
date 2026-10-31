"""Retention (doc section 9).

Two lifetimes, deliberately different:

* **operational detail** — 90 days. The per-table rows and the run logs, both the JSON record and
  the text narrative. Useful while a problem is fresh, and no longer.
* **audit summary** — 24 months. The run-level row. It is the evidence that a published figure was
  produced correctly, and a question about last year's numbers arrives long after anyone would think
  to check.

Deletion is automated rather than manual, so it cannot be forgotten — or done early by hand while a
run is still under investigation. Nothing here touches a run younger than its lifetime.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

__all__ = [
    "AUDIT_DAYS",
    "OPERATIONAL_DAYS",
    "prune_logs",
    "prune_pipeline_runs",
]

OPERATIONAL_DAYS = 90
AUDIT_DAYS = 730

# The two files one run leaves behind, which age out together.
LOG_SUFFIXES = (".log", ".json")


def prune_logs(
    data_dir: Path | str,
    *,
    older_than_days: int = OPERATIONAL_DAYS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete run logs older than the operational lifetime; return what went.

    The directory is derived from ``data_dir`` rather than accepted as an argument, so this cannot
    be pointed at ``handover/`` or ``exports/``. The handover manifests are Stage 2's only input and
    the exports are what the submission bundle is built from; neither is operational detail, and a
    retention job that could delete them would be one mistaken path away from destroying the
    evidence it exists to keep.

    A run's two files are deleted together. A text log without the record it belongs to — or a
    record without its narrative — reads as evidence of a run whose other half was lost, when in
    fact the run simply aged out.
    """
    logs = Path(data_dir) / "logs"
    if not logs.is_dir():
        raise FileNotFoundError(
            f"no log directory at {logs}. Retention is scoped to <data dir>/logs; "
            "check PSYNC_DATA_DIR rather than assuming there is nothing to prune."
        )

    cutoff_epoch = (
        (now or datetime.now(timezone.utc)) - timedelta(days=older_than_days)
    ).timestamp()

    files = 0
    pairs = 0
    # The stage subfolders, and the logs directory itself for anything written straight into it.
    for directory in [logs, *(p for p in sorted(logs.iterdir()) if p.is_dir())]:
        stems = {
            path.stem
            for path in directory.iterdir()
            if path.is_file() and path.suffix in LOG_SUFFIXES
        }
        for stem in sorted(stems):
            present = [
                directory / f"{stem}{suffix}"
                for suffix in LOG_SUFFIXES
                if (directory / f"{stem}{suffix}").exists()
            ]
            # The newer of the two decides, so a .log written a moment after its .json does not
            # outlive it by a whole day.
            if max(path.stat().st_mtime for path in present) >= cutoff_epoch:
                continue
            for path in present:
                path.unlink()
                files += 1
            pairs += 1

    return {"files": files, "pairs": pairs}


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
