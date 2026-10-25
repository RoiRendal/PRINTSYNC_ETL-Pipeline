"""The pipeline's own database (doc section 1.6).

Everything the pipeline produces — staging rows, the run record, the logs — lives in
``psync_analytics``. The source is never written to, so this module only ever talks to the target,
and callers use it knowing that writing here is allowed.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from psync_extract.config import Settings

__all__ = ["connect_target"]


@contextmanager
def connect_target(settings: Settings) -> Iterator[psycopg.Connection]:
    """One connection to the pipeline's own database.

    The connection commits when the block ends normally and rolls back when it raises, so a
    caller can treat the block as one unit of work.
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
