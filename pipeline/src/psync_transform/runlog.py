"""The batch's JSON log and its streamed text log (doc section 8).

Two files per batch, one stem, two jobs:

* ``<stem>.json`` is the **record**. Written once, at the end, by writing a temporary file and
  renaming it into place, so a crash never leaves a half-written log that looks like a complete one.
  It holds what section 8 hands over: the batch's identity and window, the counts per output table,
  the outcome of every check, the rule counts and any error.
* ``<stem>.log`` is the **narrative**. One line per step, flushed as each step completes, so a batch
  that dies half way still says how far it got and what it was doing.

Both are renderings of the same step list, so the two cannot disagree about what happened. They
contain identifiers, counts and timestamps only — no customer data (section 9).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = ["RunTrace", "build_log", "log_stem", "write_log"]

# Characters Windows forbids in a filename. The batch ID contains none, but the same sanitiser as
# Stage 1 is used so the two stages behave identically.
_ILLEGAL_IN_FILENAME = '<>:"/\\|?*'


def _safe_filename(name: str) -> str:
    return "".join("_" if character in _ILLEGAL_IN_FILENAME else character for character in name)


def log_stem(batch_id: str) -> str:
    """The one name a batch's two files share.

    The batch ID already identifies one batch — ``TRF_20261017_618f1325`` carries the date and the
    parent run's prefix — so no further key is needed. Both writers call this, so the pair cannot
    drift apart.
    """
    return _safe_filename(str(batch_id))


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
    steps: Sequence[Mapping[str, Any]] = (),
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
        "steps": [dict(step) for step in steps],
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

    target = directory / f"{log_stem(payload['batch_id'])}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


class RunTrace:
    """The batch's timeline, streamed to ``<stem>.log`` while it happens (doc section 8).

    The same shape as Stage 1's, deliberately: a reader who has followed one stage's log can follow
    the other's. The JSON log is the record, written once at the end; this is the narrative, flushed
    line by line, so a batch that dies half way still says how far it got.

    Identifiers, counts and timings only — no row contents (doc section 9).
    """

    def __init__(self, directory: Path | str, stem: str, *, title: str) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self._path = directory / f"{_safe_filename(stem)}.log"
        # Line buffered: a crash has to leave the lines already written, not an empty file.
        self._handle = self._path.open("w", encoding="utf-8", buffering=1)
        self._steps: list[dict[str, Any]] = []
        self._closed = False
        self._failed = False
        self._write("INFO", "run", title)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def steps(self) -> tuple[dict[str, Any], ...]:
        """The steps so far, for the JSON log. A copy, so a caller cannot rewrite history."""
        return tuple(dict(step) for step in self._steps)

    def _write(self, level: str, name: str, message: str) -> None:
        """One line. The stamp carries its UTC offset, so a log line and a `timestamptz` row agree."""
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
        self._handle.write(f"{stamp} | {level:<7} | {name} | {message}\n")

    def step(self, name: str, message: str, *, seconds: float | None = None) -> None:
        """Record one completed step, with how long it took when the caller measured it."""
        self._steps.append(
            {"step": name, "ms": None if seconds is None else round(seconds * 1000)}
        )
        suffix = "" if seconds is None else f" in {seconds:.1f}s"
        self._write("INFO", name, f"{message}{suffix}")

    def failed(self, error: BaseException) -> None:
        """Close the narrative with the failure. A batch that raised writes no JSON at all.

        Safe to call twice, and safe to call on a trace that has already been closed: the line is
        written at most once, by whichever of ``failed`` and ``__exit__`` gets there first.
        """
        if self._closed or self._failed:
            return
        self._failed = True
        self._steps.append({"step": "failed", "ms": None})
        self._write("ERROR", "failed", f"{type(error).__name__}: {error}")

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._handle.close()

    def __enter__(self) -> "RunTrace":
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Record an exception that passed through the block, then close.

        The failure line has to be written *before* the handle closes, so the context manager
        writes it rather than leaving the caller to call :meth:`failed` on a closed file.
        """
        error = exc_info[1] if len(exc_info) > 1 else None
        if isinstance(error, BaseException):
            self.failed(error)
        self.close()
