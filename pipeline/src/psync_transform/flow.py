"""The Prefect flow for the transformation stage (doc section 1.2).

A thin wrapper around :func:`psync_transform.pipeline.run_transformation`, so what the scheduler runs
and what a demo runs are the same code. The extraction flow triggers this one on its success — a
failed extraction can never be followed by a transformation of yesterday's staging rows.

Prefect is an **optional extra**, not a dependency (``pip install -e ".[orchestration]"``). That
keeps the installed package free of an orchestration framework, which is one of the project's
constraints, while leaving the scheduled path one import away.
"""

from __future__ import annotations

from pathlib import Path

try:
    from prefect import flow
except ImportError as exc:  # the base install, which has no orchestration framework
    raise ImportError(
        "The Prefect flows are an optional extra and Prefect is not installed. "
        'Install it with: pip install -e ".[orchestration]"\n'
        "The pipeline itself does not need it: python -m psync_transform --date YYYY-MM-DD"
    ) from exc

from psync_transform.config import load_settings
from psync_transform.pipeline import run_transformation

__all__ = ["transformation_flow"]


@flow(name="psync_nightly_analytics-transformation")
def transformation_flow(
    business_date: str | None = None,
    parent_run_id: str | None = None,
    data_dir: Path | None = None,
) -> None:
    """Transform one extraction handover for PRINTSYNC.

    ``data_dir`` is the evidence folder shared with Stage 1: the handover is read from it and the
    log is written to it, so redirecting one redirects the other.
    """
    overrides: dict[str, object] = {
        "business_date": business_date,
        "parent_run_id": parent_run_id,
    }
    if data_dir is not None:
        overrides["psync_data_dir"] = data_dir
    settings = load_settings(**overrides)
    result = run_transformation(settings)
    print(f"decision   {result.decision.decision}")
    print(f"reason     {result.decision.reason}")
    if result.log_path:
        print(f"log        {result.log_path}")
