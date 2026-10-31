"""Run one transformation batch from the command line.

    python -m psync_transform --date 2026-10-17
    python -m psync_transform --date 2026-10-17 --parent-run 618f1325-…
    python -m psync_transform --export TRF_20261017_618f1325

This is the entry point that needs no scheduler and no server: it is what a demo runs, and what an
operator runs by hand when a night needs repeating. The Prefect flow calls the same function.

``--export`` is the other half of the evidence: it renders a batch that already ran into a folder a
panel can open, and runs no batch of its own.

The exit code is what a scheduler notices: 0 when the batch may be handed over, 1 when it may not,
2 when the configuration is missing or invalid.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from uuid import UUID

from psync_transform.config import ConfigurationError, Settings, load_settings
from psync_transform.db import connect_target
from psync_transform.export import ExportError, export_batch
from psync_transform.pipeline import run_transformation

__all__ = ["main"]


def _summary(result) -> str:
    lines = [
        f"batch_id   {result.batch.batch_id}",
        f"business   {result.batch.business_date}",
        f"window     {result.batch.window_start} -> {result.batch.window_end}",
        f"decision   {result.decision.decision}",
        f"reason     {result.decision.reason}",
    ]
    if result.checks:
        lines.append(
            "checks     "
            + "  ".join(f"{k}={v}" for k, v in sorted(result.checks.items()))
        )
    if result.log_path:
        lines.append(f"log        {result.log_path}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psync_transform",
        description="Transform one extraction handover for PRINTSYNC.",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="business date (YYYY-MM-DD); defaults to yesterday in the run time zone",
    )
    parser.add_argument(
        "--parent-run",
        type=UUID,
        default=None,
        help="transform one specific extraction run; defaults to the most recent handover",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="the evidence folder; defaults to PSYNC_DATA_DIR, then <repo>/data. "
        "The handover is read from it and the log is written to it.",
    )
    parser.add_argument(
        "--export",
        metavar="BATCH_ID",
        default=None,
        help="write one batch's quarantine evidence to <data dir>/exports/<batch_id>/ and exit. "
        "No batch is run, so no ledger row and no log are written.",
    )
    args = parser.parse_args(argv)

    overrides: dict[str, object] = {
        "business_date": args.date,
        "parent_run_id": args.parent_run,
    }
    if args.data_dir is not None:
        overrides["psync_data_dir"] = args.data_dir

    try:
        settings = load_settings(**overrides)
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.export:
        return _export(settings, args.export)

    try:
        result = run_transformation(settings)
    except Exception as exc:  # noqa: BLE001 - the CLI is the last line of defence
        print(f"transformation error: {exc}", file=sys.stderr)
        return 1

    print(_summary(result))

    # A run that may not be handed over is a non-zero exit, so a scheduler notices.
    return 0 if "APPROVED" in result.decision.decision else 1


def _export(settings: Settings, batch_id: str) -> int:
    """Render one batch's quarantine evidence and report where it went."""
    try:
        with connect_target(settings) as conn:
            result = export_batch(conn, batch_id, settings.exports_directory)
    except ExportError as exc:
        print(f"export error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - the CLI is the last line of defence
        print(f"export error: {exc}", file=sys.stderr)
        return 1

    print(f"export     {result.directory}")
    print(f"rows       {result.rows}")
    print(f"rules      {result.rules}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
