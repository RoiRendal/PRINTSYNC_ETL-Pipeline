"""The ``branches`` snapshot extractor (doc section 2.7).

A four-column lookup, read in full every run. It is what makes ``branch_id`` mean something: every
other table carries a branch, and without this one the ids are opaque.

Read in full rather than windowed because a branch row is small, changes rarely, and a missing
branch would make its sales unattributable rather than merely stale.
"""

from __future__ import annotations

from typing import Iterator

import psycopg

from psync_extract.db.connection import server_side_cursor

__all__ = ["COLUMNS", "SQL", "TABLE", "extract_branches"]

TABLE = "branches"

# In the order section 2.7 lists them.
COLUMNS: tuple[str, ...] = (
    "id",
    "code",
    "name",
    "is_active",
)

SQL = f"""
    select {", ".join(COLUMNS)}
    from public.{TABLE}
    order by code
"""


def extract_branches(conn: psycopg.Connection) -> Iterator[tuple]:
    """Every branch, every run."""
    with server_side_cursor(conn, TABLE) as cursor:
        cursor.execute(SQL)
        yield from cursor
