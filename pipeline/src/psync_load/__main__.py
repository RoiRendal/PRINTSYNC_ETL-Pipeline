"""Run one load batch from the command line (doc section 1.3).

    python -m psync_load --batch TRF_20261024_d031cb6c

Resolves the handover, runs the L1–L6 pre-load gate, loads the batch in one transaction, runs
L7–L13 before committing, and records a verdict. A crash is retried with backoff; a verdict is not —
re-running a rejected batch would reject it again for the same reason.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid

from psync_load.config import ConfigurationError, code_version, load_settings
from psync_load.handover import HandoverError, load_handover
from psync_load.loader import LoadOutcome, load_batch
from psync_load.runlog import RunTrace, log_stem
from psync_load.runs import record_checks, record_finish, record_start, record_tables
from psync_load.validation import run_post_load_checks, run_pre_load_checks

__all__ = ["main"]


def _print_checks(label: str, checks: dict) -> None:
    print(f"{label:<10} " + "  ".join(f"{k}={v.status}" for k, v in sorted(checks.items())))
    for check_id, result in sorted(checks.items()):
        if result.status != "PASS":
            print(f"  {check_id}: {result.message}", file=sys.stderr)


def _record(trace: RunTrace, label: str, checks: dict) -> None:
    for check_id, result in sorted(checks.items()):
        if result.status == "PASS":
            trace.info(label, f"{check_id} PASS {result.message}")
        elif result.status == "WARN":
            trace.warn(label, f"{check_id} WARN {result.message}")
        else:
            trace.error(label, f"{check_id} FAIL {result.message}")


def _payload(settings, handover, run_id, outcome: LoadOutcome, trace: RunTrace) -> dict:
    return {
        "stage": "load",
        "run_id": run_id,
        "transformation_run_id": handover.run_id,
        "batch_id": handover.batch_id,
        "business_date": handover.business_date,
        "window": {"start": handover.window_start, "end": handover.window_end},
        "decision": outcome.decision.verdict if outcome.decision else None,
        "status": "success" if outcome.committed else "rolled_back",
        "steps": trace.steps,
        "tables": {
            table: {
                "records_received": load.received,
                "records_inserted": load.inserted,
                "records_updated": 0,
                "records_rejected": load.rejected,
            }
            for table, load in outcome.loads.items()
        },
        "validation_results": {
            check_id: result.status for check_id, result in outcome.checks.items()
        },
        "error": None,
        "code_version": code_version(),
    }


def main(argv: list[str] | None = None) -> int:
    """Resolve one approved batch, gate it, load it, verify it, and decide."""
    parser = argparse.ArgumentParser(
        prog="psync_load",
        description="Load one approved transformation batch into psync_warehouse.",
    )
    parser.add_argument("--batch", required=True, help="the transformation batch_id to load")
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
    print(f"handover   {handover.decision} / {handover.status}")
    print(f"version    {code_version()}")

    pre = run_pre_load_checks(settings, handover)
    _print_checks("pre-load", pre)
    if any(result.is_critical_failure for result in pre.values()):
        print("pre-load gate failed. Nothing was written.", file=sys.stderr)
        return 1

    attempt = 0
    while True:
        attempt += 1
        run_id = uuid.uuid4()
        trace = RunTrace.open(settings.log_directory, log_stem(handover.batch_id, run_id))
        trace.begin("preload")
        trace.done("preload", f"L1-L6 {sum(1 for r in pre.values() if r.status == 'PASS')} PASS")
        record_start(settings, handover, run_id)

        try:
            trace.begin("copy")
            outcome = load_batch(settings, handover, run_id, validate=run_post_load_checks)
            trace.done("copy", f"{outcome.inserted} rows in {len(outcome.loads)} tables")
        except Exception as exc:  # noqa: BLE001 - a failed load must be recorded
            trace.error("copy", f"attempt {attempt} failed: {exc}")
            record_finish(
                settings,
                run_id,
                status="failed",
                error_code="LOAD_FAILED",
                error_message=str(exc)[:500],
            )
            trace.close()
            if attempt > settings.max_retries:
                print(f"load failed: {exc}", file=sys.stderr)
                print("rolled back — no rows from this batch were published", file=sys.stderr)
                return 1
            print(
                f"attempt {attempt} failed; retrying in {settings.retry_backoff_seconds}s",
                file=sys.stderr,
            )
            time.sleep(settings.retry_backoff_seconds)
            continue

        _print_checks("post-load", outcome.checks)
        trace.begin("validate")
        _record(trace, "validate", outcome.checks)
        trace.done(
            "validate",
            f"L7-L13 {sum(1 for r in outcome.checks.values() if r.status == 'PASS')} PASS",
        )

        decision = outcome.decision
        trace.begin("decision")
        trace.done("decision", f"{decision.verdict}: {decision.reason}")

        inserted = {table: load.inserted for table, load in outcome.loads.items()}
        record_tables(settings, run_id, handover, outcome.loads)
        record_checks(settings, handover.batch_id, outcome.checks)
        record_finish(
            settings,
            run_id,
            status="success" if outcome.committed else "failed",
            loaded=inserted,
            rejected=outcome.rejected,
            decision=decision.verdict,
            error_code=None if outcome.committed else "LOAD_NOT_PUBLISHED",
            error_message=None if outcome.committed else decision.reason,
        )

        trace.begin("record")
        trace.write_record(_payload(settings, handover, run_id, outcome, trace))
        trace.done("record", "ledger and log written")
        trace.close()

        print(f"decision   {decision.verdict}")
        print(f"reason     {decision.reason}")
        if not outcome.committed:
            print("rolled back — nothing from this batch was published", file=sys.stderr)
            return 1

        for table, load in outcome.loads.items():
            print(f"  {table:<28} {load.inserted:>4} row(s)  {load.rejected} rejected")
        print(f"loaded     {outcome.inserted} rows in one transaction")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
