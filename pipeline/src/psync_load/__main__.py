"""Run one load batch from the command line (doc section 1.3).

    python -m psync_load --batch TRF_20261024_d031cb6c

For now this resolves and prints the configuration. The pre-load gate, the bulk loader and the
validation set arrive in batches 2–4; the entry point stays the same, so a demo run does not change
shape as the stage is built.
"""

from __future__ import annotations

import argparse
import sys

from psync_load.config import ConfigurationError, code_version, load_settings

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Load one approved batch into the reporting database."""
    parser = argparse.ArgumentParser(
        prog="psync_load",
        description="Load one approved transformation batch into psync_warehouse.",
    )
    parser.add_argument(
        "--batch",
        required=True,
        help="the transformation batch_id to load, e.g. TRF_20261024_d031cb6c",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="the evidence folder; defaults to PSYNC_DATA_DIR, then <repo>/data",
    )
    args = parser.parse_args(argv)

    overrides: dict[str, object] = {"batch_id": args.batch}
    if args.data_dir is not None:
        overrides["psync_data_dir"] = args.data_dir

    try:
        settings = load_settings(**overrides)
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    print(f"batch      {settings.batch_id}")
    print(f"pipeline   {settings.pipeline_name}")
    print(f"timezone   {settings.run_timezone}")
    print(f"logs       {settings.log_directory}")
    print(f"version    {code_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
