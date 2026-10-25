"""Writing an extractor's rows into the pipeline's own database (doc sections 6.1 and 6.2).

Stage 1 does not clean anything. A row read from PRINTSYNC is written to staging unchanged, apart
from the three control columns every staging table carries: the run it belongs to, the business day
it was read for, and when it was read.

Two conventions from the contract are enforced here rather than left to each extractor:

* the source primary key is renamed ``id`` -> ``source_id``; every other column keeps its name;
* the writer never chooses its own column list — it takes the extractor's, so staging cannot drift
  away from the statement that produced the rows.

This module only ever touches the **target** database. The source session is read-only and stays
that way (doc section 1.6).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable, Sequence

import psycopg

__all__ = [
    "CONTROL_COLUMNS",
    "STAGING_TABLES",
    "StagingError",
    "staging_columns",
    "staging_table_for",
    "write_rows",
]

# Source table -> staging table (doc section 6.1).
STAGING_TABLES: dict[str, str] = {
    "sales_transactions": "stg_sales_transactions",
    "sales_transaction_items": "stg_sales_transaction_items",
    "payments": "stg_payments",
    "orders": "stg_orders",
    "inventory_items": "stg_inventory_items",
    "business_settings": "stg_business_settings",
    "branches": "stg_branches",
}

CONTROL_COLUMNS: tuple[str, ...] = ("run_id", "business_date", "extracted_at")


class StagingError(RuntimeError):
    """A table has no staging counterpart, or a row does not match the columns."""


def staging_table_for(source_table: str) -> str:
    """The staging table for a source table, or a clear error."""
    try:
        return STAGING_TABLES[source_table]
    except KeyError:
        raise StagingError(f"no staging table is mapped to {source_table!r}") from None


def staging_columns(source_columns: Sequence[str]) -> tuple[str, ...]:
    """``id`` becomes ``source_id``; every other name is unchanged (doc section 6.2)."""
    return tuple("source_id" if column == "id" else column for column in source_columns)


def write_rows(
    conn: psycopg.Connection,
    *,
    table: str,
    columns: Sequence[str],
    rows: Iterable[tuple],
    run_id: str,
    business_date: date,
    extracted_at: datetime | None = None,
) -> int:
    """Insert one extractor's rows into its staging table, and return how many were written.

    The caller owns the transaction: nothing is committed here, so a failure part-way leaves the
    run's rows in the caller's hands rather than half-visible.
    """
    staging = staging_table_for(table)
    target_columns = (*CONTROL_COLUMNS, *staging_columns(columns))
    placeholders = ", ".join(["%s"] * len(target_columns))
    sql = (
        f"insert into public.{staging} ({', '.join(target_columns)}) "
        f"values ({placeholders})"
    )
    stamp = extracted_at or datetime.now(timezone.utc)

    written = 0
    with conn.cursor() as cursor:
        for row in rows:
            if len(row) != len(columns):
                raise StagingError(
                    f"{table}: expected {len(columns)} values per row, got {len(row)}"
                )
            cursor.execute(sql, (run_id, business_date, stamp, *row))
            written += 1

    return written
