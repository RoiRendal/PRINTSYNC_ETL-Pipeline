"""Read-only access to the PRINTSYNC source database (doc sections 1.2, 1.3, 1.5 L7/L8).

The pipeline reads PRINTSYNC and never writes to it. That boundary is enforced in three places,
and this module is the second of them:

1. the source login is read-only, provisioned once on PRINTSYNC's side (doc section 1.6);
2. every session opened here is marked read-only **at the server** before a single row is read;
3. nothing in this module can issue DDL or DML.

Encryption is carried by the connection string itself (``sslmode=require``); see
``pipeline/.env.example``. Every read goes through a server-side cursor, so a large extract
streams in batches instead of being held in memory (doc section 1.3).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from psync_extract.config import Settings

__all__ = ["SourceConnectionError", "connect_source", "server_side_cursor"]


class SourceConnectionError(RuntimeError):
    """PRINTSYNC could not be reached, or the session could not be made read-only."""


@contextmanager
def connect_source(settings: Settings) -> Iterator[psycopg.Connection]:
    """One connection to PRINTSYNC, read-only for its whole life.

    The connection is closed however the block ends. A failure to connect, or to prepare the
    session, is reported as :class:`SourceConnectionError` so the caller can decide between
    retrying and rejecting the run (doc section 7.1).
    """
    try:
        conn = psycopg.connect(
            settings.psync_source_dsn,
            connect_timeout=settings.connect_timeout_seconds,
            autocommit=False,
        )
    except psycopg.OperationalError as exc:
        raise SourceConnectionError(
            "could not connect to the PRINTSYNC source within "
            f"{settings.connect_timeout_seconds}s: {exc}"
        ) from exc

    try:
        try:
            # `default_transaction_read_only` governs *subsequent* transactions, so the
            # statement is committed before the caller runs anything. From here on every
            # transaction this session starts is read-only, and a write fails at the server.
            conn.execute("SET default_transaction_read_only = on")
            conn.commit()
        except psycopg.Error as exc:
            raise SourceConnectionError(
                f"connected to PRINTSYNC but could not make the session read-only: {exc}"
            ) from exc

        yield conn
    finally:
        conn.close()


def server_side_cursor(
    conn: psycopg.Connection, name: str = "psync_extract"
) -> psycopg.Cursor:
    """A named cursor: rows stream from the server as they are fetched.

    A named cursor lives inside a transaction, so the caller must be inside one (psycopg opens
    one on the first statement when the connection is not in autocommit mode).
    """
    return conn.cursor(name=name)
