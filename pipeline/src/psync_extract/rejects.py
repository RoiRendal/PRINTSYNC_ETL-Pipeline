"""Structural rejects (doc sections 3 and 4).

Rejected rows at this stage are only **structural** — a child row whose parent sale is not in the
run. Business-rule rejects (a negative amount, an unknown status) belong to the Check stage and are
recorded separately. Keeping the two apart is what lets a reader tell "the extraction broke" from
"the shop data is bad".

A healthy run rejects nothing. The counts belong in ``pipeline_runs.rows_rejected`` and the reason
in ``reject_reason``, so V7's ``rows_read = rows_extracted + rows_rejected`` balances.
"""

from __future__ import annotations

import psycopg

__all__ = ["CHILD_TABLES", "ORPHAN_REASON", "reject_orphans"]

ORPHAN_REASON = "orphan_transaction_id"

# The two staging tables that point at a sale (doc section 2).
CHILD_TABLES: tuple[str, ...] = ("stg_sales_transaction_items", "stg_payments")


def reject_orphans(conn: psycopg.Connection, run_id: str) -> dict[str, int]:
    """Delete child rows whose parent sale is not in this run; return counts per table.

    An orphan means the item or payment was read but its sale was not — a broken window, not bad
    shop data. Keeping it would leave revenue attached to a sale that does not exist.
    """
    removed: dict[str, int] = {}

    with conn.cursor() as cursor:
        for child in CHILD_TABLES:
            cursor.execute(
                f"""
                delete from public.{child} c
                where c.run_id = %s
                  and not exists (
                      select 1
                      from public.stg_sales_transactions s
                      where s.run_id = c.run_id
                        and s.source_id = c.transaction_id
                  )
                """,
                (run_id,),
            )
            removed[child] = cursor.rowcount

    return removed
