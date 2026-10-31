"""Run one extraction day from the command line.

    python -m psync_extract --date 2026-10-17

This is the entry point that needs no scheduler and no server: it is what a demo runs, and what an
operator runs by hand when a night needs repeating. The Prefect flow calls the same function.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from psync_extract.config import ConfigurationError, load_settings
from psync_extract.pipeline import run_extraction

__all__ = ["main"]


def _summary(result) -> str:
    lines = [
        f"run_key    {result.run_key}",
        f"business   {result.business_date}",
        f"decision   {result.decision.decision}",
        f"reason     {result.decision.reason}",
    ]
    if result.tables:
        lines.append("tables")
        for table in result.tables:
            lines.append(
                f"  {table.table:26} read {table.rows_read:>4}  "
                f"written {table.rows_extracted:>4}  rejected {table.rows_rejected:>3}"
            )
    if result.results:
        checks = "  ".join(
            f"{check_id}={check.status}" for check_id, check in sorted(result.results.items())
        )
        lines.append(f"checks     {checks}")
    if result.log_path:
        lines.append(f"log        {result.log_path}")
    if result.handover is not None:
        lines.append("handover   written")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="psync_extract", description="Extract one business day from PRINTSYNC."
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="business date (YYYY-MM-DD); defaults to yesterday in the run time zone",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="the evidence folder; defaults to PSYNC_DATA_DIR, then <repo>/data. "
        "The logs and the handover are derived from it.",
    )
    args = parser.parse_args(argv)

    try:
        settings = load_settings(
            **({"psync_data_dir": args.data_dir} if args.data_dir else {})
        )
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    day = args.date or settings.resolved_business_date()
    result = run_extraction(settings, day)
    print(_summary(result))

    # A run that may not be handed over is a non-zero exit, so a scheduler notices.
    return 0 if result.decision.handover else 1


if __name__ == "__main__":
    raise SystemExit(main())
