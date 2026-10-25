"""The handover package (doc section 7.3).

On approval, six things pass to Transformation: the staged data, the run record, the counts, the
check results, the rejects, and any error. This module assembles that as one document and writes it
beside the run's log.

It is a manifest, not a copy: the data itself stays in the `stg_*` tables, identified by `run_id`
and `business_date`. Duplicating rows into a file would create a second version of the truth.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from psync_extract.decisions import Decision
from psync_extract.runs import RunRecord
from psync_extract.staging import STAGING_TABLES

__all__ = ["HandoverPackage", "build_handover", "write_handover"]


@dataclass(frozen=True)
class HandoverPackage:
    """What Transformation is told, and where to find the rows."""

    run_id: str
    run_key: str
    business_date: str
    decision: str
    window_start: str
    window_end: str
    staging_tables: tuple[str, ...]
    counts: dict[str, dict[str, int]]
    validation_results: dict[str, str]
    rejects: dict[str, int]
    error_code: str | None
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_handover(record: RunRecord, decision: Decision) -> HandoverPackage | None:
    """Build the package, or nothing at all when the run may not be handed over."""
    if not decision.handover:
        return None

    counts = {
        table.table: {
            "rows_read": table.rows_read,
            "rows_extracted": table.rows_extracted,
            "rows_rejected": table.rows_rejected,
        }
        for table in record.tables
    }
    rejects = {t.table: t.rows_rejected for t in record.tables if t.rows_rejected}

    return HandoverPackage(
        run_id=record.run_id,
        run_key=record.run_key,
        business_date=record.business_date.isoformat(),
        decision=decision.decision,
        window_start=record.window.window_start.isoformat(),
        window_end=record.window.window_end.isoformat(),
        staging_tables=tuple(STAGING_TABLES.values()),
        counts=counts,
        validation_results=record.validation_results,
        rejects=rejects,
        error_code=record.error_code,
        error_message=record.error_message,
    )


def write_handover(directory: Path | str, package: HandoverPackage) -> Path:
    """Write ``<run_key>_<run_id>.handover.json`` atomically and return its path.

    Keyed on the run, not just the day, so a re-run cannot replace the package that was actually
    handed over.
    """
    from psync_extract.runlog import _safe_filename

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    stem = _safe_filename(package.run_key)
    target = directory / f"{stem}_{package.run_id[:8]}.handover.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(package.to_dict(), indent=2, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
    return target
