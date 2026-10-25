"""V8 — non-empty result (doc section 3).

A zero-row sale day usually means a broken window, not a genuinely empty day. This is the only
check whose severity is a **warning**: the shop may simply have been shut, and stopping the run
over that would be wrong.

It counts sales **inside the business day**, not inside the read range. The look-back pulls three
earlier days into every extract, so a quiet day would otherwise still show rows and this check
would never fire — which is the same as not having it.

The closed-day flag is supplied by the operator for a specific date and never inferred from the
data: a quiet night and a broken window look identical in the rows.
"""

from __future__ import annotations

import psycopg

from psync_extract.config import Settings
from psync_extract.db.target import connect_target
from psync_extract.validation.result import CheckResult
from psync_extract.window import ExtractionWindow

__all__ = ["check_non_empty"]


def check_non_empty(
    settings: Settings,
    run_id: str,
    window: ExtractionWindow,
    *,
    closed_day: bool = False,
) -> CheckResult:
    """At least one sale inside the business day, unless the day was flagged as closed."""
    try:
        with connect_target(settings) as conn:
            count = conn.execute(
                "select count(*) from public.stg_sales_transactions "
                "where run_id = %s and created_at >= %s and created_at < %s",
                (run_id, window.window_start, window.window_end),
            ).fetchone()[0]
    except psycopg.Error as exc:
        return CheckResult(
            check_id="V8",
            status="FAIL",
            severity="warning",
            message=f"could not count sales: {exc}",
            error_code="TGT_QUERY_FAILED",
        )

    if count:
        return CheckResult(
            check_id="V8",
            status="PASS",
            severity="warning",
            message=f"{count} sale(s) inside the business day",
        )

    if closed_day:
        return CheckResult(
            check_id="V8",
            status="PASS",
            severity="warning",
            message="no sales, and the date is flagged as a closed day",
        )

    return CheckResult(
        check_id="V8",
        status="WARN",
        severity="warning",
        message=(
            "no sales inside the business day — check the window before publishing, "
            "or flag the date as a closed day"
        ),
        error_code="ZERO_SALES",
    )
