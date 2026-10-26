"""The batch's JSON log (doc section 8).

One file per batch, holding what section 8 hands over: the batch's identity and window, the counts
per output table, the outcome of every check, the rule counts and any error. It contains identifiers,
counts and timestamps only — no customer data (section 9).

Written by writing a temporary file and renaming it into place, so a crash never leaves a
half-written log that looks like a complete one. Named for the batch ID, which contains no colon —
but the same sanitiser as Stage 1 is used, so the two stages behave identically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

__all__ = ["build_log", "write_log"]

# Characters Windows forbids in a filename. The batch ID contains none, but the same sanitiser as
# Stage 1 is used so the two stages behave identically.
_ILLEGAL_IN_FILENAME = '<>:"/\\|?*'


def _safe_filename(name: str) -> str:
    return "".join("_" if character in _ILLEGAL_IN_FILENAME else character for character in name)


def build_log(
    *,
    batch_id: str,
    parent_run_id: str,
    business_date: str,
    window_start: str,
    window_end: str,
    decision: str,
    status: str,
    tables: Mapping[str, Mapping[str, Any]],
    rule_counts: Mapping[str, int],
    validation_results: Mapping[str, str],
    error_code: str | None = None,
    error_message: str | None = None,
    code_version: str = "",
) -> dict[str, Any]:
    """Assemble the log payload. Plain data only, so it serialises without surprises."""
    return {
        "batch_id": batch_id,
        "parent_run_id": parent_run_id,
        "business_date": business_date,
        "window": {"start": window_start, "end": window_end},
        "decision": decision,
        "status": status,
        "tables": dict(tables),
        "rules_applied": dict(rule_counts),
        "validation_results": dict(validation_results),
        "error": {"code": error_code, "message": error_message}
        if error_code or error_message
        else None,
        "code_version": code_version,
    }


def write_log(directory: Path | str, payload: Mapping[str, Any]) -> Path:
    """Write one file per batch, atomically, and return its path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    stem = _safe_filename(str(payload["batch_id"]))
    target = directory / f"{stem}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target
