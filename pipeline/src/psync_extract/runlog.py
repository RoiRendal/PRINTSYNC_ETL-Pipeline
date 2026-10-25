"""The run's JSON log (doc section 7.3).

One file per run, holding what section 7.3 hands over: the run's identity and window, the counts
per table, the outcome of every check, the rejects, and any error. It contains identifiers, counts
and timestamps only — no customer data (section 9).

Written by writing a temporary file and renaming it into place, so a crash never leaves a
half-written log that looks like a complete one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

__all__ = ["build_log", "write_log"]

# Characters Windows forbids in a filename. `run_key` contains a colon by design
# ("psync_nightly_analytics:2026-10-04"), so it cannot be used as a name unchanged — the colon is
# kept inside the payload and replaced only in the filename.
_ILLEGAL_IN_FILENAME = '<>:"/\\|?*'


def _safe_filename(name: str) -> str:
    return "".join("_" if character in _ILLEGAL_IN_FILENAME else character for character in name)


def build_log(
    *,
    run_id: str,
    run_key: str,
    business_date: str,
    window_start: str,
    window_end: str,
    lookback_days: int,
    decision: str,
    status: str,
    tables: Mapping[str, Mapping[str, Any]],
    validation_results: Mapping[str, str],
    rejects: Mapping[str, int] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Assemble the log payload. Plain data only, so it serialises without surprises."""
    return {
        "run_id": run_id,
        "run_key": run_key,
        "business_date": business_date,
        "window": {
            "start": window_start,
            "end": window_end,
            "lookback_days": lookback_days,
        },
        "decision": decision,
        "status": status,
        "tables": dict(tables),
        "validation_results": dict(validation_results),
        "rejects": dict(rejects or {}),
        "error": {"code": error_code, "message": error_message}
        if error_code or error_message
        else None,
    }


def write_log(directory: Path | str, payload: Mapping[str, Any]) -> Path:
    """Write ``<run_key>.json`` atomically and return its path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    target = directory / f"{_safe_filename(str(payload['run_key']))}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
    return target
