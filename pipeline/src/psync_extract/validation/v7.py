"""V7 — count parity: what was read is what was written (doc section 3).

For every table, the rows read from PRINTSYNC must equal the rows that landed in staging, plus any
the run deliberately rejected (``rows_read = rows_extracted + rows_rejected``). A shortfall means a
row was lost between reading and writing — the failure that produces plausible numbers rather than
an error, which is why it is a critical check and not a warning.

The comparison spans two databases: the read counts come from the run, the written counts from
``psync_analytics``. There is no SQL that joins across them, so the arithmetic happens here.
"""

from __future__ import annotations

from typing import Mapping

import psycopg

from psync_extract.config import Settings
from psync_extract.db.target import connect_target
from psync_extract.staging import STAGING_TABLES
from psync_extract.validation.result import CheckResult

__all__ = ["check_row_parity"]


def check_row_parity(
    settings: Settings,
    run_id: str,
    *,
    read: Mapping[str, int],
    rejected: Mapping[str, int] | None = None,
) -> CheckResult:
    """Compare each table's read count with what actually reached staging.

    ``read`` is what each extractor reported reading; ``rejected`` is what the run discarded on
    purpose (empty until the structural checks start rejecting rows). A table absent from either
    mapping counts as zero, so a table that was not extracted must also be empty in staging.
    """
    rejected = rejected or {}
    problems: list[str] = []
    total_read = 0
    total_written = 0

    try:
        with connect_target(settings) as conn:
            for table, staging in STAGING_TABLES.items():
                written = conn.execute(
                    f"select count(*) from public.{staging} where run_id = %s",
                    (run_id,),
                ).fetchone()[0]
                rows_read = read.get(table, 0)
                expected = rows_read - rejected.get(table, 0)
                total_read += rows_read
                total_written += written

                if written != expected:
                    problems.append(f"{table}: read {rows_read}, wrote {written}")
    except psycopg.Error as exc:
        return CheckResult(
            check_id="V7",
            status="FAIL",
            severity="critical",
            message=f"could not count staging rows: {exc}",
            error_code="TGT_QUERY_FAILED",
        )

    if problems:
        return CheckResult(
            check_id="V7",
            status="FAIL",
            severity="critical",
            message="row-count parity failed — " + "; ".join(problems),
            error_code="ROW_COUNT_MISMATCH",
        )

    return CheckResult(
        check_id="V7",
        status="PASS",
        severity="critical",
        message=(
            f"{len(STAGING_TABLES)} tables match: {total_read} rows read, "
            f"{total_written} written"
        ),
    )
