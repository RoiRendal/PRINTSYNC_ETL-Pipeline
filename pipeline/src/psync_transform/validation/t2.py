"""T2 — the staged data is still the data that was handed over (doc section 7).

The manifest says how many rows Stage 1 wrote per table. This check counts what is actually in
staging for that run and compares.

Why it matters: everything downstream reconciles against the handover's counts. If staging holds
fewer rows than the manifest claims — a truncated table, a manual ``delete``, a run that died
between writing rows and writing its record — then every reconciliation in section 7 balances
against a number that was never true, and the day is published short. T2 is the check that makes
the handover's counts trustworthy enough to reconcile against.

A table the manifest reports as empty must be empty here too: 0 = 0 passes, and 0 = 4 does not.
"""

from __future__ import annotations

import psycopg

from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.handover import Handover
from psync_transform.schema import STAGING_SCHEMA
from psync_transform.validation.result import CheckResult

__all__ = ["check_handover_counts"]


def check_handover_counts(settings: Settings, handover: Handover) -> CheckResult:
    """Every table holds exactly the rows its manifest says were extracted."""
    problems: list[str] = []
    total = 0

    try:
        with connect_target(settings) as conn:
            for spec in STAGING_SCHEMA:
                expected = handover.rows_extracted(spec.source)
                actual = conn.execute(
                    f"select count(*) from public.{spec.staging} where run_id = %s",
                    (handover.run_id,),
                ).fetchone()[0]
                total += actual

                if actual != expected:
                    problems.append(
                        f"{spec.staging}: {actual} rows staged, manifest says {expected}"
                    )
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T2",
            status="FAIL",
            severity="critical",
            message=f"could not count the staged rows: {exc}",
            error_code="TRF_STAGING_UNREADABLE",
        )

    if problems:
        return CheckResult(
            check_id="T2",
            status="FAIL",
            severity="critical",
            message=(
                "staging does not hold what the handover says was extracted: "
                + "; ".join(problems)
            ),
            error_code="TRF_STAGING_COUNT_MISMATCH",
        )

    return CheckResult(
        check_id="T2",
        status="PASS",
        severity="critical",
        message=(
            f"all {len(STAGING_SCHEMA)} staging tables hold the {total} rows the handover for "
            f"{handover.business_date} reports"
        ),
    )
