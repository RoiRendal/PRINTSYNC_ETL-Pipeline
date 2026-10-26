"""T5 — the line-to-header identity (doc section 7).

```
Σ (quantity × unit_price) over live lines  =  Σ subtotal over live sales
```

The header is authoritative for revenue (rule B-01) and the payments prove it — captured payments
equal the sale total on all 851 completed sales in the profiled export. The *lines* are the
approximation: they are what a product-level fact is built from, and if the two ever disagree, the
daily fact and the product fact are describing different money.

The profile measured this identity holding on **867 of 867 sales** (doc §2.3), which is what makes it
worth checking: a rule that always passes is only useful when it starts failing.

This is the check the schema cannot express. `fct_daily_sales` enforces its own internal arithmetic
with CHECK constraints, but nothing in the database knows that a day's line revenue should equal its
header subtotal — that crosses two tables and a rule.
"""

from __future__ import annotations

import psycopg

from psync_transform.batch import Batch
from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.validation.result import CheckResult

__all__ = ["check_line_to_header_identity"]

# One row per business date, with the header's subtotal and the lines' gross side by side. Both
# sides exclude quarantined sales; the line side also excludes quarantined lines.
_IDENTITY_SQL = r"""
with live_sale as (
    select s.source_id,
           (s.created_at at time zone %(tz)s)::date as business_date,
           s.subtotal
    from public.stg_sales_transactions s
    where s.run_id = %(run)s
      and s.status = 'completed'
      and not exists (
          select 1 from public.quarantine_rows q
          where q.batch_id = %(batch)s
            and q.source_table = 'sales_transactions'
            and q.source_id = s.source_id::text
      )
),
header as (
    select business_date, sum(subtotal) as header_subtotal
    from live_sale
    group by 1
),
line as (
    select ls.business_date, sum(i.quantity * i.unit_price) as line_gross
    from public.stg_sales_transaction_items i
    join live_sale ls on ls.source_id = i.transaction_id
    where i.run_id = %(run)s
      and not exists (
          select 1 from public.quarantine_rows q
          where q.batch_id = %(batch)s
            and q.source_table = 'sales_transaction_items'
            and q.source_id = i.source_id::text
      )
    group by 1
)
select h.business_date,
       h.header_subtotal,
       coalesce(l.line_gross, 0) as line_gross
from header h
left join line l on l.business_date = h.business_date
order by 1
"""

# A cent of slack: the columns are numeric(14,2), so a difference below half a cent cannot be
# rounding — anything larger is a real disagreement.
TOLERANCE = 0.005


def check_line_to_header_identity(settings: Settings, batch: Batch) -> CheckResult:
    """Every live day's line revenue equals its header subtotal."""
    try:
        with connect_target(settings) as conn:
            rows = conn.execute(
                _IDENTITY_SQL,
                {
                    "run": batch.parent_run_id,
                    "batch": batch.batch_id,
                    "tz": settings.run_timezone,
                },
            ).fetchall()
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T5",
            status="FAIL",
            severity="critical",
            message=f"could not compare the lines with their headers: {exc}",
            error_code="TRF_IDENTITY_UNREADABLE",
        )

    problems = [
        f"{business_date}: header {header:.2f} but lines {lines:.2f}"
        for business_date, header, lines in rows
        if abs(float(header) - float(lines)) > TOLERANCE
    ]

    if problems:
        return CheckResult(
            check_id="T5",
            status="FAIL",
            severity="critical",
            message="lines and headers disagree: " + "; ".join(problems[:6]),
            error_code="TRF_LINE_HEADER_IDENTITY",
        )

    return CheckResult(
        check_id="T5",
        status="PASS",
        severity="critical",
        message=(
            f"{len(rows)} live business date(s) reconcile: every day's line revenue equals its "
            "header subtotal"
        ),
    )
