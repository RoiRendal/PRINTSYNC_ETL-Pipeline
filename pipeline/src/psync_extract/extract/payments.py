"""The ``payments`` extractor (doc sections 1.3 and 2.3).

How each sale was paid. A sale can be settled by **more than one payment**, so this extractor
returns one row per payment — never one row per sale. Collapsing them (a `distinct`, a join that
fans in) would leave the day's takings quietly short, and nothing downstream could tell.
"""

from __future__ import annotations

from typing import Iterator

import psycopg

from psync_extract.db.connection import server_side_cursor
from psync_extract.window import ExtractionWindow

__all__ = ["COLUMNS", "SQL", "TABLE", "extract_payments"]

TABLE = "payments"

# In the order section 2.3 lists them.
COLUMNS: tuple[str, ...] = (
    "id",
    "transaction_id",
    "amount",
    "method",
    "status",
    "created_at",
    "voided_at",
)

SQL = f"""
    select {", ".join(COLUMNS)}
    from public.{TABLE}
    where (created_at >= %(start)s and created_at < %(end)s)
       or (voided_at >= %(start)s and voided_at < %(end)s)
    order by created_at, id
"""


def extract_payments(
    conn: psycopg.Connection, window: ExtractionWindow
) -> Iterator[tuple]:
    """Every payment created **or voided** inside the read range, one row per payment."""
    with server_side_cursor(conn, TABLE) as cursor:
        cursor.execute(SQL, {"start": window.read_start, "end": window.read_end})
        yield from cursor
