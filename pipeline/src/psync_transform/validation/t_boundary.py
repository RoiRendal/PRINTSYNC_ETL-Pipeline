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

from typing import Mapping

import psycopg

from psync_transform.batch import Batch
from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.validation.result import CheckResult

__all__ = ["check_vat_conformance", "check_business_date_boundary", "check_non_empty_output"]

# T6 — the recorded tax against the rate in force, per live sale. Never recomputed (rule P6).
#
# A sale recorded with **no tax** is zero-rated, not a mismatch: the rate is a setting the shop may
# put at 0 (S-20). The source records the tax but not the rate it was charged at, so a sale made
# under a different rate cannot be told apart from a mistake — which is why this check warns rather
# than fails, and why zero is accepted instead of guessed at.
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
select count(*) filter (where tax <> 0 and tax <> expected_tax) as exceptions,
       count(*) filter (where tax = 0 and expected_tax <> 0)     as zero_rated,
       count(*)                                                  as live
from live
"""

# T13 — the batch's own rows, and only those. The fact tables carry no batch column: their grain is
# (business_date, branch_key), because a published day is the day, not the run that built it. So
# "rows outside the window" cannot be attributed to this batch — another night's rows sit there by
# design — and counting them failed every batch that ran after a gap longer than the look-back.
#
# What can be checked is the batch's own account of itself: the rows it reports writing must be the
# rows present in its window. A row written to the wrong date makes those two disagree.
_WINDOW_COUNT_SQL: dict[str, str] = {
    "fct_daily_sales": "select count(*) from public.fct_daily_sales where business_date between %(start)s and %(end)s",
    "fct_daily_product_demand": "select count(*) from public.fct_daily_product_demand where business_date between %(start)s and %(end)s",
    "fct_daily_order_status": "select count(*) from public.fct_daily_order_status where business_date between %(start)s and %(end)s",
}

_INPUT_DATES = r"""
    select distinct (s.created_at at time zone %(tz)s)::date as business_date
    from public.stg_sales_transactions s
    where s.run_id = %(run)s
      and not exists (
          select 1 from public.quarantine_rows q
          where q.batch_id = %(batch)s
            and q.source_table = 'sales_transactions'
            and q.source_id = s.source_id::text
      )
"""

# An input date that produced no output row is a date the batch dropped.
_DROPPED_DATE_SQL = (
    "with input_dates as ("
    + _INPUT_DATES
    + ") select i.business_date from input_dates i "
    "where not exists (select 1 from public.fct_daily_sales f where f.business_date = i.business_date) "
    "order by 1"
)

# An output date with no input behind it is a date the batch invented.
_UNEXPECTED_DATE_SQL = (
    "with input_dates as ("
    + _INPUT_DATES
    + "), output_dates as ("
    "select distinct f.business_date from public.fct_daily_sales f "
    "where f.business_date between %(start)s and %(end)s) "
    "select o.business_date from output_dates o "
    "where not exists (select 1 from input_dates i where i.business_date = o.business_date) "
    "order by 1"
)

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
    """Count the sales whose tax matches neither the rate in force nor zero, and warn.

    A zero-rated sale is conformant (S-20): the rate is a setting, and 0 is a legal one.
    """
    try:
        with connect_target(settings) as conn:
            exceptions, zero_rated, live = conn.execute(
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

    zero_note = (
        f" ({zero_rated} sale(s) zero-rated and accepted as such)" if zero_rated else ""
    )

    if live and exceptions * 100 > live:
        return CheckResult(
            check_id="T6",
            status="FAIL",
            severity="warning",
            message=(
                f"{exceptions} of {live} live sales carry tax that is neither zero nor the rate in "
                f"force — above the 1% threshold, so the day needs a look{zero_note}"
            ),
            error_code="TRF_VAT_MISMATCH",
        )
    if exceptions:
        return CheckResult(
            check_id="T6",
            status="WARN",
            severity="warning",
            message=(
                f"{exceptions} sale(s) carry tax that is neither zero nor the rate in force; the "
                "recorded tax is never recomputed, so this is counted and left alone"
                f"{zero_note}"
            ),
            error_code="TRF_VAT_MISMATCH",
        )

    return CheckResult(
        check_id="T6",
        status="PASS",
        severity="warning",
        message=(
            f"every live sale's tax is either zero or the rate in force{zero_note}"
        ),
    )


def check_business_date_boundary(
    settings: Settings,
    batch: Batch,
    time_zone: str,
    *,
    written: Mapping[str, int],
) -> CheckResult:
    """The batch wrote the dates it claims, and only those.

    ``written`` is what the fact builders reported, table by table. Comparing it with what is in the
    window is the only account of "this batch's rows" the schema allows, because the facts carry no
    batch column. The two date-set comparisons catch the other direction: a date read but not
    published, and a date published but never read.
    """
    problems: list[str] = []
    params = _params(batch, time_zone)
    try:
        with connect_target(settings) as conn:
            for table, rows_written in written.items():
                present = conn.execute(_WINDOW_COUNT_SQL[table], params).fetchone()[0]
                if present != rows_written:
                    problems.append(
                        f"{table}: {rows_written} row(s) written but {present} in the window"
                    )

            dropped = [
                row[0] for row in conn.execute(_DROPPED_DATE_SQL, params).fetchall()
            ]
            if dropped:
                problems.append(f"{dropped} has input rows but no output")

            unexpected = [
                row[0] for row in conn.execute(_UNEXPECTED_DATE_SQL, params).fetchall()
            ]
            if unexpected:
                problems.append(f"{unexpected} has output rows but no input")
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
        message=(
            "the batch wrote what it reported, and its output dates are exactly its input dates"
        ),
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
