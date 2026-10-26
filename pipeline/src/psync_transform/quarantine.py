"""Recording what could not be transformed (doc sections 3, 7 and 9).

Nothing in this stage is ever dropped silently. A row is either **retained** — it is in the batch,
whether or not it feeds a particular measure — or it is **quarantined** here, with the rule that
caught it, the batch it belongs to and the parent extraction run.

The payload is the offending row itself, as ``to_jsonb`` of its staging row. That is deliberate: a
message that says "row 8f3a… had a bad total" is useless a month later, and the staging rows are
pruned at 90 days while the quarantine is kept for 24. The payload is the only copy that survives.

No customer data is stored: Stage 1 does not extract any (doc section 9).
"""

from __future__ import annotations

from typing import Mapping

import psycopg

from psync_transform.batch import Batch
from psync_transform.schema import STAGING_TABLES

__all__ = ["QuarantineError", "quarantine", "quarantined"]


class QuarantineError(RuntimeError):
    """A quarantine write could not be made as asked."""


def quarantine(
    conn: psycopg.Connection,
    batch: Batch,
    *,
    source_table: str,
    rule_id: str,
    reason: str,
    detail: str,
    condition: str,
    params: Mapping[str, object] | None = None,
) -> int:
    """Quarantine every staging row of one table that matches ``condition``.

    ``condition`` is a SQL predicate written by this package — never by a caller at run time — and
    ``source_table`` is checked against the staging registry, so neither can introduce SQL that was
    not written here. It is a string rather than a parameter because a predicate cannot be bound;
    ``params`` carries the values the predicate does need (a time zone, say).

    The insert is idempotent on ``(batch_id, source_table, source_id, rule_id)``, so a retried batch
    does not quarantine the same row twice (doc section 1.2).
    """
    staging = STAGING_TABLES.get(source_table)
    if staging is None:
        raise QuarantineError(
            f"{source_table!r} is not a staging table; known tables are "
            f"{sorted(STAGING_TABLES)}"
        )

    sql = f"""
        insert into public.quarantine_rows (
            batch_id, run_id, parent_run_id, business_date,
            source_table, source_id, rule_id, reason, detail, payload
        )
        select %(batch)s, %(run)s, %(parent)s, %(date)s,
               %(table)s, s.source_id::text, %(rule)s, %(reason)s, %(detail)s, to_jsonb(s)
        from public.{staging} s
        where s.run_id = %(run)s
          and ({condition})
        on conflict (batch_id, source_table, source_id, rule_id) do nothing
    """

    values: dict[str, object] = {
        "batch": batch.batch_id,
        "run": batch.parent_run_id,
        "parent": batch.parent_run_id,
        "date": batch.business_date,
        "table": source_table,
        "rule": rule_id,
        "reason": reason,
        "detail": detail,
    }
    if params:
        values.update(params)

    return conn.execute(sql, values).rowcount


def quarantined(conn: psycopg.Connection, batch: Batch, source_table: str) -> int:
    """How many rows of one table this batch has quarantined so far."""
    return conn.execute(
        "select count(*) from public.quarantine_rows "
        "where batch_id = %s and source_table = %s",
        (batch.batch_id, source_table),
    ).fetchone()[0]
