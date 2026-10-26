"""T12 — the facts reconcile against each other (doc section 7).

The product fact is built from lines and the sales fact from headers. If the two ever disagree about
the same revenue, one of them is describing money the shop did not make — and no single-fact check
can see it, because each is internally consistent.

The equations this stage can evaluate so far, per business date:

```
Σ fct_daily_product_demand.revenue
  = Σ fct_daily_sales.net_revenue + Σ fct_daily_sales.unallocated_discount
Σ fct_daily_product_demand.quantity_sold = Σ fct_daily_sales.units_sold
```

The first is the one that carries the whole design. The product fact attributes revenue to products
by the name on the line; the sales fact takes it from the header. They reconcile only because
`Σ (quantity × unit_price)` equals `Σ subtotal` (check T5) and the discount difference is published
as `unallocated_discount` rather than invented on the lines.

The order and stock equations arrive with `fct_daily_order_status` and the stock snapshot; this
check grows with them rather than being rewritten.
"""

from __future__ import annotations

import psycopg

from psync_transform.batch import Batch
from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.validation.result import CheckResult

__all__ = ["check_fact_reconciliation"]

_MONEY_TOLERANCE = 0.005

_RECONCILIATION_SQL = r"""
with sales as (
    select business_date,
           sum(net_revenue)             as net_revenue,
           sum(unallocated_discount)    as unallocated_discount,
           sum(units_sold)              as units_sold
    from public.fct_daily_sales
    where business_date between %(start)s and %(end)s
    group by 1
),
demand as (
    select business_date,
           sum(revenue)        as revenue,
           sum(quantity_sold)  as quantity_sold
    from public.fct_daily_product_demand
    where business_date between %(start)s and %(end)s
    group by 1
)
select coalesce(s.business_date, d.business_date) as business_date,
       coalesce(s.net_revenue, 0) + coalesce(s.unallocated_discount, 0) as expected_revenue,
       coalesce(d.revenue, 0)                                    as actual_revenue,
       coalesce(s.units_sold, 0)                                 as expected_units,
       coalesce(d.quantity_sold, 0)                              as actual_units
from sales s
full outer join demand d on d.business_date = s.business_date
order by 1
"""


def check_fact_reconciliation(settings: Settings, batch: Batch) -> CheckResult:
    """The product fact and the sales fact describe the same money."""
    try:
        with connect_target(settings) as conn:
            rows = conn.execute(
                _RECONCILIATION_SQL,
                {"start": batch.window_start, "end": batch.window_end},
            ).fetchall()
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T12",
            status="FAIL",
            severity="critical",
            message=f"could not reconcile the facts: {exc}",
            error_code="TRF_FACTS_UNREADABLE",
        )

    problems = [
        f"{business_date}: revenue {actual:.2f} against {expected:.2f}"
        for business_date, expected, actual, _units, _actual_units in rows
        if abs(float(expected) - float(actual)) > _MONEY_TOLERANCE
    ]
    problems += [
        f"{business_date}: units {actual_units} against {units}"
        for business_date, _e, _a, units, actual_units in rows
        if units != actual_units
    ]

    if problems:
        return CheckResult(
            check_id="T12",
            status="FAIL",
            severity="critical",
            message="the facts disagree: " + "; ".join(problems[:6]),
            error_code="TRF_FACT_RECONCILIATION",
        )

    return CheckResult(
        check_id="T12",
        status="PASS",
        severity="critical",
        message=(
            f"{len(rows)} business date(s) reconcile between the sales fact and the product fact"
        ),
    )
