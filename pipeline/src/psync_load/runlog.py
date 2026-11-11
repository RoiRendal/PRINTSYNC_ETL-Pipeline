"""The load's two log files (doc section 6.2).

The same pair Stages 1 and 2 write, so a reader who has followed one stage can follow this one:

* ``<stem>.log`` — the narrative, one line per step, flushed as it happens. A batch that dies half
  way still says how far it got.
* ``<stem>.json`` — the record, written once at the end. A run that fails never produces one.

Identifiers, counts and timings only — no row contents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID

__all__ = ["RunTrace", "log_stem"]

STAGE = "Load"


def log_stem(batch_id: str, run_id: UUID) -> str:
    """A filename-safe stem: the batch id plus the first eight characters of the run id.

    Keying on the batch alone would let a retry overwrite the attempt that failed, which is exactly
    the attempt someone needs to read.
    """
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in batch_id)
    return f"{safe}_{str(run_id)[:8]}"


def _stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


@dataclass
class RunTrace:
    """The load's timeline, streamed to ``<stem>.log`` while it happens."""

    directory: Path
    stem: str
    handle: TextIO
    steps: list[dict[str, Any]] = field(default_factory=list)
    _started: dict[str, datetime] = field(default_factory=dict)

    @classmethod
    def open(cls, directory: Path | str, stem: str) -> "RunTrace":
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        handle = (directory / f"{stem}.log").open("w", encoding="utf-8")
        return cls(directory=directory, stem=stem, handle=handle)

    def _write(self, level: str, step: str, message: str) -> None:
        # The stage is on every line, so a line quoted on its own still says which stage wrote it.
        self.handle.write(f"{_stamp()} | {level:<7} | [{STAGE}] | {step} | {message}\n")
        self.handle.flush()

    def begin(self, step: str) -> None:
        self._started[step] = datetime.now(timezone.utc)

    def done(self, step: str, message: str, level: str = "INFO") -> None:
        started = self._started.pop(step, None)
        elapsed = (
            (datetime.now(timezone.utc) - started).total_seconds() * 1000 if started else None
        )
        self.steps.append({"step": step, "ms": round(elapsed) if elapsed is not None else None})
        self._write(level, step, message)

    def info(self, step: str, message: str) -> None:
        self._write("INFO", step, message)

    def warn(self, step: str, message: str) -> None:
        self._write("WARN", step, message)

    def error(self, step: str, message: str) -> None:
        self._write("ERROR", step, message)

    def close(self) -> None:
        self.handle.close()

    def __enter__(self) -> "RunTrace":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def write_record(self, payload: dict[str, Any]) -> Path:
        """Write ``<stem>.json`` once, atomically, and return its path."""
        target = self.directory / f"{self.stem}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, default=_encode), encoding="utf-8"
        )
        temporary.replace(target)
        return target


def _encode(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)
