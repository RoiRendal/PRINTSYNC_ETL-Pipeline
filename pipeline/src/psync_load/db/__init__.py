"""The two database connections used by Stage 3.

The load stage reads one database and writes another. It never opens a connection to PRINTSYNC.
Both connections carry a connect timeout, so an unreachable host fails the batch cleanly rather
than hanging a scheduled run.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from psync_load.config import Settings

__all__ = ["connect_source", "connect_warehouse"]


@contextmanager
def connect_source(settings: Settings) -> Iterator[psycopg.Connection]:
    """Read-only session against the Stage 2 output in ``psync_analytics``."""
    conn = psycopg.connect(
        settings.psync_analytics_dsn,
        connect_timeout=settings.connect_timeout_seconds,
    )
    try:
        with conn:
            conn.execute("set default_transaction_read_only = on")
            yield conn
    finally:
        conn.close()


@contextmanager
def connect_warehouse(settings: Settings) -> Iterator[psycopg.Connection]:
    """One unit of work against ``psync_warehouse`` (doc section 3.4).

    The block commits on normal exit and rolls back on an exception, so a caller can treat the
    whole batch as one transaction.
    """
    conn = psycopg.connect(
        settings.psync_warehouse_dsn,
        connect_timeout=settings.connect_timeout_seconds,
    )
    try:
        with conn:
            yield conn
    finally:
        conn.close()
