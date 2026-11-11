"""Pre-load snapshots (doc section 7).

The normal failure path is the transaction rollback: a batch that fails leaves nothing behind. The
snapshot covers the other case — a load that commits and is *later* found to be wrong. It is taken
from the warehouse as it stands before the first write, one CSV per reporting table, under
``<data dir>/snapshots/<batch_id>/``.

Snapshots live seven days, not ninety: the table itself is still in the warehouse, so this is a
convenience for undoing a mistake, not the record of what was published.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from psync_load.config import Settings
from psync_load.handover import REPORTING_TABLES, Handover

__all__ = ["write_snapshot"]


def write_snapshot(
    target: psycopg.Connection, settings: Settings, handover: Handover
) -> Path:
    """Stream the eight reporting tables to CSV. Returns the directory written.

    Each file is written to a temporary name and renamed when complete, so an interrupted snapshot
    cannot be mistaken for a whole one.
    """
    directory = settings.snapshot_directory / handover.batch_id
    directory.mkdir(parents=True, exist_ok=True)

    for table in REPORTING_TABLES:
        destination = directory / f"{table}.csv"
        temporary = destination.with_suffix(".csv.part")
        with temporary.open("wb") as handle, target.cursor() as cursor:
            with cursor.copy(
                f"copy public.{table} to stdout with (format csv, header true)"
            ) as outgoing:
                for chunk in outgoing:
                    handle.write(chunk)
        temporary.replace(destination)

    return directory
