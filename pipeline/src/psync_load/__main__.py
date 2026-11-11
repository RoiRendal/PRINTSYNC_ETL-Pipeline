"""Run one load batch from the command line (doc section 1.3).

    python -m psync_load --batch TRF_20261024_d031cb6c

The entry point resolves the handover, runs the L1–L6 pre-load gate, and loads the batch in one
transaction. The post-load checks and the decision engine arrive in batches 4 and 5; the command
stays the same, so a demo run does not change shape as the stage is built.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from psync_load.config import ConfigurationError, code_version, load_settings
from psync_load.handover import HandoverError, load_handover
from psync_load.loader import LoadError, load_batch
from psync_load.runs import record_finish, record_start
from psync_load.validation import run_pre_load_checks

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Resolve one approved batch, gate it, and load it."""
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

    try:
        handover = load_handover(settings)
    except HandoverError as exc:
        print(f"handover error: {exc}", file=sys.stderr)
        return 1

    print(f"batch      {handover.batch_id}")
    print(f"window     {handover.window_start} -> {handover.window_end}")
    print(f"decision   {handover.decision} / {handover.status}")
    print(f"version    {code_version()}")

    checks = run_pre_load_checks(settings, handover)
    print("checks     " + "  ".join(f"{k}={v.status}" for k, v in sorted(checks.items())))
    for check_id, result in sorted(checks.items()):
        if result.status != "PASS":
            print(f"  {check_id}: {result.message}", file=sys.stderr)

    failed = [result for result in checks.values() if result.is_critical_failure]
    if failed:
        print(
            f"pre-load gate failed: {len(failed)} critical check(s). Nothing was written.",
            file=sys.stderr,
        )
        return 1

    run_id = uuid.uuid4()
    record_start(settings, handover, run_id)
    try:
        loaded = load_batch(settings, handover, run_id)
    except (LoadError, Exception) as exc:  # noqa: BLE001 - a failed load must be recorded
        record_finish(
            settings,
            run_id,
            status="failed",
            error_code="LOAD_FAILED",
            error_message=str(exc)[:500],
        )
        print(f"load failed: {exc}", file=sys.stderr)
        print("rolled back — no rows from this batch were published", file=sys.stderr)
        return 1

    record_finish(settings, run_id, status="success", loaded=loaded)

    for table in loaded:
        print(f"  {table:<28} {loaded[table]:>4} row(s)")
    print(f"loaded     {sum(loaded.values())} rows in one transaction")
    print("post-load checks arrive in batch 4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
