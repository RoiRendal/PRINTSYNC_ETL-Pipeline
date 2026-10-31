"""The run's JSON log and its streamed text log (doc section 4).

Two files per run, one stem, two jobs:

* ``<stem>.json`` is the **record**. Written once, at the end, by writing a temporary file and
  renaming it into place, so a crash never leaves a half-written log that looks like a complete one.
  It holds what section 7.3 hands over: the run's identity and window, the counts per table, the
  outcome of every check, the rejects, and any error.
* ``<stem>.log`` is the **narrative**. One line per step, flushed as each step completes, so a run
  that dies half way still says how far it got and what it was doing. The JSON is the only file a
  successful run needs; the text file is what a reader follows.

Both are renderings of the same step list, so the two cannot disagree about what happened. They
contain identifiers, counts and timestamps only — no customer data (section 9).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = ["RunTrace", "build_log", "log_stem", "write_log"]

# Characters Windows forbids in a filename. `run_key` contains a colon by design
# ("psync_nightly_analytics:2026-10-04"), so it cannot be used as a name unchanged — the colon is
# kept inside the payload and replaced only in the filename.
_ILLEGAL_IN_FILENAME = '<>:"/\\|?*'


def _safe_filename(name: str) -> str:
    return "".join("_" if character in _ILLEGAL_IN_FILENAME else character for character in name)


def log_stem(run_key: str, run_id: str) -> str:
    """The one name a run's two files share.

    Named for the ``run_key`` *and* the run's id: the key identifies the business day, but a day can
    legitimately be run more than once (a retry, or a repeat that is skipped). Keying the filename
    on the key alone meant the second run's log replaced the first — losing the evidence of the
    extraction that actually happened. Both writers call this, so the pair cannot drift apart.
    """
    return f"{_safe_filename(str(run_key))}_{str(run_id)[:8]}"


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
    steps: Sequence[Mapping[str, Any]] = (),
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
        "steps": [dict(step) for step in steps],
        "tables": dict(tables),
        "validation_results": dict(validation_results),
        "rejects": dict(rejects or {}),
        "error": {"code": error_code, "message": error_message}
        if error_code or error_message
        else None,
    }


def write_log(directory: Path | str, payload: Mapping[str, Any]) -> Path:
    """Write one file per **run**, atomically, and return its path.

    The name comes from :func:`log_stem`, so this file and the streamed text log of the same run
    always share a stem and can never be matched to the wrong run.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    stem = log_stem(payload["run_key"], payload["run_id"])
    target = directory / f"{stem}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
    return target


class RunTrace:
    """The run's timeline, streamed to ``<stem>.log`` while it happens (doc section 4).

    The JSON log is the record: written once, at the end, atomically. This is the narrative: one
    line per step, flushed as the step completes, so a run that dies half way still says how far it
    got and what it was doing. ``steps`` is what the JSON log records, so the two files are two
    renderings of one list and cannot disagree.

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
        """Close the narrative with the failure. A run that raised writes no JSON at all.

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
