"""Building the facts (doc sections 5.2, 5.4 and 5.6).

``fct_daily_sales`` first: one row per business date per branch, and the only fact whose numbers a
reader will check against the till.

Three things shape this module.

**The grain is not the input's grain.** A sale has lines and payments; the fact is one row per day
per branch. Every measure is therefore aggregated *in its own temp table first* and joined
afterwards. Summing a sale-level column in the same ``group by`` as a line-level column multiplies
the sale by its line count — the "row multiplication after a join" failure, and the reason the
totals would look like a very good night (doc section 11).

**Voided records are extracted on purpose and excluded here.** A void is not a data-quality problem
to be cleaned away; it is a business event, reported as a count and an amount (rule X-01).

**A sale that cannot be attributed is quarantined whole.** Rule C-01 quarantines a sale whose lines
have no product name, because rejecting only the line would leave its money in this fact through the
header and remove it from the product fact — the two would then disagree about the same revenue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

import psycopg

from psync_transform.batch import Batch
from psync_transform.quarantine import quarantine, quarantined
from psync_transform.schema import STAGING_TABLES

__all__ = [
    "FactBuild",
    "FactError",
    "SourceCounts",
    "build_fct_daily_product_demand",
    "build_fct_daily_sales",
]


class FactError(RuntimeError):
    """A fact cannot be built from what the batch holds."""


@dataclass(frozen=True)
class SourceCounts:
    """What one source table contributed to the batch (doc section 7, check T3)."""

    table: str
    read: int
    quarantined: int

    @property
    def retained(self) -> int:
        return self.read - self.quarantined


@dataclass(frozen=True)
class FactBuild:
    """What one fact build did."""

    table: str
    business_dates: tuple[date, ...]
    rows_written: int
    counts: Mapping[str, SourceCounts]


# =============================================================================================
# The cleaning rules that can stop a row before it reaches the fact (doc section 3)
# =============================================================================================

# C-15: a status the code map does not know cannot be classified as revenue or not.
_UNKNOWN_SALE_STATUS = "s.status not in ('completed', 'voided')"

# C-14: the header is authoritative for revenue (rule B-01). If it contradicts itself, there is no
# trustworthy figure to publish — and zero occurrences in the profiled data.
_INVALID_SALE_TOTAL = """
    s.subtotal < 0 or s.discount < 0 or s.tax < 0 or s.total < 0
    or s.total <> s.subtotal - s.discount + s.tax
""".strip()

# C-01: a line with no product name has no identity at all, so the whole sale goes (doc rev 1.3).
_SALE_WITH_UNNAMED_LINE = """
    exists (
        select 1
        from public.stg_sales_transaction_items i
        where i.run_id = s.run_id
          and i.transaction_id = s.source_id
          and (i.name is null or btrim(i.name) = '')
    )
""".strip()

# C-21: a sale whose branch has no version in force on its own day cannot be placed in the grain.
_UNRESOLVED_BRANCH = """
    not exists (
        select 1
        from public.dim_branch b
        where b.branch_id = s.branch_id
          and b.valid_from <= (s.created_at at time zone %(tz)s)::date
          and (b.valid_to is null
               or (s.created_at at time zone %(tz)s)::date < b.valid_to)
    )
""".strip()

# C-13: a line that cannot be true cannot be aggregated.
_INVALID_LINE = """
    s.quantity <= 0
    or s.unit_price < 0
    or s.line_discount < 0
    or s.line_discount > s.quantity * s.unit_price
""".strip()

# C-17 and S-13: a settlement of zero or less is not a settlement, and a method the code map does
# not know would fall outside the three columns the fact publishes.
_INVALID_PAYMENT = """
    s.amount <= 0
    or s.method not in ('Cash', 'Card', 'Custom Order')
""".strip()


# =============================================================================================
# The build
# =============================================================================================

# Every sale that survived the cleaning rules, with its Manila business date and the branch version
# in force that day. Both statuses are kept: a voided sale contributes to voided_count and
# voided_amount (rule X-01), which is a measure, not a filter.
_INCOMING_SALE_SQL = r"""
create temp table incoming_sale on commit drop as
select s.source_id                               as transaction_id,
       (s.created_at at time zone %(tz)s)::date  as business_date,
       s.status,
       b.branch_key,
       s.total,
       s.tax,
       s.discount
from public.stg_sales_transactions s
left join public.dim_branch b
       on b.branch_id = s.branch_id
      and b.valid_from <= (s.created_at at time zone %(tz)s)::date
      and (b.valid_to is null or (s.created_at at time zone %(tz)s)::date < b.valid_to)
where s.run_id = %(run)s
  and not exists (
      select 1
      from public.quarantine_rows q
      where q.batch_id = %(batch)s
        and q.source_table = 'sales_transactions'
        and q.source_id = s.source_id::text
  )
"""

# The lines of those sales, with the product version in force on the line's own day (rule J-01).
_INCOMING_LINE_SQL = r"""
create temp table incoming_line on commit drop as
select i.source_id,
       i.transaction_id,
       s.business_date,
       s.branch_key,
       s.status,
       i.quantity,
       i.unit_price,
       i.line_discount,
       d.item_key,
       d.unit_cost
from public.stg_sales_transaction_items i
join incoming_sale s
  on s.transaction_id = i.transaction_id
left join public.dim_item d
       on d.item_ref = 'name:' || regexp_replace(btrim(lower(i.name)), '\s+', ' ', 'g')
      and d.valid_from <= s.business_date
      and (d.valid_to is null or s.business_date < d.valid_to)
where i.run_id = %(run)s
  and not exists (
      select 1
      from public.quarantine_rows q
      where q.batch_id = %(batch)s
        and q.source_table = 'sales_transaction_items'
        and q.source_id = i.source_id::text
  )
"""

# One row per (date, branch) that appears in the batch's sales — including a day whose sales were
# all voided, which is a real, reportable fact (rule A-06).
_SALE_TOTALS_SQL = r"""
create temp table sale_totals on commit drop as
select business_date,
       branch_key,
       count(*) filter (where status = 'completed')                     as transaction_count,
       coalesce(sum(total)    filter (where status = 'completed'), 0)   as gross_revenue,
       coalesce(sum(tax)      filter (where status = 'completed'), 0)   as tax_total,
       coalesce(sum(discount) filter (where status = 'completed'), 0)   as discount_total,
       count(*) filter (where status = 'voided')                        as voided_count,
       coalesce(sum(total) filter (where status = 'voided'), 0)         as voided_amount
from incoming_sale
group by 1, 2
"""

# Line measures, from live sales only (rule X-03).
_LINE_TOTALS_SQL = r"""
create temp table line_totals on commit drop as
select business_date,
       branch_key,
       count(*)                                                                   as line_count,
       coalesce(sum(quantity), 0)                                                 as units_sold,
       coalesce(sum(quantity * unit_price), 0)                                    as line_revenue_total,
       coalesce(sum(line_discount), 0)                                            as line_discount_total,
       coalesce(sum(case when unit_cost is not null
                         then quantity * unit_cost else 0 end), 0)                as cogs,
       coalesce(sum(case when unit_cost is not null
                         then quantity * unit_price - line_discount else 0 end), 0) as revenue_costed
from incoming_line
where status = 'completed'
group by 1, 2
"""

# How the money arrived. Captured payments only (rule X-02), and the three methods are the three
# columns, so their sum is the settled total by construction.
_PAYMENT_TOTALS_SQL = r"""
create temp table payment_totals on commit drop as
select s.business_date,
       s.branch_key,
       coalesce(sum(p.amount), 0)                                          as settled_total,
       coalesce(sum(p.amount) filter (where p.method = 'Cash'), 0)          as cash_total,
       coalesce(sum(p.amount) filter (where p.method = 'Card'), 0)          as card_total,
       coalesce(sum(p.amount) filter (where p.method = 'Custom Order'), 0)  as custom_order_total
from public.stg_payments p
join incoming_sale s
  on s.transaction_id = p.transaction_id
where p.run_id = %(run)s
  and p.status = 'captured'
  and not exists (
      select 1
      from public.quarantine_rows q
      where q.batch_id = %(batch)s
        and q.source_table = 'payments'
        and q.source_id = p.source_id::text
  )
group by 1, 2
"""

# The whole window is cleared, not just the dates that produced rows, so a day that has become empty
# is emptied rather than left stale (rule C-09).
_DELETE_SQL = "delete from public.fct_daily_sales where business_date between %(start)s and %(end)s"

# The money columns are related by identity and the table enforces them, so this statement only has
# to be honest about its inputs:
#
#   gross_revenue        = net_revenue + tax_total
#   net_revenue          = line_revenue_total - line_discount_total - unallocated_discount
#   settled_total        = cash_total + card_total + custom_order_total
#
# Rule B-10: profit is published only where the cost of every peso of revenue is known. A coverage
# of 100 on a day with no revenue is vacuously complete, and the day's profit is then zero — which
# is true, and better than NULL meaning "we did not check".
_INSERT_SQL = r"""
insert into public.fct_daily_sales (
    business_date, branch_key, transaction_count, line_count, units_sold,
    gross_revenue, net_revenue, tax_total, line_revenue_total,
    discount_total, line_discount_total, unallocated_discount,
    cogs, revenue_costed, cogs_coverage_pct, gross_profit, margin_pct,
    gross_profit_costed, margin_pct_costed, avg_transaction_value,
    settled_total, cash_total, card_total, custom_order_total,
    voided_count, voided_amount
)
with base as (
    select st.business_date,
           st.branch_key,
           st.transaction_count,
           st.voided_count,
           st.voided_amount,
           st.gross_revenue,
           st.tax_total,
           st.discount_total,
           st.gross_revenue - st.tax_total                        as net_revenue,
           coalesce(lt.line_count, 0)                             as line_count,
           coalesce(lt.units_sold, 0)                             as units_sold,
           coalesce(lt.line_revenue_total, 0)                     as line_revenue_total,
           coalesce(lt.line_discount_total, 0)                    as line_discount_total,
           coalesce(lt.cogs, 0)                                   as cogs,
           coalesce(lt.revenue_costed, 0)                         as revenue_costed,
           coalesce(lt.line_revenue_total, 0)
             - coalesce(lt.line_discount_total, 0)                as itemised_revenue,
           coalesce(pt.settled_total, 0)                          as settled_total,
           coalesce(pt.cash_total, 0)                             as cash_total,
           coalesce(pt.card_total, 0)                             as card_total,
           coalesce(pt.custom_order_total, 0)                     as custom_order_total
    from sale_totals st
    left join line_totals lt
           on lt.business_date = st.business_date
          and lt.branch_key = st.branch_key
    left join payment_totals pt
           on pt.business_date = st.business_date
          and pt.branch_key = st.branch_key
),
rated as (
    select base.*,
           case when itemised_revenue > 0
                then round(100 * revenue_costed / itemised_revenue, 2)
                else 100.00
           end as cogs_coverage_pct
    from base
)
select business_date, branch_key, transaction_count, line_count, units_sold,
       gross_revenue, net_revenue, tax_total, line_revenue_total,
       discount_total, line_discount_total,
       discount_total - line_discount_total                     as unallocated_discount,
       cogs, revenue_costed, cogs_coverage_pct,
       case when cogs_coverage_pct = 100
            then net_revenue - cogs end                        as gross_profit,
       case when cogs_coverage_pct = 100 and net_revenue > 0
            then round(100 * (net_revenue - cogs) / net_revenue, 2) end as margin_pct,
       revenue_costed - cogs                                   as gross_profit_costed,
       case when revenue_costed > 0
            then round(100 * (revenue_costed - cogs) / revenue_costed, 2) end as margin_pct_costed,
       case when transaction_count > 0
            then round(gross_revenue / transaction_count, 2) end as avg_transaction_value,
       settled_total, cash_total, card_total, custom_order_total,
       voided_count, voided_amount
from rated
"""


def _count(conn: psycopg.Connection, table: str, run_id) -> int:
    return conn.execute(
        f"select count(*) from public.{STAGING_TABLES[table]} where run_id = %s",
        (run_id,),
    ).fetchone()[0]


def _stage(conn: psycopg.Connection, batch: Batch, time_zone: str) -> dict[str, object]:
    """Quarantine what cannot be used, then stage what can.

    Every fact calls this, so the two cannot disagree about what was excluded — which is exactly
    the disagreement T12 would catch, one fact later. Calling it twice in a batch is harmless: the
    quarantine is idempotent and the temp tables are rebuilt from the same rows.
    """
    params: dict[str, object] = {
        "run": batch.parent_run_id,
        "batch": batch.batch_id,
        "tz": time_zone,
    }

    # --- cleaning: quarantine first, then use whatever is left --------------------------------
    quarantine(
        conn, batch,
        source_table="sales_transactions",
        rule_id="C-15", reason="unknown_status",
        detail="the sale status is not one the code map knows",
        condition=_UNKNOWN_SALE_STATUS,
    )
    quarantine(
        conn, batch,
        source_table="sales_transactions",
        rule_id="C-14", reason="invalid_sale_total",
        detail="the sale's own money columns do not add up",
        condition=_INVALID_SALE_TOTAL,
    )
    quarantine(
        conn, batch,
        source_table="sales_transactions",
        rule_id="C-01", reason="missing_product_name",
        detail="a line of this sale has no product name, so the sale cannot be attributed",
        condition=_SALE_WITH_UNNAMED_LINE,
    )
    quarantine(
        conn, batch,
        source_table="sales_transactions",
        rule_id="C-21", reason="unresolved_branch_key",
        detail="no branch version is in force on this sale's own business date",
        condition=_UNRESOLVED_BRANCH,
        params={"tz": time_zone},
    )
    quarantine(
        conn, batch,
        source_table="sales_transaction_items",
        rule_id="C-13", reason="invalid_line_value",
        detail="quantity, price or discount cannot be true",
        condition=_INVALID_LINE,
    )
    quarantine(
        conn, batch,
        source_table="payments",
        rule_id="C-17", reason="invalid_payment_amount",
        detail="a payment of zero or less, or a method the code map does not know",
        condition=_INVALID_PAYMENT,
    )

    # --- stage what survived -------------------------------------------------------------------
    conn.execute("drop table if exists incoming_sale")
    conn.execute(_INCOMING_SALE_SQL, params)
    conn.execute("drop table if exists incoming_line")
    conn.execute(_INCOMING_LINE_SQL, params)

    uncovered = conn.execute(
        "select count(*) from incoming_line where item_key is null"
    ).fetchone()[0]
    if uncovered:
        raise FactError(
            f"{uncovered} sale line(s) have no product version. The item dimension is built from "
            "the same lines, so this means it was built from different data — fix the order of the "
            "batch, not this statement."
        )

    unbranched = conn.execute(
        "select count(*) from incoming_sale where branch_key is null"
    ).fetchone()[0]
    if unbranched:
        raise FactError(
            f"{unbranched} sale(s) survived C-21 but resolved no branch version, which means the "
            "branch dimension changed between the check and the join."
        )

    return params


def build_fct_daily_sales(
    conn: psycopg.Connection, batch: Batch, time_zone: str
) -> FactBuild:
    """Rebuild the daily sales fact for every business date this batch covers."""
    params = _stage(conn, batch, time_zone)

    conn.execute(_SALE_TOTALS_SQL)
    conn.execute(_LINE_TOTALS_SQL)
    conn.execute(_PAYMENT_TOTALS_SQL, params)

    # --- replace the window ---------------------------------------------------------------------
    conn.execute(_DELETE_SQL, {"start": batch.window_start, "end": batch.window_end})
    written = conn.execute(_INSERT_SQL).rowcount

    dates = tuple(
        row[0]
        for row in conn.execute(
            "select business_date from public.fct_daily_sales "
            "where business_date between %(start)s and %(end)s order by 1",
            {"start": batch.window_start, "end": batch.window_end},
        ).fetchall()
    )

    counts = {
        table: SourceCounts(
            table=table,
            read=_count(conn, table, batch.parent_run_id),
            quarantined=quarantined(conn, batch, table),
        )
        for table in ("sales_transactions", "sales_transaction_items", "payments")
    }

    return FactBuild(
        table="fct_daily_sales",
        business_dates=dates,
        rows_written=written,
        counts=counts,
    )


# =============================================================================================
# fct_daily_product_demand                                     (doc section 6.1, rules A-02, A-04, B-04)
#
# One row per business_date x branch x item that sold. Deliberately not densified: a zero row would
# be indistinguishable from a day the batch never processed, and the unsold items a reorder decision
# needs live in fct_daily_stock_snapshot.
#
# Two steps, because the trailing demand average needs history that lives outside this batch's
# window. The insert writes the measures; the update then fills in the average by reading the fact
# as it now stands — the new rows plus whatever earlier batches wrote. Both happen inside the
# caller's transaction, so the brief moment where the averages are placeholders is never visible.
# =============================================================================================

_DELETE_DEMAND_SQL = (
    "delete from public.fct_daily_product_demand where business_date between %(start)s and %(end)s"
)

_DEMAND_BASE_SQL = r"""
insert into public.fct_daily_product_demand (
    business_date, branch_key, item_key, line_count, quantity_sold,
    line_revenue, discount_total, revenue, cogs, is_costed,
    demand_window_days, avg_daily_demand, forecast_demand_30d
)
select business_date,
       branch_key,
       item_key,
       count(*),
       coalesce(sum(quantity), 0)                                       as quantity_sold,
       coalesce(sum(quantity * unit_price), 0)                          as line_revenue,
       coalesce(sum(line_discount), 0)                                  as discount_total,
       coalesce(sum(quantity * unit_price), 0)
         - coalesce(sum(line_discount), 0)                              as revenue,
       coalesce(sum(case when unit_cost is not null
                         then quantity * unit_cost else 0 end), 0)      as cogs,
       bool_and(unit_cost is not null)                                  as is_costed,
       1, 0, 0
from incoming_line
where status = 'completed'
group by 1, 2, 3
"""

# The denominator is the branch's **trading days** in the window, counted from fct_daily_sales —
# not the days this product sold. A product that moved ten units on one day of seven would otherwise
# average 10 a day and run the shelf empty on a forecast built from it. `demand_window_days` records
# that denominator, so thin history is visible rather than folded into a number (rule B-13).
_DEMAND_AVERAGE_SQL = r"""
update public.fct_daily_product_demand as d
set demand_window_days   = w.trading_days,
    avg_daily_demand     = round(w.total_quantity::numeric / w.trading_days, 2),
    forecast_demand_30d  = round(30 * w.total_quantity::numeric / w.trading_days, 2)
from (
    select cur.business_date,
           cur.branch_key,
           cur.item_key,
           greatest(
               (select count(*)
                  from public.fct_daily_sales s
                 where s.branch_key = cur.branch_key
                   and s.business_date between cur.business_date - (%(window)s - 1)
                                           and cur.business_date),
               1
           )::smallint                                                  as trading_days,
           (select coalesce(sum(p.quantity_sold), 0)
              from public.fct_daily_product_demand p
             where p.branch_key = cur.branch_key
               and p.item_key = cur.item_key
               and p.business_date between cur.business_date - (%(window)s - 1)
                                       and cur.business_date)              as total_quantity
    from public.fct_daily_product_demand cur
    where cur.business_date between %(start)s and %(end)s
) w
where d.business_date = w.business_date
  and d.branch_key = w.branch_key
  and d.item_key = w.item_key
"""


def build_fct_daily_product_demand(
    conn: psycopg.Connection, batch: Batch, time_zone: str, demand_window_days: int
) -> FactBuild:
    """Rebuild the product demand fact for every business date this batch covers."""
    params = _stage(conn, batch, time_zone)
    params["start"] = batch.window_start
    params["end"] = batch.window_end
    params["window"] = demand_window_days

    conn.execute(_DELETE_DEMAND_SQL, params)
    conn.execute(_DEMAND_BASE_SQL, params)
    conn.execute(_DEMAND_AVERAGE_SQL, params)

    dates = tuple(
        row[0]
        for row in conn.execute(
            "select business_date from public.fct_daily_product_demand "
            "where business_date between %(start)s and %(end)s order by 1",
            {"start": batch.window_start, "end": batch.window_end},
        ).fetchall()
    )
    written = conn.execute(
        "select count(*) from public.fct_daily_product_demand "
        "where business_date between %(start)s and %(end)s",
        {"start": batch.window_start, "end": batch.window_end},
    ).fetchone()[0]

    counts = {
        table: SourceCounts(
            table=table,
            read=_count(conn, table, batch.parent_run_id),
            quarantined=quarantined(conn, batch, table),
        )
        for table in ("sales_transactions", "sales_transaction_items", "payments")
    }

    return FactBuild(
        table="fct_daily_product_demand",
        business_dates=dates,
        rows_written=written,
        counts=counts,
    )
