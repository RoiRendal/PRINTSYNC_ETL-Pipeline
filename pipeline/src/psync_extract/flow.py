"""The Prefect wrapper (doc section 7.1's "runs at 01:00" story).

Deliberately thin: it resolves the day and calls :func:`psync_extract.pipeline.run_extraction`.
Nothing is reimplemented here, so what a demo runs and what a schedule runs cannot drift apart.

It is kept separate from the pipeline module on purpose — Prefect is the orchestration layer, and
the extraction has to work whether or not a scheduler is available. See ``python -m psync_extract``
for the version that needs no server at all.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from prefect import flow

from psync_extract.config import load_settings
from psync_extract.pipeline import RunResult, run_extraction

__all__ = ["extraction_flow"]


@flow(name="psync_nightly_analytics", log_prints=True)
def extraction_flow(
    business_date: date | None = None,
    log_directory: Path = Path("logs"),
    handover_directory: Path = Path("handover"),
) -> RunResult:
    """Extract one business day and return the decision."""
    settings = load_settings()
    day = business_date or settings.resolved_business_date()

    result = run_extraction(
        settings, day, log_directory=log_directory, handover_directory=handover_directory
    )
    print(f"{result.run_key}: {result.decision.decision} — {result.decision.reason}")
    return result
