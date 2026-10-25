"""The ``orders`` extractor (doc sections 1.3 and 2.4).

Custom and production jobs. These live for days — placed, designed, in production, collected — so
the question is not "when was it placed" but **"did anything about it change yesterday"**.

That is why this table is windowed on ``updated_at`` alone. Adding a ``created_at`` predicate would
pull in orders that were placed long ago and have not moved since, and worse, would make the
extractor's behaviour depend on a column that has nothing to do with what changed.
"""

from __future__ import annotations

from typing import Iterator

import psycopg

from psync_extract.db.connection import server_side_cursor
from psync_extract.window import ExtractionWindow

__all__ = ["COLUMNS", "SQL", "TABLE", "extract_orders"]

TABLE = "orders"

# In the order section 2.4 lists them.
COLUMNS: tuple[str, ...] = (
    "id",
    "status",
    "amount",
    "customer_id",
    "created_at",
    "updated_at",
    "branch_id",
)

SQL = f"""
    select {", ".join(COLUMNS)}
    from public.{TABLE}
    where updated_at >= %(start)s and updated_at < %(end)s
    order by updated_at, id
"""


def extract_orders(
    conn: psycopg.Connection, window: ExtractionWindow
) -> Iterator[tuple]:
    """Every order whose ``updated_at`` falls inside the read range."""
    with server_side_cursor(conn, TABLE) as cursor:
        cursor.execute(SQL, {"start": window.read_start, "end": window.read_end})
        yield from cursor
