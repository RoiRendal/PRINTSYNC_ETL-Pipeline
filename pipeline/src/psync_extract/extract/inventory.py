"""The ``inventory_items`` extractor (doc sections 1.3 and 2.5).

The product catalogue, extracted **in full** on every run.

There is deliberately no window here. Stock changes with every sale, so "what changed since
yesterday" is not a question this table can answer usefully — and a partial catalogue would be worse
than useless downstream, because a product missing from staging looks like a product that does not
exist rather than one that was not re-read.

The absence of a predicate is the property worth protecting: a snapshot that quietly acquires a date
filter still looks correct on a busy day, and silently drops most of the catalogue on a quiet one.
"""

from __future__ import annotations

from typing import Iterator

import psycopg

from psync_extract.db.connection import server_side_cursor

__all__ = ["COLUMNS", "SQL", "TABLE", "extract_inventory_items"]

TABLE = "inventory_items"

# In the order section 2.5 lists them. `cost_price` is here because profit needs it later.
COLUMNS: tuple[str, ...] = (
    "id",
    "sku",
    "name",
    "category",
    "price",
    "cost_price",
    "stock",
    "reorder_level",
    "uom",
    "updated_at",
    "branch_id",
)

SQL = f"""
    select {", ".join(COLUMNS)}
    from public.{TABLE}
    order by sku, id
"""


def extract_inventory_items(conn: psycopg.Connection) -> Iterator[tuple]:
    """Every inventory item, every run — no date range, no filter."""
    with server_side_cursor(conn, TABLE) as cursor:
        cursor.execute(SQL)
        yield from cursor
