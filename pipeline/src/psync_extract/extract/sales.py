"""The ``sales_transactions`` extractor (doc sections 1.3 and 2.1).

The spine of the pipeline: every other table joins back to a sale. This is the first extractor, so
it also sets the shape the other six follow — one statement, a server-side cursor, and the read
range taken from the window rather than recomputed.
"""

from __future__ import annotations

from typing import Iterator

import psycopg

from psync_extract.db.connection import server_side_cursor
from psync_extract.window import ExtractionWindow

__all__ = ["COLUMNS", "SQL", "TABLE", "extract_sales_transactions"]

TABLE = "sales_transactions"

# In the order section 2.1 lists them. `id` becomes `source_id` in staging (section 6.2).
COLUMNS: tuple[str, ...] = (
    "id",
    "status",
    "subtotal",
    "discount",
    "tax",
    "total",
    "payment_method",
    "created_at",
    "voided_at",
    "customer_id",
    "branch_id",
)

SQL = f"""
    select {", ".join(COLUMNS)}
    from public.{TABLE}
    where (created_at >= %(start)s and created_at < %(end)s)
       or (voided_at >= %(start)s and voided_at < %(end)s)
    order by created_at, id
"""


def extract_sales_transactions(
    conn: psycopg.Connection, window: ExtractionWindow
) -> Iterator[tuple]:
    """Every sale created **or voided** inside the read range.

    The ``voided_at`` half of the predicate is what catches P1: a sale from last week that was
    voided yesterday belongs in yesterday's run. ``sales_transactions`` has no ``updated_at``, so
    there is no other way to notice the change (L2, P2).

    Voided sales are extracted, not filtered out — Stage 1 copies what it reads, and the
    Transformation stage decides what a void means (section 7.3).
    """
    with server_side_cursor(conn, TABLE) as cursor:
        cursor.execute(SQL, {"start": window.read_start, "end": window.read_end})
        yield from cursor
