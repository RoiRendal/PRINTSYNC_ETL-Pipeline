"""T16 — every status is one the pipeline knows (doc section 7).

A status the code map does not know cannot be classified as revenue or not. Guessing "probably
completed" is how a refund becomes income; inventing a seventh order status is how a funnel grows a
step nobody asked for.

Two domains, and they are worth keeping apart:

* the **status dimension** is seeded with the six order statuses and never derived from the batch, so
  a seventh value at the source fails here instead of quietly becoming a dimension row (rule M-04);
* the **sale and payment statuses** are a two-value domain enforced at the source by `CHECK`
  constraints. This is the same run-time assertion Stage 1 keeps for V5 and V6: the constraint is on
  the other side of the boundary, and a migration could drop it without anyone being told.
"""

from __future__ import annotations

import psycopg

from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.validation.result import CheckResult

__all__ = ["check_status_domain"]

_SALE_DOMAIN = ("completed", "voided")
_PAYMENT_DOMAIN = ("captured", "voided")

_ORDER_STATUS_SQL = """
select distinct o.status
from public.stg_orders o
where o.run_id = %(run)s
  and o.status not in (select status_name from public.dim_order_status)
"""

_SALE_STATUS_SQL = """
select distinct status
from public.stg_sales_transactions
where run_id = %(run)s
  and status <> all(%(sale)s)
"""

_PAYMENT_STATUS_SQL = """
select distinct status
from public.stg_payments
where run_id = %(run)s
  and status <> all(%(payment)s)
"""


def check_status_domain(settings: Settings, batch: Batch) -> CheckResult:
    """Every status in the batch is one the code map and the dimension know."""
    problems: list[str] = []

    try:
        with connect_target(settings) as conn:
            unknown_orders = [
                row[0]
                for row in conn.execute(
                    _ORDER_STATUS_SQL, {"run": batch.parent_run_id}
                ).fetchall()
            ]
            if unknown_orders:
                problems.append(
                    f"orders: {unknown_orders} is not in the status dimension"
                )

            unknown_sales = [
                row[0]
                for row in conn.execute(
                    _SALE_STATUS_SQL,
                    {"run": batch.parent_run_id, "sale": list(_SALE_DOMAIN)},
                ).fetchall()
            ]
            if unknown_sales:
                problems.append(f"sales: {unknown_sales} is not a sale status")

            unknown_payments = [
                row[0]
                for row in conn.execute(
                    _PAYMENT_STATUS_SQL,
                    {"run": batch.parent_run_id, "payment": list(_PAYMENT_DOMAIN)},
                ).fetchall()
            ]
            if unknown_payments:
                problems.append(f"payments: {unknown_payments} is not a payment status")
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T16",
            status="FAIL",
            severity="critical",
            message=f"could not read the status domains: {exc}",
            error_code="TRF_STATUS_UNREADABLE",
        )

    if problems:
        return CheckResult(
            check_id="T16",
            status="FAIL",
            severity="critical",
            message="statuses outside their domains: " + "; ".join(problems[:6]),
            error_code="TRF_UNKNOWN_STATUS",
        )

    return CheckResult(
        check_id="T16",
        status="PASS",
        severity="critical",
        message="every order, sale and payment status is in its documented domain",
    )
