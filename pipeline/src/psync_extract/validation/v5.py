"""V5 — identifiers present (doc section 3).

A row without a key cannot be joined downstream, and a child row without a parent link cannot be
attributed to a sale. Every staging table carries ``source_id``; ``sales_transaction_items`` and
``payments`` also carry ``transaction_id``.

Both columns are ``NOT NULL`` in the staging schema, and ``source_id`` is part of each primary key,
so on a healthy database this check cannot fail. That is exactly its job: a run-time assertion that
the constraint is still there. A staging table rebuilt without it would accept nulls silently and
surface much later, as revenue that belongs to no sale.
"""

from __future__ import annotations

import psycopg

from psync_extract.config import Settings
from psync_extract.db.target import connect_target
from psync_extract.validation.result import CheckResult

__all__ = ["IDENTIFIER_COLUMNS", "check_identifiers"]

# Which identifier columns must be present on each staging table (doc section 3).
IDENTIFIER_COLUMNS: dict[str, tuple[str, ...]] = {
    "stg_sales_transactions": ("source_id",),
    "stg_sales_transaction_items": ("source_id", "transaction_id"),
    "stg_payments": ("source_id", "transaction_id"),
    "stg_orders": ("source_id",),
    "stg_inventory_items": ("source_id",),
    "stg_business_settings": ("source_id",),
    "stg_branches": ("source_id",),
}


def check_identifiers(settings: Settings, run_id: str) -> CheckResult:
    """Confirm no row in this run is missing a key or a parent link."""
    problems: list[str] = []

    try:
        with connect_target(settings) as conn:
            for staging, columns in IDENTIFIER_COLUMNS.items():
                # One query per column, so the message names the column that is actually null
                # rather than every column the table is supposed to have.
                for column in columns:
                    count = conn.execute(
                        f"select count(*) from public.{staging} "
                        f"where run_id = %s and {column} is null",
                        (run_id,),
                    ).fetchone()[0]

                    if count:
                        problems.append(f"{staging}.{column}: {count} null row(s)")
    except psycopg.Error as exc:
        return CheckResult(
            check_id="V5",
            status="FAIL",
            severity="critical",
            message=f"could not check identifiers: {exc}",
            error_code="TGT_QUERY_FAILED",
        )

    if problems:
        return CheckResult(
            check_id="V5",
            status="FAIL",
            severity="critical",
            message="null identifiers found — " + "; ".join(problems),
            error_code="NULL_IDENTIFIER",
        )

    return CheckResult(
        check_id="V5",
        status="PASS",
        severity="critical",
        message=(
            f"{len(IDENTIFIER_COLUMNS)} staging tables keyed: no null source_id, "
            "no null transaction_id"
        ),
    )
