"""Run one load batch from the command line (doc section 1.3).

    python -m psync_load --batch TRF_20261024_d031cb6c

The entry point resolves the handover, runs the L1–L6 pre-load gate, loads the batch in one
transaction, and runs L7–L13 before committing. The decision engine and the log pair arrive in
batch 5; the command stays the same.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from psync_load.config import ConfigurationError, code_version, load_settings
from psync_load.handover import HandoverError, load_handover
from psync_load.loader import load_batch
from psync_load.runs import record_finish, record_start
from psync_load.validation import run_post_load_checks, run_pre_load_checks

__all__ = ["main"]


def _print_checks(label: str, checks: dict) -> None:
    print(f"{label:<10} " + "  ".join(f"{k}={v.status}" for k, v in sorted(checks.items())))
    for check_id, result in sorted(checks.items()):
        if result.status != "PASS":
            print(f"  {check_id}: {result.message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Resolve one approved batch, gate it, load it, and verify it."""
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

    pre = run_pre_load_checks(settings, handover)
    _print_checks("pre-load", pre)
    if any(result.is_critical_failure for result in pre.values()):
        print("pre-load gate failed. Nothing was written.", file=sys.stderr)
        return 1

    run_id = uuid.uuid4()
    record_start(settings, handover, run_id)
    try:
        outcome = load_batch(settings, handover, run_id, validate=run_post_load_checks)
    except Exception as exc:  # noqa: BLE001 - a failed load must be recorded
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

    _print_checks("post-load", outcome.checks)

    inserted = {table: load.inserted for table, load in outcome.loads.items()}
    if not outcome.committed:
        record_finish(
            settings,
            run_id,
            status="failed",
            loaded=inserted,
            rejected=outcome.rejected,
            error_code="LOAD_POSTCHECK_FAILED",
            error_message="a critical post-load check failed",
        )
        print(
            "rolled back — a critical post-load check failed, nothing was published",
            file=sys.stderr,
        )
        return 1

    record_finish(
        settings, run_id, status="success", loaded=inserted, rejected=outcome.rejected
    )
    for table in outcome.loads:
        load = outcome.loads[table]
        print(f"  {table:<28} {load.inserted:>4} row(s)  {load.rejected} rejected")
    print(f"loaded     {outcome.inserted} rows in one transaction, {outcome.rejected} rejected")
    print("decision   the engine arrives in batch 5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
