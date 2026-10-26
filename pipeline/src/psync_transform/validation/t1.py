"""T1 — the input contract is present (doc sections 1.1, 6.4 and 7).

Two questions, both asked before a single row is read:

* **is the handover usable?** Only ``APPROVED`` and ``APPROVED WITH WARNING`` may be transformed.
  Stage 1 writes no manifest for any other decision, so reaching here with one means the file was
  edited by hand — which is worth stopping for.
* **is the staging table the shape this stage expects?** Every column in
  :mod:`psync_transform.schema` must exist, with its type family.

Why this check exists at all, when the database is the same one Stage 1 writes: because a staging
table can be older than this code. Revision 1.4 of the extraction contract added
``stg_sales_transaction_items.name`` through migration ``002``, and a database that was never
migrated still holds the seven tables — just not that column. Without T1 the batch would run, and
93 % of the shop's revenue would quietly have no product attached to it.
"""

from __future__ import annotations

import psycopg

from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.handover import ACCEPTED_DECISIONS, Handover
from psync_transform.schema import STAGING_SCHEMA, ColumnType
from psync_transform.validation.result import CheckResult

__all__ = ["check_input_contract"]

# information_schema spells types out; the registry uses short families. A type absent from this
# map is drift by definition — it is reported as its own spelling, which then fails the comparison.
_TYPE_FAMILY: dict[str, ColumnType] = {
    "uuid": "uuid",
    "text": "text",
    "numeric": "numeric",
    "integer": "integer",
    "timestamp with time zone": "timestamptz",
    "date": "date",
    "boolean": "boolean",
    "jsonb": "jsonb",
}


def _live_columns(settings: Settings) -> dict[str, dict[str, str]]:
    """Every column of the staging tables, as ``{table: {column: type family}}``."""
    tables = [spec.staging for spec in STAGING_SCHEMA]
    live: dict[str, dict[str, str]] = {}

    with connect_target(settings) as conn:
        rows = conn.execute(
            "select table_name, column_name, data_type "
            "from information_schema.columns "
            "where table_schema = 'public' and table_name = any(%s)",
            (tables,),
        ).fetchall()

    for table_name, column_name, data_type in rows:
        live.setdefault(table_name, {})[column_name] = _TYPE_FAMILY.get(data_type, data_type)

    return live


def check_input_contract(settings: Settings, handover: Handover) -> CheckResult:
    """The handover may be transformed, and staging is the shape this stage expects."""
    if handover.decision not in ACCEPTED_DECISIONS:
        return CheckResult(
            check_id="T1",
            status="FAIL",
            severity="critical",
            message=(
                f"the handover for {handover.business_date} records decision "
                f"{handover.decision!r}; only {' and '.join(ACCEPTED_DECISIONS)} may be transformed"
            ),
            error_code="TRF_HANDOVER_NOT_APPROVED",
        )

    try:
        live = _live_columns(settings)
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T1",
            status="FAIL",
            severity="critical",
            message=f"could not read the staging schema: {exc}",
            error_code="TRF_INPUT_UNREADABLE",
        )

    problems: list[str] = []

    for spec in STAGING_SCHEMA:
        columns = live.get(spec.staging)
        if not columns:
            problems.append(f"{spec.staging} does not exist")
            continue

        for column in spec.columns:
            actual = columns.get(column.name)
            if actual is None:
                problems.append(f"{spec.staging}.{column.name} is missing")
            elif actual != column.type:
                problems.append(
                    f"{spec.staging}.{column.name} is {actual}, expected {column.type}"
                )

    if problems:
        return CheckResult(
            check_id="T1",
            status="FAIL",
            severity="critical",
            message=(
                "staging does not match the input contract: "
                + "; ".join(problems[:8])
                + (f" (+{len(problems) - 8} more)" if len(problems) > 8 else "")
            ),
            error_code="TRF_INPUT_COLUMN_MISSING",
        )

    return CheckResult(
        check_id="T1",
        status="PASS",
        severity="critical",
        message=(
            f"{len(STAGING_SCHEMA)} staging tables match the input contract; "
            f"the handover is {handover.decision}"
        ),
    )
