"""Retention (doc section 7).

Two lifetimes, deliberately different:

* **operational detail** — 90 days. The load's two log files and the pre-load snapshots. Useful
  while a problem is fresh, and no longer.
* **audit summary** — 24 months. The `load_runs` ledger and `load_rejects`. They are the evidence
  that a published day was produced correctly, and a question about last year's numbers arrives long
  after anyone would think to look.

Deletion is automated rather than manual, so it cannot be forgotten — or done early by hand while a
run is still under investigation. Nothing here touches a run younger than its lifetime.

The directory is always derived from the data dir, never accepted as an argument. That is what stops
this job reaching ``handover/``, ``exports/`` or ``submission/``: the handover manifests are Stage
2's only input, the exports are what the submission bundle is built from, and a retention job that
could delete them would be one mistaken path away from destroying the evidence it exists to keep.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

__all__ = [
    "AUDIT_DAYS",
    "OPERATIONAL_DAYS",
    "SNAPSHOT_DAYS",
    "prune_load_logs",
    "prune_snapshots",
]

OPERATIONAL_DAYS = 90
AUDIT_DAYS = 730
SNAPSHOT_DAYS = 7

# The two files one run leaves behind, which age out together.
LOG_SUFFIXES = (".log", ".json")


def _age_days(path: Path, now: datetime) -> float:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (now - modified).total_seconds() / 86400


def prune_load_logs(
    data_dir: Path | str,
    *,
    older_than_days: int = OPERATIONAL_DAYS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete load logs older than the operational lifetime; return what went.

    A run's two files are deleted together. A narrative without the record it belongs to — or a
    record without its narrative — reads as evidence of a run whose other half was lost, when in
    fact the run simply aged out.
    """
    logs = Path(data_dir) / "logs" / "load"
    if not logs.is_dir():
        raise FileNotFoundError(
            f"no load log directory at {logs}. Retention is scoped to <data dir>/logs/load; "
            "check PSYNC_DATA_DIR rather than assuming there is nothing to prune."
        )

    moment = now or datetime.now(timezone.utc)
    removed = 0
    freed = 0

    stems: dict[str, list[Path]] = {}
    for path in logs.iterdir():
        if path.suffix in LOG_SUFFIXES and path.is_file():
            stems.setdefault(path.stem, []).append(path)

    for paths in stems.values():
        if any(_age_days(path, moment) < older_than_days for path in paths):
            continue
        for path in paths:
            freed += path.stat().st_size
            path.unlink()
            removed += 1

    return {"files": removed, "bytes": freed}


def prune_snapshots(
    data_dir: Path | str,
    *,
    older_than_days: int = SNAPSHOT_DAYS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete snapshot directories older than their shorter lifetime.

    Snapshots exist for the mistake found *after* a commit. A week is long enough to notice one; the
    table itself is still in the warehouse, so the snapshot is a convenience, not the record.
    """
    root = Path(data_dir) / "snapshots"
    if not root.is_dir():
        return {"directories": 0, "bytes": 0}

    moment = now or datetime.now(timezone.utc)
    removed = 0
    freed = 0
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        files = [path for path in directory.rglob("*") if path.is_file()]
        if not files:
            directory.rmdir()
            continue
        if any(_age_days(path, moment) < older_than_days for path in files):
            continue
        for path in files:
            freed += path.stat().st_size
            path.unlink()
        for path in sorted(directory.rglob("*"), reverse=True):
            if path.is_dir():
                path.rmdir()
        directory.rmdir()
        removed += 1

    return {"directories": removed, "bytes": freed}


def _main(argv: list[str] | None = None) -> int:
    """``python -m psync_load.retention [--dry-run]`` — the nightly retention job."""
    import argparse
    import sys

    from psync_load.config import load_settings

    parser = argparse.ArgumentParser(prog="python -m psync_load.retention")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be deleted, change nothing"
    )
    args = parser.parse_args(argv)

    settings = load_settings(batch_id=None)
    data_dir = settings.psync_data_dir

    if args.dry_run:
        logs = data_dir / "logs" / "load"
        snaps = data_dir / "snapshots"
        print(f"logs      {len(list(logs.glob('*.log'))) if logs.is_dir() else 0} narrative file(s)")
        print(f"snapshots {len(list(snaps.iterdir())) if snaps.is_dir() else 0} directory(ies)")
        print("dry run — nothing was deleted")
        return 0

    logs = prune_load_logs(data_dir)
    snaps = prune_snapshots(data_dir)
    print(f"deleted {logs['files']} log file(s), {logs['bytes'] // 1024} KB")
    print(f"deleted {snaps['directories']} snapshot directory(ies), {snaps['bytes'] // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
