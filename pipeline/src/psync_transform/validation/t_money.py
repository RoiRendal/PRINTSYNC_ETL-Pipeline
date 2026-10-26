"""The money checks: T4, T10 and T11 (doc section 7).

Grouped because they look at the same table for the same reason — that the money `fct_daily_sales`
publishes can be believed. They differ in what they are allowed to do about a failure:

* **T4** (critical): the identities the table enforces with CHECK constraints still hold on the stored
  rows. A dropped constraint would let a broken aggregate through; this catches it.
* **T10** (warning): cost coverage. Recorded every batch, warned when it is thin — never a stop,
  because the catalogue is what it is and refusing to publish the day's revenue over it would punish
  the wrong party.
* **T11** (critical): the business rules. Most are CHECK constraints; this is the run-time assertion
  that they are still there, in the same spirit as Stage 1's V5 and V6.
"""

from __future__ import annotations

import psycopg

from psync_transform.batch import Batch
from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.validation.result import CheckResult

__all__ = [
    "check_internal_money_arithmetic",
    "check_cost_coverage",
    "check_business_rules",
]

_WINDOW = "business_date between %(start)s and %(end)s"

# T4 — the four identities of §6.1, on the stored rows.
_IDENTITIES_SQL = f"""
select count(*)
from public.fct_daily_sales
where {_WINDOW}
  and (gross_revenue <> net_revenue + tax_total
   or net_revenue <> line_revenue_total - line_discount_total - unallocated_discount
   or unallocated_discount <> discount_total - line_discount_total
   or settled_total <> cash_total + card_total + custom_order_total)
"""

# T10 — coverage over the window.
_COVERAGE_SQL = f"""
select min(cogs_coverage_pct), max(cogs_coverage_pct), count(*)
from public.fct_daily_sales
where {_WINDOW}
"""

# T11 — the business rules, per fact.
_SALES_RULES_SQL = f"""
select count(*)
from public.fct_daily_sales
where {_WINDOW}
  and (gross_revenue < 0
    or net_revenue < 0
    or line_revenue_total < 0
    or (margin_pct is not null and (margin_pct < -1000 or margin_pct > 100))
    or settled_total > gross_revenue * 1.01)
""".strip()

_DEMAND_RULES_SQL = f"""
select count(*)
from public.fct_daily_product_demand
where {_WINDOW}
  and (quantity_sold < 0 or revenue < 0 or cogs < 0
    or avg_daily_demand < 0 or forecast_demand_30d < 0)
""".strip()

_STOCK_RULES_SQL = f"""
select count(*)
from public.fct_daily_stock_snapshot
where business_date = %(target)s
  and (stock_on_hand < 0 or reorder_level < 0 or recommended_reorder < 0)
""".strip()


def _window_params(batch: Batch) -> dict[str, object]:
    return {"start": batch.window_start, "end": batch.window_end}


def check_internal_money_arithmetic(settings: Settings, batch: Batch) -> CheckResult:
    """The money identities hold on the stored rows, to the cent."""
    try:
        with connect_target(settings) as conn:
            broken = conn.execute(_IDENTITIES_SQL, _window_params(batch)).fetchone()[0]
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T4",
            status="FAIL",
            severity="critical",
            message=f"could not read the daily fact: {exc}",
            error_code="TRF_MONEY_UNREADABLE",
        )

    if broken:
        return CheckResult(
            check_id="T4",
            status="FAIL",
            severity="critical",
            message=f"{broken} row(s) break the money identities",
            error_code="TRF_MONEY_IDENTITY",
        )

    return CheckResult(
        check_id="T4",
        status="PASS",
        severity="critical",
        message="every published row satisfies the money identities",
    )


def check_cost_coverage(settings: Settings, batch: Batch) -> CheckResult:
    """Make the profit gap visible rather than silent (doc section 7, T10)."""
    try:
        with connect_target(settings) as conn:
            low, high, rows = conn.execute(_COVERAGE_SQL, _window_params(batch)).fetchone()
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T10",
            status="FAIL",
            severity="warning",
            message=f"could not read the cost coverage: {exc}",
            error_code="TRF_COVERAGE_UNREADABLE",
        )

    if rows == 0:
        return CheckResult(
            check_id="T10", status="PASS", severity="warning",
            message="no daily sales rows to cover",
        )

    lowest = float(low) if low is not None else 100.0
    if lowest < 50:
        return CheckResult(
            check_id="T10", status="WARN", severity="warning",
            message=(
                f"cost coverage is {lowest:.2f}% at its thinnest — read "
                "gross_profit_costed with cogs_coverage_pct, never the whole-day figures"
            ),
        )
    if lowest < 95:
        return CheckResult(
            check_id="T10", status="WARN", severity="warning",
            message=f"cost coverage is {lowest:.2f}% at its thinnest (best {float(high):.2f}%)",
        )

    return CheckResult(
        check_id="T10",
        status="PASS",
        severity="warning",
        message=f"cost coverage is at least {lowest:.2f}% on every published day",
    )


def check_business_rules(settings: Settings, batch: Batch) -> CheckResult:
    """The values the schema refuses are refused, and the ones it cannot express hold."""
    try:
        with connect_target(settings) as conn:
            sales = conn.execute(_SALES_RULES_SQL, _window_params(batch)).fetchone()[0]
            demand = conn.execute(_DEMAND_RULES_SQL, _window_params(batch)).fetchone()[0]
            stock = conn.execute(
                _STOCK_RULES_SQL, {"target": batch.window_end}
            ).fetchone()[0]
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T11",
            status="FAIL",
            severity="critical",
            message=f"could not read the business rules: {exc}",
            error_code="TRF_BUSINESS_RULES_UNREADABLE",
        )

    broken = sales + demand + stock
    if broken:
        return CheckResult(
            check_id="T11",
            status="FAIL",
            severity="critical",
            message=f"{broken} row(s) break a business rule",
            error_code="TRF_BUSINESS_RULE",
        )

    return CheckResult(
        check_id="T11",
        status="PASS",
        severity="critical",
        message="every published value obeys the business rules",
    )
