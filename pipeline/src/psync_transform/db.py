"""The pipeline's own database, from the transformation side (doc section 1.1).

Stage 2 has exactly one database. It never opens a connection to PRINTSYNC, so there is no source
and target to confuse here — only ``psync_analytics``, which this stage reads and writes.

Stage 1's ``psync_extract.db.target`` is not imported, for the same reason its configuration is not:
the two stages share a database and nothing else, and a shared module would let a change on one
side reach the other without anyone noticing.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from psync_transform.config import Settings

__all__ = ["connect_target"]


@contextmanager
def connect_target(settings: Settings) -> Iterator[psycopg.Connection]:
    """One connection to ``psync_analytics``.

    The block commits when it ends normally and rolls back when it raises, so a caller can treat
    it as one unit of work — which is how every fact write in this stage is meant to be used.
    """
    conn = psycopg.connect(
        settings.psync_target_dsn,
        connect_timeout=settings.connect_timeout_seconds,
    )
    try:
        with conn:
            yield conn
    finally:
        conn.close()
