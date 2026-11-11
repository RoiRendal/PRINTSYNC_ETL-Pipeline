"""The bulk loader (doc section 3).

Rows travel by `COPY … TO STDOUT` on the Stage 2 database and `COPY … FROM STDIN` on the warehouse,
because the two databases cannot be joined in one statement. The whole batch is a single
transaction on the target: a failure rolls back every table, so no partial day is ever published.

**Dimensions are upserted, not replaced** (§3.1). Facts from earlier days already reference their
keys, so a delete would raise a foreign-key violation the moment the warehouse holds a second day.
Rows still move by bulk COPY — into a temporary table, because COPY cannot upsert — and the upsert
runs from there.

**Facts are staged too**, so a row that cannot be written can be recorded in `load_rejects` instead
of aborting the statement. A `COPY` straight into a table would fail the whole batch on one bad
row, and the specification asks for the row to be counted, not the batch to die (§5, L13).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable

import psycopg

from psync_load.config import Settings
from psync_load.db import connect_source, connect_warehouse
from psync_load.handover import FACT_TABLES, REPORTING_TABLES, Handover
from psync_load.schema import LOAD_COLUMNS
from psync_load.snapshot import write_snapshot
from psync_load.checks import CheckResult
from psync_load.decisions import Decision, decide

__all__ = [
    "DIMENSION_TABLES",
    "FK_PREDICATE",
    "LOAD_ORDER",
    "LoadOutcome",
    "PRIMARY_KEY",
    "TableLoad",
    "load_batch",
]

# Dimensions first: the facts declare foreign keys to them (doc section 1.4).
LOAD_ORDER = REPORTING_TABLES
DIMENSION_TABLES = tuple(t for t in LOAD_ORDER if t not in FACT_TABLES)

PRIMARY_KEY: dict[str, tuple[str, ...]] = {
    "dim_date": ("date_key",),
    "dim_branch": ("branch_key",),
    "dim_item": ("item_key",),
    "dim_order_status": ("status_key",),
    "fct_daily_sales": ("business_date", "branch_key"),
    "fct_daily_product_demand": ("business_date", "branch_key", "item_key"),
    "fct_daily_stock_snapshot": ("business_date", "branch_key", "item_key"),
    "fct_daily_order_status": ("business_date", "status_key"),
}

# The condition a staged fact row must satisfy to be writable. Written here, over the stage alias
# ``s``, so the reject and the insert agree about what "orphan" means.
FK_PREDICATE: dict[str, str] = {
    "fct_daily_sales": (
        "exists (select 1 from public.dim_date d where d.date_key = s.business_date) "
        "and exists (select 1 from public.dim_branch b where b.branch_key = s.branch_key)"
    ),
    "fct_daily_product_demand": (
        "exists (select 1 from public.dim_date d where d.date_key = s.business_date) "
        "and exists (select 1 from public.dim_branch b where b.branch_key = s.branch_key) "
        "and exists (select 1 from public.dim_item i where i.item_key = s.item_key)"
    ),
    "fct_daily_stock_snapshot": (
        "exists (select 1 from public.dim_date d where d.date_key = s.business_date) "
        "and exists (select 1 from public.dim_branch b where b.branch_key = s.branch_key) "
        "and exists (select 1 from public.dim_item i where i.item_key = s.item_key)"
    ),
    "fct_daily_order_status": (
        "exists (select 1 from public.dim_date d where d.date_key = s.business_date) "
        "and exists (select 1 from public.dim_order_status o where o.status_key = s.status_key)"
    ),
}

_TARGET_COLUMNS_SQL = """
    select column_name
    from information_schema.columns
    where table_schema = 'public' and table_name = %s
    order by ordinal_position
"""


class LoadError(RuntimeError):
    """The batch could not be loaded."""


@dataclass(frozen=True)
class TableLoad:
    """What happened to one table in one batch."""

    received: int
    inserted: int
    rejected: int


@dataclass
class LoadOutcome:
    """The result of one load attempt, whether or not it was committed."""

    loads: dict[str, TableLoad] = field(default_factory=dict)
    checks: dict[str, CheckResult] = field(default_factory=dict)
    decision: Decision | None = None
    committed: bool = False

    @property
    def inserted(self) -> int:
        return sum(load.inserted for load in self.loads.values())

    @property
    def rejected(self) -> int:
        return sum(load.rejected for load in self.loads.values())

    @property
    def critical_failures(self) -> list[CheckResult]:
        return [result for result in self.checks.values() if result.is_critical_failure]


def _columns(conn: psycopg.Connection, table: str) -> tuple[list[str], list[str]]:
    """The target's columns, and the subset that comes from the source."""
    target = [row[0] for row in conn.execute(_TARGET_COLUMNS_SQL, (table,)).fetchall()]
    if not target:
        raise LoadError(f"table {table} does not exist in the warehouse")
    source = [name for name in target if name not in LOAD_COLUMNS]
    return target, source


def _select_sql(table: str, source_columns: list[str], *, scoped: bool) -> str:
    """The source query as a COPY statement: its own columns plus the three bookkeeping values.

    The values are bound, not interpolated; the column list comes from information_schema on the
    target, so nothing in this string can carry SQL that was not written in this file. Both ends
    use PostgreSQL's default text format, so the stream round-trips unchanged.
    """
    columns = ", ".join(source_columns)
    where = " where business_date between %s and %s" if scoped else ""
    return (
        f"copy (select {columns}, %s::text, %s::uuid, now() "
        f"from public.{table}{where}) to stdout"
    )


def _stream(
    source: psycopg.Connection,
    target: psycopg.Connection,
    select_sql: str,
    select_params: tuple,
    copy_sql: str,
) -> None:
    """Copy one query's rows into one table, chunk by chunk."""
    with source.cursor() as reader, target.cursor() as writer:
        with reader.copy(select_sql, select_params) as outgoing:
            with writer.copy(copy_sql) as incoming:
                for chunk in outgoing:
                    incoming.write(chunk)


def _stage(
    source: psycopg.Connection,
    target: psycopg.Connection,
    table: str,
    columns: list[str],
    source_columns: list[str],
    handover: Handover,
    run_id: uuid.UUID,
    *,
    scoped: bool,
) -> str:
    """Copy the source into a temp table shaped like the target. Returns the stage name."""
    stage = f"_stage_{table}"
    target.execute(
        f"create temp table {stage} on commit drop as "
        f"select * from public.{table} with no data"
    )
    params: tuple = (handover.batch_id, run_id)
    if scoped:
        params += (handover.window_start, handover.window_end)
    _stream(
        source,
        target,
        _select_sql(table, source_columns, scoped=scoped),
        params,
        f"copy {stage} ({', '.join(columns)}) from stdin",
    )
    return stage


def _upsert_dimension(
    source: psycopg.Connection,
    target: psycopg.Connection,
    table: str,
    handover: Handover,
    run_id: uuid.UUID,
) -> TableLoad:
    """Stage the whole dimension in a temp table, then upsert it on its primary key."""
    target_columns, source_columns = _columns(target, table)
    key = PRIMARY_KEY[table][0]
    stage = _stage(
        source, target, table, target_columns, source_columns, handover, run_id, scoped=False
    )

    received = target.execute(f"select count(*) from {stage}").fetchone()[0]
    assignments = ", ".join(
        f"{name} = excluded.{name}" for name in target_columns if name != key
    )
    target.execute(
        f"insert into public.{table} ({', '.join(target_columns)}) "
        f"select {', '.join(target_columns)} from {stage} "
        f"on conflict ({key}) do update set {assignments}"
    )
    inserted = target.execute(
        f"select count(*) from public.{table} where load_batch_id = %s",
        (handover.batch_id,),
    ).fetchone()[0]
    return TableLoad(received=received, inserted=inserted, rejected=0)


def _copy_fact(
    source: psycopg.Connection,
    target: psycopg.Connection,
    table: str,
    handover: Handover,
    run_id: uuid.UUID,
) -> TableLoad:
    """Replace the batch window: reject orphans, then bulk-insert the rest."""
    target_columns, source_columns = _columns(target, table)
    stage = _stage(
        source, target, table, target_columns, source_columns, handover, run_id, scoped=True
    )
    predicate = FK_PREDICATE[table]

    received = target.execute(f"select count(*) from {stage}").fetchone()[0]

    target.execute(
        "delete from public.load_rejects where batch_id = %s and table_name = %s",
        (handover.batch_id, table),
    )
    with target.cursor() as cursor:
        cursor.execute(
            f"""
            insert into public.load_rejects (batch_id, table_name, rule_id, reason, payload)
            select %s, %s, 'L-10', 'no matching dimension member', to_jsonb(s)
            from {stage} s
            where not ({predicate})
            """,
            (handover.batch_id, table),
        )
        rejected = cursor.rowcount

    target.execute(
        f"delete from public.{table} where business_date between %s and %s",
        (handover.window_start, handover.window_end),
    )
    target.execute(
        f"insert into public.{table} ({', '.join(target_columns)}) "
        f"select {', '.join(f's.{name}' for name in target_columns)} from {stage} s "
        f"where ({predicate})"
    )
    inserted = target.execute(
        f"select count(*) from public.{table} where load_batch_id = %s",
        (handover.batch_id,),
    ).fetchone()[0]
    return TableLoad(received=received, inserted=inserted, rejected=rejected)


def load_batch(
    settings: Settings,
    handover: Handover,
    run_id: uuid.UUID,
    *,
    validate: Callable[
        [psycopg.Connection, psycopg.Connection, Handover, dict[str, TableLoad]],
        dict[str, CheckResult],
    ]
    | None = None,
) -> LoadOutcome:
    """Load one approved batch and, if a validator is given, check it before committing.

    The whole batch is one transaction. A critical failure in ``validate`` rolls it back and returns
    ``committed=False`` — no partial day is ever published (doc section 3.4).
    """
    loads: dict[str, TableLoad] = {}
    checks: dict[str, CheckResult] = {}

    with connect_source(settings) as source, connect_warehouse(settings) as target:
        # SET does not take a bind parameter; both values are ints from validated settings.
        target.execute(
            f"set local lock_timeout = {int(settings.lock_timeout_seconds) * 1000}"
        )
        target.execute(
            f"set local statement_timeout = {int(settings.statement_timeout_seconds) * 1000}"
        )

        # Before the first write, so the snapshot is the state a mistake would be undone to.
        write_snapshot(target, settings, handover)

        for table in DIMENSION_TABLES:
            loads[table] = _upsert_dimension(source, target, table, handover, run_id)
        for table in LOAD_ORDER:
            if table in FACT_TABLES:
                loads[table] = _copy_fact(source, target, table, handover, run_id)

        if validate is not None:
            checks = validate(source, target, handover, loads)
            decision = decide(checks)
            if not decision.publishes:
                target.rollback()
                return LoadOutcome(
                    loads=loads, checks=checks, decision=decision, committed=False
                )
            return LoadOutcome(
                loads=loads, checks=checks, decision=decision, committed=True
            )

    return LoadOutcome(loads=loads, checks=checks, committed=True)
