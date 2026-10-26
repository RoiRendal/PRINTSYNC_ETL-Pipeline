"""The Prefect flow for the transformation stage (doc section 1.2).

A thin wrapper around :func:`psync_transform.pipeline.run_transformation`, so what the scheduler runs
and what a demo runs are the same code. The extraction flow triggers this one on its success — a
failed extraction can never be followed by a transformation of yesterday's staging rows.
"""

from __future__ import annotations

from pathlib import Path

from prefect import flow

from psync_transform.config import load_settings
from psync_transform.pipeline import run_transformation

__all__ = ["transformation_flow"]


@flow(name="psync_nightly_analytics-transformation")
def transformation_flow(
    business_date: str | None = None,
    parent_run_id: str | None = None,
    log_directory: Path | str = "logs",
) -> None:
    """Transform one extraction handover for PRINTSYNC."""
    settings = load_settings(
        business_date=business_date, parent_run_id=parent_run_id
    )
    result = run_transformation(settings, log_directory=log_directory)
    print(f"decision   {result.decision.decision}")
    print(f"reason     {result.decision.reason}")
    if result.log_path:
        print(f"log        {result.log_path}")
