"""The ``business_settings`` snapshot extractor (doc sections 2.6 and 1.5 L5).

One row per branch, read in full every run — the same snapshot reasoning as inventory: a missing
settings row would leave a branch's sales without a VAT rate or a currency, which is worse than
re-reading rows that did not change.

Note the key. ``business_settings.id`` is an **integer**, the only non-UUID primary key among the
seven tables (§2.6). Copying the column list from another extractor would get this wrong.
"""

from __future__ import annotations

from typing import Iterator

import psycopg

from psync_extract.db.connection import server_side_cursor

__all__ = ["COLUMNS", "SQL", "TABLE", "extract_business_settings"]

TABLE = "business_settings"

# In the order section 2.6 lists them.
COLUMNS: tuple[str, ...] = (
    "id",
    "branch_id",
    "vat_rate",
    "currency_symbol",
    "time_zone",
)

SQL = f"""
    select {", ".join(COLUMNS)}
    from public.{TABLE}
    order by id
"""


def extract_business_settings(conn: psycopg.Connection) -> Iterator[tuple]:
    """Every branch's settings, every run."""
    with server_side_cursor(conn, TABLE) as cursor:
        cursor.execute(SQL)
        yield from cursor
