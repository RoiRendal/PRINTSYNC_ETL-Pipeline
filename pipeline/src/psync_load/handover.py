"""The load's input contract (doc section 1.1).

Stage 2 writes no manifest file — Transformation §10.3 and revision 1.10 say so. Its handover is
the ``transformation_runs`` ledger row for one ``batch_id``: the run-level row (``table_name IS
NULL``) carrying the window, decision, status and code version, plus one row per output table
carrying ``records_output``.

This module reads that row and nothing else. It does not approve or reject a batch — that is L3's
job (§4) — because the check that refuses an unapproved batch must be able to name the decision it
found.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

import psycopg

from psync_load.config import Settings
from psync_load.db import connect_source

__all__ = ["Handover", "HandoverError", "REPORTING_TABLES", "load_handover"]

# The eight published tables, in load order (doc section 1.4). Dimensions first, facts second.
REPORTING_TABLES = (
    "dim_date",
    "dim_branch",
    "dim_item",
    "dim_order_status",
    "fct_daily_sales",
    "fct_daily_product_demand",
    "fct_daily_stock_snapshot",
    "fct_daily_order_status",
)

FACT_TABLES = frozenset(REPORTING_TABLES[4:])

_RUN_SQL = """
    select run_id, business_date, batch_window_start, batch_window_end,
           transformation_status, decision, code_version
    from public.transformation_runs
    where batch_id = %s and table_name is null
    order by transformation_started_at desc
    limit 1
"""

_COUNTS_SQL = """
    select table_name, records_output
    from public.transformation_runs
    where batch_id = %s and table_name is not null
"""


class HandoverError(RuntimeError):
    """The batch cannot be loaded as asked."""


@dataclass(frozen=True)
class Handover:
    """What Stage 2 published for one batch, as the ledger recorded it."""

    batch_id: str
    run_id: UUID
    business_date: date
    window_start: date
    window_end: date
    status: str
    decision: str | None
    code_version: str
    counts: dict[str, int]

    @property
    def total_rows(self) -> int:
        """Rows the batch reported writing, across every table it reports."""
        return sum(self.counts.values())

    def expected_rows(self, table: str) -> int | None:
        """The number of rows to load for ``table``, or ``None`` when it is a full load.

        A fact's count is the handover's ``records_output``. A dimension is copied whole, so its
        expected size is whatever the source holds at load time — ``dim_date`` reports 0 because it
        only inserts dates it has not seen, while the table holds eleven.
        """
        return None if table not in FACT_TABLES else self.counts.get(table)


def load_handover(settings: Settings) -> Handover:
    """Read the handover for ``settings.batch_id`` from the Stage 2 database."""
    batch_id = settings.batch_id
    if not batch_id:
        raise HandoverError("no batch_id was given; pass --batch <batch_id>")

    try:
        with connect_source(settings) as conn:
            row = conn.execute(_RUN_SQL, (batch_id,)).fetchone()
            if row is None:
                raise HandoverError(
                    f"no transformation run for batch {batch_id!r}. Stage 2 has not published "
                    "this batch, so there is nothing to load."
                )
            (
                run_id,
                business_date,
                window_start,
                window_end,
                status,
                decision,
                code_version,
            ) = row

            counts = {
                table: output
                for table, output in conn.execute(_COUNTS_SQL, (batch_id,)).fetchall()
                if table in REPORTING_TABLES
            }
    except psycopg.Error as exc:
        raise HandoverError(f"could not read the handover: {exc}") from exc

    # Only the facts are required: their rows in the window are exactly what this run wrote, so
    # records_output is the number the load must reproduce. A dimension's records_output counts the
    # rows *this run inserted*, which is 0 for dim_date on a re-run and absent for the seeded
    # dim_order_status — neither is the number of rows to load, because dimensions load in full.
    missing = [table for table in FACT_TABLES if table not in counts]
    if missing:
        raise HandoverError(
            f"the handover for {batch_id!r} names no output count for: {', '.join(missing)}. "
            "A batch with an incomplete ledger is not a loadable batch."
        )

    return Handover(
        batch_id=batch_id,
        run_id=run_id,
        business_date=business_date,
        window_start=window_start,
        window_end=window_end,
        status=status,
        decision=decision,
        code_version=code_version,
        counts=counts,
    )
