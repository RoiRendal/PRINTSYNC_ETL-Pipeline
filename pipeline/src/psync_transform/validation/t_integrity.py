"""The integrity checks: T7, T8 and T9 (doc section 7).

Grouped because they are all assertions about the **structure** of the published output — that rows
are unique, that every dimension key resolves, and that the columns the contract declares required
hold values. The schema enforces most of this with primary keys, foreign keys and NOT NULL columns;
the checks are run-time assertions that those constraints are still there, in the same spirit as
Stage 1's V5 and V6. A table rebuilt without its keys would accept duplicates silently, and an
over-count never announces itself.
"""

from __future__ import annotations

import psycopg

from psync_transform.batch import Batch
from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.validation.result import CheckResult

__all__ = [
    "check_key_uniqueness",
    "check_referential_integrity",
    "check_required_columns",
]

_WINDOW = "business_date between %(start)s and %(end)s"

# (fact table, its own grain columns, the dimension columns it must resolve)
_FACTS: tuple[tuple[str, str, str], ...] = (
    ("fct_daily_sales", "branch_key", "branch_key"),
    ("fct_daily_product_demand", "item_key", "item_key"),
    ("fct_daily_stock_snapshot", "item_key", "item_key"),
    ("fct_daily_order_status", "status_key", "status_key"),
)

# T7 — one table per grain check.
_UNIQUE_SQL: dict[str, str] = {
    "fct_daily_sales": f"select count(*) - count(distinct (business_date, branch_key)) from public.fct_daily_sales where {_WINDOW}",
    "fct_daily_product_demand": f"select count(*) - count(distinct (business_date, branch_key, item_key)) from public.fct_daily_product_demand where {_WINDOW}",
    "fct_daily_stock_snapshot": f"select count(*) - count(distinct (business_date, branch_key, item_key)) from public.fct_daily_stock_snapshot where business_date = %(target)s",
    "fct_daily_order_status": f"select count(*) - count(distinct (business_date, branch_key, status_key)) from public.fct_daily_order_status where {_WINDOW}",
    "dim_branch": "select count(*) - count(distinct (branch_id, valid_from)) from public.dim_branch",
    "dim_item": "select count(*) - count(distinct (item_ref, valid_from)) from public.dim_item",
}

# T8 — every fact row's dimension keys resolve.
_REFERENTIAL_SQL = {
    "fct_daily_sales": f"""
        select count(*)
        from public.fct_daily_sales f
        left join public.dim_branch b on b.branch_key = f.branch_key
        left join public.dim_date d on d.date_key = f.business_date
        where {_WINDOW}
          and (b.branch_key is null or d.date_key is null)
    """,
    "fct_daily_product_demand": f"""
        select count(*)
        from public.fct_daily_product_demand f
        left join public.dim_item i on i.item_key = f.item_key
        left join public.dim_branch b on b.branch_key = f.branch_key
        left join public.dim_date d on d.date_key = f.business_date
        where {_WINDOW}
          and (i.item_key is null or b.branch_key is null or d.date_key is null)
    """,
    "fct_daily_stock_snapshot": f"""
        select count(*)
        from public.fct_daily_stock_snapshot f
        left join public.dim_item i on i.item_key = f.item_key
        left join public.dim_date d on d.date_key = f.business_date
        where f.business_date = %(target)s
          and (i.item_key is null or d.date_key is null)
    """,
    "fct_daily_order_status": f"""
        select count(*)
        from public.fct_daily_order_status f
        left join public.dim_order_status st on st.status_key = f.status_key
        left join public.dim_branch b on b.branch_key = f.branch_key
        left join public.dim_date d on d.date_key = f.business_date
        where {_WINDOW}
          and (st.status_key is null or b.branch_key is null or d.date_key is null)
    """,
}

# T9 — the columns the contract declares NOT NULL, on the tables a batch writes.
_REQUIRED_COLUMNS: dict[str, str] = {
    "fct_daily_sales": "business_date, branch_key, gross_revenue, net_revenue, tax_total, line_revenue_total, discount_total, settled_total",
    "fct_daily_product_demand": "business_date, branch_key, item_key, quantity_sold, line_revenue, revenue, cogs, is_costed",
    "fct_daily_stock_snapshot": "business_date, branch_key, item_key, stock_on_hand, stock_status, recommended_reorder",
    "fct_daily_order_status": "business_date, branch_key, status_key, order_count, order_value",
    "dim_branch": "branch_key, branch_id, code, vat_rate, time_zone, valid_from, is_current",
    "dim_item": "item_key, item_ref, item_name, category, valid_from, is_current",
    "dim_date": "date_key, year, month, day_of_month",
}


def _window_params(batch: Batch) -> dict[str, object]:
    return {"start": batch.window_start, "end": batch.window_end, "target": batch.window_end}


def check_key_uniqueness(settings: Settings, batch: Batch) -> CheckResult:
    """No published row shares its grain with another."""
    problems: list[str] = []
    try:
        with connect_target(settings) as conn:
            for table, sql in _UNIQUE_SQL.items():
                duplicates = conn.execute(sql, _window_params(batch)).fetchone()[0]
                if duplicates:
                    problems.append(f"{table}: {duplicates} duplicate row(s)")
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T7",
            status="FAIL",
            severity="critical",
            message=f"could not check the keys: {exc}",
            error_code="TRF_KEYS_UNREADABLE",
        )

    if problems:
        return CheckResult(
            check_id="T7",
            status="FAIL",
            severity="critical",
            message="duplicated keys: " + "; ".join(problems),
            error_code="TRF_DUPLICATE_KEY",
        )

    return CheckResult(
        check_id="T7",
        status="PASS",
        severity="critical",
        message=f"no duplicates across {len(_UNIQUE_SQL)} output tables",
    )


def check_referential_integrity(settings: Settings, batch: Batch) -> CheckResult:
    """Every dimension key resolves, and no join multiplies the rows it starts from."""
    problems: list[str] = []
    try:
        with connect_target(settings) as conn:
            for table, sql in _REFERENTIAL_SQL.items():
                orphans = conn.execute(sql, _window_params(batch)).fetchone()[0]
                if orphans:
                    problems.append(f"{table}: {orphans} row(s) with an unresolved key")
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T8",
            status="FAIL",
            severity="critical",
            message=f"could not check the referential integrity: {exc}",
            error_code="TRF_INTEGRITY_UNREADABLE",
        )

    if problems:
        return CheckResult(
            check_id="T8",
            status="FAIL",
            severity="critical",
            message="unresolved dimension keys: " + "; ".join(problems),
            error_code="TRF_UNRESOLVED_KEY",
        )

    return CheckResult(
        check_id="T8",
        status="PASS",
        severity="critical",
        message="every fact row resolves its dimension keys",
    )


def check_required_columns(settings: Settings, batch: Batch) -> CheckResult:
    """The columns the contract declares required hold values."""
    problems: list[str] = []
    try:
        with connect_target(settings) as conn:
            for table, columns in _REQUIRED_COLUMNS.items():
                predicate = " or ".join(f"{column} is null" for column in columns.split(", "))
                # The window applies to the facts. The dimensions are not windowed — every row they
                # hold is this stage's output, and dim_branch / dim_item are versioned by
                # valid_from rather than dated.
                if table in ("fct_daily_sales", "fct_daily_product_demand"):
                    where = _WINDOW
                elif table == "fct_daily_stock_snapshot":
                    where = "business_date = %(target)s"
                else:
                    where = "true"
                nulls = conn.execute(
                    f"select count(*) from public.{table} where {where} and ({predicate})",
                    _window_params(batch),
                ).fetchone()[0]
                if nulls:
                    problems.append(f"{table}: {nulls} row(s) with a required column empty")
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T9",
            status="FAIL",
            severity="critical",
            message=f"could not check the required columns: {exc}",
            error_code="TRF_COLUMNS_UNREADABLE",
        )

    if problems:
        return CheckResult(
            check_id="T9",
            status="FAIL",
            severity="critical",
            message="required columns are empty: " + "; ".join(problems),
            error_code="TRF_REQUIRED_COLUMN_EMPTY",
        )

    return CheckResult(
        check_id="T9",
        status="PASS",
        severity="critical",
        message=f"no required column is empty across {len(_REQUIRED_COLUMNS)} output tables",
    )
