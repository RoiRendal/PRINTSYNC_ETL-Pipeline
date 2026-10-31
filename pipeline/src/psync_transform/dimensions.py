"""Building the dimensions (doc section 5.5).

Three dimensions live here. ``dim_date`` is generated — a calendar is arithmetic, not data.
``dim_branch`` and ``dim_item`` are SCD Type 2: an attribute that changes closes the current version
and opens a new one, so a fact row from last week still points at the settings that were true last
week.

The version mechanics are worth stating once, because getting them wrong is silent:

* ``valid_from`` is **inclusive**, ``valid_to`` is **exclusive**, and ``valid_to IS NULL`` means
  "still current" (rule M-06). Half-open intervals, because a closed one makes the boundary day
  belong to two versions.
* A version is compared against the incoming attributes as a **whole row**. Comparing field by
  field invites a version that differs in one column and is missed in another.
* A **rerun on the same business date** must update the version it created, not close and reopen it:
  closing it would set ``valid_to = valid_from``, which the table refuses — and rightly so.

Nothing here writes to the facts, and nothing here is committed by this module: the caller owns the
transaction, so a batch that fails halfway leaves the previous output untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import psycopg

from psync_transform.batch import Batch

__all__ = [
    "DimensionBuild",
    "DimensionError",
    "build_dim_branch",
    "build_dim_date",
    "build_dim_item",
]


class DimensionError(RuntimeError):
    """A dimension cannot be built from what the batch holds."""


@dataclass(frozen=True)
class DimensionBuild:
    """What one dimension build did, in the terms the run record uses (doc section 8).

    ``rows_unchanged`` is not a term in any reconciliation: a dimension row that did not need a new
    version is not a modified record, it is the same record. It is reported because "nothing
    changed" is the answer most nights, and a silent zero is indistinguishable from a broken rule.
    """

    table: str
    rows_written: int
    rows_closed: int = 0
    rows_unchanged: int = 0

    @property
    def records_affected(self) -> int:
        """Records this build touched, for ``transformation_rule_counts``."""
        return self.rows_written + self.rows_closed


# =============================================================================================
# dim_date                                                                          (rule M-01)
#
# Generated for the batch window *and* the trailing demand window, so the demand average in rule
# B-13 always has dates to join. `on conflict do nothing`: a date is never rewritten, because a
# calendar does not change and a second opinion about 2026-10-17 would be a bug.
# =============================================================================================
_DIM_DATE_SQL = r"""
insert into public.dim_date (
    date_key, year, quarter, month, month_name,
    day_of_month, iso_week, day_of_week, day_name, is_weekend
)
select d::date,
       extract(year from d)::smallint,
       extract(quarter from d)::smallint,
       extract(month from d)::smallint,
       to_char(d, 'FMMonth'),
       extract(day from d)::smallint,
       extract(week from d)::smallint,
       extract(isodow from d)::smallint,
       to_char(d, 'FMDay'),
       extract(isodow from d) in (6, 7)
from generate_series(%(start)s::date, %(end)s::date, interval '1 day') as d
on conflict (date_key) do nothing
"""


def build_dim_date(
    conn: psycopg.Connection, batch: Batch, demand_window_days: int
) -> DimensionBuild:
    """Every date this batch could need: the window, plus the demand look-back behind it."""
    start = batch.window_start - timedelta(days=demand_window_days)
    end = batch.window_end

    written = conn.execute(_DIM_DATE_SQL, {"start": start, "end": end}).rowcount
    present = conn.execute(
        "select count(*) from public.dim_date where date_key between %s and %s",
        (start, end),
    ).fetchone()[0]

    return DimensionBuild(
        table="dim_date",
        rows_written=written,
        rows_unchanged=present - written,
    )


# =============================================================================================
# dim_branch                                                                (rules M-02, M-05, M-06)
# =============================================================================================

# A branch with no settings row cannot become a version: vat_rate, currency_symbol and time_zone
# are NOT NULL, and inventing them would put a made-up VAT rate on real revenue. Fail, name the
# branch, and let an operator fix the source.
_BRANCHES_WITHOUT_SETTINGS_SQL = """
select b.source_id
from public.stg_branches b
where b.run_id = %(run_id)s
  and not exists (
      select 1
      from public.stg_business_settings s
      where s.run_id = %(run_id)s
        and s.branch_id = b.source_id
  )
"""

# The incoming attributes, normalised once so the two statements below cannot disagree about what
# they are comparing (rule C-10: trim, then collapse internal runs of whitespace). Created and
# dropped inside the caller's transaction, so a failed build leaves nothing behind.
_DROP_INCOMING_BRANCH_SQL = "drop table if exists incoming_branch"

_INCOMING_BRANCH_SQL = r"""
create temp table incoming_branch on commit drop as
with sold as (
    -- The first day this branch sold anything in this batch. A version has to be in force on the
    -- day a sale happened, and the batch's window reaches back further than its business date —
    -- so the batch date is the wrong day to start it (rule M-02).
    select t.branch_id,
           min((t.created_at at time zone %(tz)s)::date) as first_seen
    from public.stg_sales_transactions t
    where t.run_id = %(run_id)s
    group by 1
)
select b.source_id                                    as branch_id,
       regexp_replace(btrim(b.code), '\s+', ' ', 'g')  as code,
       regexp_replace(btrim(b.name), '\s+', ' ', 'g')  as name,
       b.is_active,
       s.vat_rate,
       btrim(s.currency_symbol)                        as currency_symbol,
       btrim(s.time_zone)                              as time_zone,
       coalesce(x.first_seen, %(d)s)                   as effective_date
from public.stg_branches b
join public.stg_business_settings s
  on s.run_id = b.run_id
 and s.branch_id = b.source_id
left join sold x
       on x.branch_id = b.source_id
where b.run_id = %(run_id)s
"""

# A version opened by an earlier attempt at this batch may start later than the day the branch was
# actually first sold — the anchoring was the batch date, not the sale date. Move it back rather
# than opening a second version: a conflict here means real history already occupies that day, and
# failing loudly is better than guessing which version is true.
_BACKDATE_BRANCH_VERSIONS_SQL = """
update public.dim_branch as b
set valid_from = i.effective_date
from incoming_branch as i
where b.branch_id = i.branch_id
  and b.is_current
  and b.valid_from > i.effective_date
"""

# Close the versions whose attributes have changed. A version that starts on the effective date is
# left alone: it is this batch's own version from an earlier attempt, and the upsert below refreshes
# it in place instead of closing it (which would make valid_to = valid_from).
_CLOSE_CHANGED_BRANCHES_SQL = """
update public.dim_branch as b
set valid_to = i.effective_date,
    is_current = false
from incoming_branch as i
where b.branch_id = i.branch_id
  and b.is_current
  and b.valid_from < i.effective_date
  and (b.code, b.name, b.is_active, b.vat_rate, b.currency_symbol, b.time_zone)
      is distinct from
      (i.code, i.name, i.is_active, i.vat_rate, i.currency_symbol, i.time_zone)
"""

# Open this batch's version for every branch that has no current one — plus, on a rerun, the
# version this batch already opened, which the conflict clause refreshes.
_UPSERT_BRANCH_VERSION_SQL = """
insert into public.dim_branch (
    branch_id, code, name, is_active, vat_rate, currency_symbol, time_zone,
    valid_from, valid_to, is_current
)
select i.branch_id, i.code, i.name, i.is_active, i.vat_rate, i.currency_symbol, i.time_zone,
       i.effective_date, null, true
from incoming_branch as i
left join public.dim_branch as b
       on b.branch_id = i.branch_id
      and b.is_current
where b.branch_key is null
   or b.valid_from = i.effective_date
on conflict (branch_id, valid_from) do update
set code            = excluded.code,
    name            = excluded.name,
    is_active       = excluded.is_active,
    vat_rate        = excluded.vat_rate,
    currency_symbol = excluded.currency_symbol,
    time_zone       = excluded.time_zone,
    valid_to        = null,
    is_current      = true
"""

_UNCHANGED_BRANCHES_SQL = """
select count(*)
from incoming_branch as i
join public.dim_branch as b
  on b.branch_id = i.branch_id
 and b.is_current
where b.valid_from < i.effective_date
"""


def build_dim_branch(
    conn: psycopg.Connection, batch: Batch, *, time_zone: str
) -> DimensionBuild:
    """Bring ``dim_branch`` up to date with this batch's branch rows, SCD Type 2."""
    run_id = batch.parent_run_id

    orphans = conn.execute(_BRANCHES_WITHOUT_SETTINGS_SQL, {"run_id": run_id}).fetchall()
    if orphans:
        listed = ", ".join(str(row[0]) for row in orphans)
        raise DimensionError(
            f"{len(orphans)} branch(es) in this batch have no business_settings row: {listed}. "
            "VAT rate, currency and time zone would have to be invented to build a version, and "
            "an invented VAT rate on real revenue is worse than a stopped batch."
        )

    conn.execute(_DROP_INCOMING_BRANCH_SQL)
    conn.execute(
        _INCOMING_BRANCH_SQL,
        {"run_id": run_id, "d": batch.business_date, "tz": time_zone},
    )

    conn.execute(_BACKDATE_BRANCH_VERSIONS_SQL)
    closed = conn.execute(_CLOSE_CHANGED_BRANCHES_SQL).rowcount
    written = conn.execute(_UPSERT_BRANCH_VERSION_SQL).rowcount
    unchanged = conn.execute(_UNCHANGED_BRANCHES_SQL).fetchone()[0]

    return DimensionBuild(
        table="dim_branch",
        rows_written=written,
        rows_closed=closed,
        rows_unchanged=unchanged,
    )


# =============================================================================================
# dim_item                                                                  (rules M-03, C-02…C-05)
#
# The one dimension that exists because the data is what it is. `inventory_item_id` is null on
# 93.4% of sale lines (finding F-01), so a product's identity is the name printed on the line, and
# the catalogue link is an attribute rather than the key.
#
# Two sources feed one natural key:
#
#   * the catalogue snapshot — every item, sold or not, because fct_daily_stock_snapshot needs a row
#     for the products that did NOT sell;
#   * the distinct product names on this batch's sale lines — 93.4% of the shop's revenue.
#
# They meet on `item_ref = 'name:' || normalised(name)`, so a catalogue item and a sold product with
# the same name are one product. The catalogue wins when both exist: its attributes are richer, and
# a name-only product has nothing but a name.
#
# The three version statements mirror build_dim_branch deliberately. A shared builder would have to
# generate the SQL, and generated SQL is what nobody can read in a pull request; two literal blocks
# side by side are easy to diff. **If you change one, change the other** — T15 checks both tables
# with the same rule, which is what catches a divergence.
# =============================================================================================

_DROP_INCOMING_ITEM_SQL = "drop table if exists incoming_item"

_INCOMING_ITEM_SQL = r"""
create temp table incoming_item on commit drop as
with catalogue as (
    select 'name:' || regexp_replace(btrim(lower(i.name)), '\s+', ' ', 'g') as item_ref,
           regexp_replace(btrim(i.name), '\s+', ' ', 'g')                    as item_name,
           i.source_id                                                       as inventory_item_id,
           upper(regexp_replace(btrim(i.sku), '\s+', ' ', 'g'))              as sku,
           coalesce(
               nullif(regexp_replace(btrim(i.category), '\s+', ' ', 'g'), ''),
               'Uncategorised'
           )                                                                 as category,
           nullif(regexp_replace(btrim(i.uom), '\s+', ' ', 'g'), '')         as uom,
           i.price                                                           as unit_price,
           i.cost_price                                                      as unit_cost,
           true                                                              as is_catalogue_item
    from public.stg_inventory_items i
    where i.run_id = %(run_id)s
),
sold as (
    -- A line with no name has no product identity at all. It is not dropped here: rule C-01
    -- quarantines it when the facts are built, so the revenue stays visible as rejected.
    select 'name:' || regexp_replace(btrim(lower(s.name)), '\s+', ' ', 'g') as item_ref,
           -- One identity per normalised name, so the display name must not depend on which row
           -- arrived first. The alphabetically first spelling is arbitrary but stable.
           min(regexp_replace(btrim(s.name), '\s+', ' ', 'g'))               as item_name,
           -- The first day this product was sold in this batch. A version has to be in force on
           -- the day it was sold, and the window reaches back further than the business date —
           -- so the batch date is the wrong day to start it (rule M-03).
           min((t.created_at at time zone %(tz)s)::date)                     as first_seen
    from public.stg_sales_transaction_items s
    join public.stg_sales_transactions t
      on t.run_id = s.run_id
     and t.source_id = s.transaction_id
    where s.run_id = %(run_id)s
      and s.name is not null
      and btrim(s.name) <> ''
    group by 1
)
select c.item_ref, c.item_name, c.inventory_item_id, c.sku, c.category, c.uom,
       c.unit_price, c.unit_cost, c.is_catalogue_item,
       coalesce(s.first_seen, %(d)s) as effective_date
from catalogue c
left join sold s
       on s.item_ref = c.item_ref
union all
select s.item_ref, s.item_name, null, null, 'Uncategorised', null, null, null, false,
       s.first_seen
from sold s
where not exists (select 1 from catalogue c where c.item_ref = s.item_ref)
"""

# Two catalogue rows that normalise to one name would collapse into one product, and the surviving
# `inventory_item_id` would be whichever row the planner happened to return first — which is how one
# branch's cost price ends up on another branch's demand. The dimension has no branch column
# (doc section 6.1), so this cannot be represented: stop, and let the contract be revised.
_DUPLICATE_CATALOGUE_SQL = """
select item_ref, string_agg(inventory_item_id::text, ', ' order by inventory_item_id)
from incoming_item
where is_catalogue_item
group by item_ref
having count(*) > 1
"""

# A version opened by an earlier attempt at this batch may start later than the day the product was
# actually first sold — the anchoring was the batch date, not the sale date. Move it back rather
# than opening a second version: a conflict here means real history already occupies that day, and
# failing loudly is better than guessing which version is true.
_BACKDATE_ITEM_VERSIONS_SQL = """
update public.dim_item as d
set valid_from = i.effective_date
from incoming_item as i
where d.item_ref = i.item_ref
  and d.is_current
  and d.valid_from > i.effective_date
"""

_CLOSE_CHANGED_ITEMS_SQL = """
update public.dim_item as d
set valid_to = i.effective_date,
    is_current = false
from incoming_item as i
where d.item_ref = i.item_ref
  and d.is_current
  and d.valid_from < i.effective_date
  and (d.item_name, d.inventory_item_id, d.sku, d.category, d.uom,
       d.unit_price, d.unit_cost, d.is_catalogue_item)
      is distinct from
      (i.item_name, i.inventory_item_id, i.sku, i.category, i.uom,
       i.unit_price, i.unit_cost, i.is_catalogue_item)
"""

_UPSERT_ITEM_VERSION_SQL = """
insert into public.dim_item (
    item_ref, item_name, inventory_item_id, sku, category, uom,
    unit_price, unit_cost, is_catalogue_item, valid_from, valid_to, is_current
)
select i.item_ref, i.item_name, i.inventory_item_id, i.sku, i.category, i.uom,
       i.unit_price, i.unit_cost, i.is_catalogue_item, i.effective_date, null, true
from incoming_item as i
left join public.dim_item as d
       on d.item_ref = i.item_ref
      and d.is_current
where d.item_key is null
   or d.valid_from = i.effective_date
on conflict (item_ref, valid_from) do update
set item_name         = excluded.item_name,
    inventory_item_id = excluded.inventory_item_id,
    sku               = excluded.sku,
    category          = excluded.category,
    uom               = excluded.uom,
    unit_price        = excluded.unit_price,
    unit_cost         = excluded.unit_cost,
    is_catalogue_item = excluded.is_catalogue_item,
    valid_to          = null,
    is_current        = true
"""

_UNCHANGED_ITEMS_SQL = """
select count(*)
from incoming_item as i
join public.dim_item as d
  on d.item_ref = i.item_ref
 and d.is_current
where d.valid_from < i.effective_date
"""


def build_dim_item(
    conn: psycopg.Connection, batch: Batch, *, time_zone: str
) -> DimensionBuild:
    """Bring ``dim_item`` up to date with this batch's products, SCD Type 2."""
    run_id = batch.parent_run_id

    conn.execute(_DROP_INCOMING_ITEM_SQL)
    conn.execute(
        _INCOMING_ITEM_SQL,
        {"run_id": run_id, "d": batch.business_date, "tz": time_zone},
    )

    duplicates = conn.execute(_DUPLICATE_CATALOGUE_SQL).fetchall()
    if duplicates:
        listed = "; ".join(f"{ref} ({ids})" for ref, ids in duplicates)
        raise DimensionError(
            "two catalogue items normalise to the same product name, so their identity is "
            f"ambiguous: {listed}. The item dimension has no branch column, so it cannot hold both "
            "versions; the contract needs revising before this batch can run."
        )

    conn.execute(_BACKDATE_ITEM_VERSIONS_SQL)
    closed = conn.execute(_CLOSE_CHANGED_ITEMS_SQL).rowcount
    written = conn.execute(_UPSERT_ITEM_VERSION_SQL).rowcount
    unchanged = conn.execute(_UNCHANGED_ITEMS_SQL).fetchone()[0]

    return DimensionBuild(
        table="dim_item",
        rows_written=written,
        rows_closed=closed,
        rows_unchanged=unchanged,
    )
