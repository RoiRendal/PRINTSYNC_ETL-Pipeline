"""The ``sales_transaction_items`` extractor (doc sections 1.3 and 2.2).

The line-level detail behind each sale: what was sold, how many, at what price.

This table has **no timestamp of its own**, which decides the whole query. The only way in is
through the parent sale: join to ``sales_transactions`` and re-apply the same
``created_at OR voided_at`` predicate the sales extractor uses (P3). A date filter on the item table
is not merely unnecessary — it is impossible, and reaching for one is how items belonging to a
late-voided sale get lost.
"""

from __future__ import annotations

from typing import Iterator

import psycopg

from psync_extract.db.connection import server_side_cursor
from psync_extract.window import ExtractionWindow

__all__ = ["COLUMNS", "SQL", "TABLE", "extract_sales_transaction_items"]

TABLE = "sales_transaction_items"

# In the order section 2.2 lists them.
COLUMNS: tuple[str, ...] = (
    "id",
    "transaction_id",
    "inventory_item_id",
    "quantity",
    "unit_price",
    "line_discount",
)

SQL = f"""
    select {", ".join(f"i.{column}" for column in COLUMNS)}
    from public.{TABLE} i
    join public.sales_transactions s on s.id = i.transaction_id
    where (s.created_at >= %(start)s and s.created_at < %(end)s)
       or (s.voided_at >= %(start)s and s.voided_at < %(end)s)
    order by i.transaction_id, i.id
"""


def extract_sales_transaction_items(
    conn: psycopg.Connection, window: ExtractionWindow
) -> Iterator[tuple]:
    """Every item whose parent sale was created **or voided** inside the read range."""
    with server_side_cursor(conn, TABLE) as cursor:
        cursor.execute(SQL, {"start": window.read_start, "end": window.read_end})
        yield from cursor
