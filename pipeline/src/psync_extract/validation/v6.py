"""V6 — primary key uniqueness (doc section 3).

A duplicated row would double-count revenue, and nothing downstream would look wrong: the totals
would simply be too high, in a way that resembles a good night.

``source_id`` is part of each staging primary key, so on a healthy database a duplicate cannot
exist. Like V5, this is a run-time assertion that the constraint is still there — a table rebuilt
without its key would accept duplicates silently, and an over-count never announces itself.
"""

from __future__ import annotations

import psycopg

from psync_extract.config import Settings
from psync_extract.db.target import connect_target
from psync_extract.staging import STAGING_TABLES
from psync_extract.validation.result import CheckResult

__all__ = ["check_primary_key_uniqueness"]


def check_primary_key_uniqueness(settings: Settings, run_id: str) -> CheckResult:
    """Every source row must appear exactly once per run."""
    problems: list[str] = []

    try:
        with connect_target(settings) as conn:
            for staging in STAGING_TABLES.values():
                rows, distinct = conn.execute(
                    f"select count(*), count(distinct source_id) "
                    f"from public.{staging} where run_id = %s",
                    (run_id,),
                ).fetchone()

                if rows != distinct:
                    problems.append(
                        f"{staging}: {rows} rows but {distinct} distinct source_id"
                    )
    except psycopg.Error as exc:
        return CheckResult(
            check_id="V6",
            status="FAIL",
            severity="critical",
            message=f"could not check uniqueness: {exc}",
            error_code="TGT_QUERY_FAILED",
        )

    if problems:
        return CheckResult(
            check_id="V6",
            status="FAIL",
            severity="critical",
            message="duplicate source_id found — " + "; ".join(problems),
            error_code="DUPLICATE_KEY",
        )

    return CheckResult(
        check_id="V6",
        status="PASS",
        severity="critical",
        message=f"{len(STAGING_TABLES)} staging tables hold each source row once",
    )
