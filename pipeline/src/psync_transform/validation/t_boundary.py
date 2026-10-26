"""The boundary checks: T6, T13 and T14 (doc section 7).

Grouped because they ask the same question from three directions — is this batch writing the dates it
claims to be writing, and is what it wrote worth reading.

They differ in severity, and the difference is doing real work:

* **T6** (warning): VAT conformance is the shop's data problem, not the pipeline's. The recorded tax
  is never recomputed — that would invent a number the customer never paid and break the
  reconciliation to payments. The check counts and warns.
* **T13** (critical): a row landed outside the batch window, which means the window arithmetic or the
  grouping is wrong. Stop.
* **T14** (warning): a silent zero is usually a broken rule, not a quiet day.
"""

from __future__ import annotations

import psycopg

from psync_transform.batch import Batch
from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.validation.result import CheckResult

__all__ = ["check_vat_conformance", "check_business_date_boundary", "check_non_empty_output"]

# T6 — the recorded tax against the configured rate, per live sale. Never recomputed (rule P6).
_VAT_SQL = r"""
with live as (
    select s.source_id,
           (s.created_at at time zone %(tz)s)::date as business_date,
           s.tax,
           round((s.subtotal - s.discount) * b.vat_rate / 100, 2) as expected_tax
    from public.stg_sales_transactions s
    join public.dim_branch b
      on b.branch_id = s.branch_id
     and b.valid_from <= (s.created_at at time zone %(tz)s)::date
     and (b.valid_to is null or (s.created_at at time zone %(tz)s)::date < b.valid_to)
    where s.run_id = %(run)s
      and s.status = 'completed'
      and not exists (
          select 1 from public.quarantine_rows q
          where q.batch_id = %(batch)s
            and q.source_table = 'sales_transactions'
            and q.source_id = s.source_id::text
      )
)
select count(*) filter (where tax <> expected_tax) as exceptions,
       count(*)                                    as live
from live
"""

# T13 — the facts only write inside the window, and every input date reaches an output.
_OUTSIDE_SQL: dict[str, str] = {
    "fct_daily_sales": "select count(*) from public.fct_daily_sales where business_date not between %(start)s and %(end)s",
    "fct_daily_product_demand": "select count(*) from public.fct_daily_product_demand where business_date not between %(start)s and %(end)s",
    "fct_daily_order_status": "select count(*) from public.fct_daily_order_status where business_date not between %(start)s and %(end)s",
}

# An input date that produced no output row is a date the batch dropped (rule T13, second half).
_DROPPED_DATE_SQL = r"""
with input_dates as (
    select distinct (s.created_at at time zone %(tz)s)::date as business_date
    from public.stg_sales_transactions s
    where s.run_id = %(run)s
      and not exists (
          select 1 from public.quarantine_rows q
          where q.batch_id = %(batch)s
            and q.source_table = 'sales_transactions'
            and q.source_id = s.source_id::text
      )
)
select i.business_date
from input_dates i
where not exists (
    select 1 from public.fct_daily_sales f where f.business_date = i.business_date
)
order by 1
"""

# T14 — the target date must have rows, or the day is being reported as absent rather than empty.
_NON_EMPTY_SQL = """
select (select count(*) from public.fct_daily_sales where business_date = %(target)s),
       (select count(*) from public.fct_daily_stock_snapshot where business_date = %(target)s)
"""


def _params(batch: Batch, time_zone: str) -> dict[str, object]:
    return {
        "run": batch.parent_run_id,
        "batch": batch.batch_id,
        "tz": time_zone,
        "start": batch.window_start,
        "end": batch.window_end,
        "target": batch.window_end,
    }


def check_vat_conformance(settings: Settings, batch: Batch, time_zone: str) -> CheckResult:
    """Count the sales whose tax does not match the configured rate, and warn."""
    try:
        with connect_target(settings) as conn:
            exceptions, live = conn.execute(
                _VAT_SQL, _params(batch, time_zone)
            ).fetchone()
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T6",
            status="FAIL",
            severity="warning",
            message=f"could not check the VAT: {exc}",
            error_code="TRF_VAT_UNREADABLE",
        )

    if live and exceptions * 100 > live:
        return CheckResult(
            check_id="T6",
            status="FAIL",
            severity="warning",
            message=(
                f"{exceptions} of {live} live sales carry tax that does not match the rate — "
                "above the 1% threshold, so the day needs a look"
            ),
            error_code="TRF_VAT_MISMATCH",
        )
    if exceptions:
        return CheckResult(
            check_id="T6",
            status="WARN",
            severity="warning",
            message=(
                f"{exceptions} sale(s) carry tax that does not match the rate; the recorded tax is "
                "never recomputed"
            ),
        )

    return CheckResult(
        check_id="T6",
        status="PASS",
        severity="warning",
        message="every live sale's tax matches the configured rate",
    )


def check_business_date_boundary(settings: Settings, batch: Batch, time_zone: str) -> CheckResult:
    """No row landed outside the batch, and no input date was dropped."""
    problems: list[str] = []
    try:
        with connect_target(settings) as conn:
            for table, sql in _OUTSIDE_SQL.items():
                outside = conn.execute(sql, _params(batch, time_zone)).fetchone()[0]
                if outside:
                    problems.append(f"{table}: {outside} row(s) outside the window")

            dropped = [
                row[0]
                for row in conn.execute(
                    _DROPPED_DATE_SQL, _params(batch, time_zone)
                ).fetchall()
            ]
            if dropped:
                problems.append(f"{dropped} has input rows but no output")
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T13",
            status="FAIL",
            severity="critical",
            message=f"could not check the business dates: {exc}",
            error_code="TRF_BOUNDARY_UNREADABLE",
        )

    if problems:
        return CheckResult(
            check_id="T13",
            status="FAIL",
            severity="critical",
            message="business dates are wrong: " + "; ".join(problems[:6]),
            error_code="TRF_BUSINESS_DATE_BOUNDARY",
        )

    return CheckResult(
        check_id="T13",
        status="PASS",
        severity="critical",
        message="every output date is inside the window and every input date produced output",
    )


def check_non_empty_output(settings: Settings, batch: Batch) -> CheckResult:
    """A silent zero is usually a broken rule, not a quiet day (doc section 7, T14)."""
    try:
        with connect_target(settings) as conn:
            sales_rows, stock_rows = conn.execute(
                _NON_EMPTY_SQL, {"target": batch.window_end}
            ).fetchone()
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T14",
            status="FAIL",
            severity="warning",
            message=f"could not check the output: {exc}",
            error_code="TRF_OUTPUT_UNREADABLE",
        )

    if sales_rows == 0 and stock_rows == 0:
        return CheckResult(
            check_id="T14",
            status="WARN",
            severity="warning",
            message=(
                f"no rows for {batch.window_end} — either the day was closed or every rule matched "
                "nothing"
            ),
        )

    return CheckResult(
        check_id="T14",
        status="PASS",
        severity="warning",
        message=f"the target date has {sales_rows} sales row(s) and {stock_rows} stock row(s)",
    )
