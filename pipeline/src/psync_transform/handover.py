"""Reading the extraction handover (doc section 1.1).

Stage 2's only input is the package Stage 1 writes on approval: ``<run_key>_<run_id[:8]>.handover.json``
(extraction documentation, section 7.3). It is a **manifest, not a copy of the data** — the rows
stay in the ``stg_*`` tables and are selected by ``run_id``. What the manifest carries is what this
stage cannot derive for itself: the run's identity, its decision, and the counts to reconcile
against.

Two rules shape this module:

* **the manifest is the only place the decision lives.** ``pipeline_runs.extraction_status``
  collapses ``APPROVED`` and ``APPROVED WITH WARNING`` into ``success``, and re-deriving Stage 1's
  verdict here would be re-checking its work (doc requirement D2). If the manifest says
  ``REJECTED``, there is nothing to transform.
* **ambiguity is an error, not a coin flip.** Two manifests for one business date mean two
  handovers, and picking one would publish a day from a batch nobody chose. The operator names the
  run with ``--parent-run``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

__all__ = [
    "ACCEPTED_DECISIONS",
    "Handover",
    "HandoverError",
    "find_manifest",
    "load_handover",
]

# The decisions that may be transformed (doc section 1.1). Stage 1 writes no manifest at all for
# any other decision, so these two are also the only ones that can appear.
ACCEPTED_DECISIONS: tuple[str, ...] = ("APPROVED", "APPROVED WITH WARNING")

MANIFEST_SUFFIX = ".handover.json"


class HandoverError(RuntimeError):
    """The handover is missing, unreadable, or ambiguous."""


@dataclass(frozen=True)
class Handover:
    """One extraction handover, as Stage 1 wrote it."""

    run_id: UUID
    run_key: str
    business_date: date
    decision: str
    window_start: datetime
    window_end: datetime
    staging_tables: tuple[str, ...]
    counts: Mapping[str, Mapping[str, int]]
    validation_results: Mapping[str, str]
    rejects: Mapping[str, int]
    error_code: str | None
    error_message: str | None
    path: Path

    def rows_extracted(self, source_table: str) -> int:
        """How many rows Stage 1 says it wrote for a source table.

        A table missing from the manifest is an error rather than zero: "the manifest does not
        mention this table" and "the table was empty" are different facts, and only the second one
        is safe to treat as zero.
        """
        try:
            return int(self.counts[source_table]["rows_extracted"])
        except KeyError:
            raise HandoverError(
                f"the handover for {self.business_date} does not report counts for "
                f"{source_table!r}; it reports {sorted(self.counts)}"
            ) from None

    def rows_rejected(self, source_table: str) -> int:
        return int(self.counts.get(source_table, {}).get("rows_rejected", 0))


def _required(payload: Mapping[str, Any], key: str, path: Path) -> Any:
    try:
        return payload[key]
    except KeyError:
        raise HandoverError(f"{path.name} is missing {key!r}") from None


def read_manifest(path: Path) -> Handover:
    """Parse one manifest file. Raises :class:`HandoverError` on anything unexpected."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HandoverError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HandoverError(f"{path.name} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HandoverError(f"{path.name} does not contain a JSON object")

    try:
        return Handover(
            run_id=UUID(str(_required(payload, "run_id", path))),
            run_key=str(_required(payload, "run_key", path)),
            business_date=date.fromisoformat(str(_required(payload, "business_date", path))),
            decision=str(_required(payload, "decision", path)),
            window_start=datetime.fromisoformat(str(_required(payload, "window_start", path))),
            window_end=datetime.fromisoformat(str(_required(payload, "window_end", path))),
            staging_tables=tuple(payload.get("staging_tables", ())),
            counts=payload.get("counts", {}),
            validation_results=payload.get("validation_results", {}),
            rejects=payload.get("rejects", {}),
            error_code=payload.get("error_code"),
            error_message=payload.get("error_message"),
            path=path,
        )
    except ValueError as exc:
        raise HandoverError(f"{path.name} holds a value that cannot be read: {exc}") from exc


def find_manifest(
    directory: Path | str,
    business_date: date,
    parent_run_id: UUID | None = None,
) -> Path:
    """The manifest for one business date.

    Selection is by the manifest's own ``business_date``, not by its filename: the name embeds the
    run key, and a filename is a label while the field is a fact.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise HandoverError(
            f"the handover directory does not exist: {directory}. Stage 1 writes it beside its "
            "logs; check HANDOVER_DIR and whether the extraction ran on this host."
        )

    matches: list[Handover] = []
    for path in sorted(directory.glob(f"*{MANIFEST_SUFFIX}")):
        handover = read_manifest(path)
        if handover.business_date != business_date:
            continue
        if parent_run_id is not None and handover.run_id != parent_run_id:
            continue
        matches.append(handover)

    if not matches:
        pinned = f" for run {parent_run_id}" if parent_run_id else ""
        raise HandoverError(
            f"no handover for {business_date}{pinned} in {directory}. Either the extraction has "
            "not run, or it did not reach APPROVED or APPROVED WITH WARNING — Stage 1 writes no "
            "manifest for any other decision."
        )

    if len(matches) > 1:
        listed = ", ".join(str(handover.run_id) for handover in matches)
        raise HandoverError(
            f"{len(matches)} handovers exist for {business_date} ({listed}). Transform one of them "
            "explicitly with --parent-run; choosing one automatically would publish a day from a "
            "batch nobody selected."
        )

    return matches[0].path


def load_handover(
    directory: Path | str,
    business_date: date,
    parent_run_id: UUID | None = None,
) -> Handover:
    """Find and parse the one handover for a business date."""
    return read_manifest(find_manifest(directory, business_date, parent_run_id))
