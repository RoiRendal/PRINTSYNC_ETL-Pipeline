"""The bulk loader (doc section 3).

Rows travel by `COPY … TO STDOUT` on the Stage 2 database and `COPY … FROM STDIN` on the warehouse,
because the two databases cannot be joined in one statement. The whole batch is a single
transaction on the target: a failure rolls back every table, so no partial day is ever published.

**Dimensions are upserted, not replaced** (§3.1). Facts from earlier days already reference their
keys, so a delete would raise a foreign-key violation the moment the warehouse holds a second day.
Rows still move by bulk COPY — into a temporary table, because COPY cannot upsert — and the upsert
runs from there.
"""

from __future__ import annotations

import uuid
from typing import Iterator

import psycopg

from psync_load.config import Settings
from psync_load.db import connect_source, connect_warehouse
from psync_load.handover import FACT_TABLES, REPORTING_TABLES, Handover
from psync_load.validation.preload import LOAD_COLUMNS

__all__ = ["DIMENSION_TABLES", "LOAD_ORDER", "PRIMARY_KEY", "load_batch"]

# Dimensions first: the facts declare foreign keys to them (doc section 1.4).
LOAD_ORDER = REPORTING_TABLES
DIMENSION_TABLES = tuple(t for t in LOAD_ORDER if t not in FACT_TABLES)

PRIMARY_KEY: dict[str, str] = {
    "dim_date": "date_key",
    "dim_branch": "branch_key",
    "dim_item": "item_key",
    "dim_order_status": "status_key",
}

_TARGET_COLUMNS_SQL = """
    select column_name
    from information_schema.columns
    where table_schema = 'public' and table_name = %s
    order by ordinal_position
"""


class LoadError(RuntimeError):
    """The batch could not be loaded."""


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


def _upsert_dimension(
    source: psycopg.Connection,
    target: psycopg.Connection,
    table: str,
    handover: Handover,
    run_id: uuid.UUID,
) -> int:
    """Stage the whole dimension in a temp table, then upsert it on its primary key."""
    target_columns, source_columns = _columns(target, table)
    key = PRIMARY_KEY[table]
    stage = f"_stage_{table}"

    target.execute(
        f"create temp table {stage} on commit drop as "
        f"select * from public.{table} with no data"
    )
    _stream(
        source,
        target,
        _select_sql(table, source_columns, scoped=False),
        (handover.batch_id, run_id),
        f"copy {stage} ({', '.join(target_columns)}) from stdin",
    )

    assignments = ", ".join(
        f"{name} = excluded.{name}" for name in target_columns if name != key
    )
    target.execute(
        f"insert into public.{table} ({', '.join(target_columns)}) "
        f"select {', '.join(target_columns)} from {stage} "
        f"on conflict ({key}) do update set {assignments}"
    )
    return target.execute(
        f"select count(*) from public.{table} where load_batch_id = %s",
        (handover.batch_id,),
    ).fetchone()[0]


def _copy_fact(
    source: psycopg.Connection,
    target: psycopg.Connection,
    table: str,
    handover: Handover,
    run_id: uuid.UUID,
) -> int:
    """Replace the batch window and bulk-insert the fact."""
    target_columns, source_columns = _columns(target, table)
    target.execute(
        f"delete from public.{table} where business_date between %s and %s",
        (handover.window_start, handover.window_end),
    )
    _stream(
        source,
        target,
        _select_sql(table, source_columns, scoped=True),
        (handover.batch_id, run_id, handover.window_start, handover.window_end),
        f"copy public.{table} ({', '.join(target_columns)}) from stdin",
    )
    return target.execute(
        f"select count(*) from public.{table} where load_batch_id = %s",
        (handover.batch_id,),
    ).fetchone()[0]


def load_batch(settings: Settings, handover: Handover, run_id: uuid.UUID) -> dict[str, int]:
    """Load one approved batch. Returns the rows written per table.

    One transaction on the warehouse: any failure raises out of this function and every table is
    rolled back (doc section 3.4).
    """
    loaded: dict[str, int] = {}
    with connect_source(settings) as source, connect_warehouse(settings) as target:
        # SET does not take a bind parameter; both values are ints from validated settings.
        target.execute(
            f"set local lock_timeout = {int(settings.lock_timeout_seconds) * 1000}"
        )
        target.execute(
            f"set local statement_timeout = {int(settings.statement_timeout_seconds) * 1000}"
        )

        for table in DIMENSION_TABLES:
            loaded[table] = _upsert_dimension(source, target, table, handover, run_id)
        for table in LOAD_ORDER:
            if table in FACT_TABLES:
                loaded[table] = _copy_fact(source, target, table, handover, run_id)

    return {table: loaded[table] for table in LOAD_ORDER}
