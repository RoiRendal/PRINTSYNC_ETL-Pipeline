"""V2 — the source still has the tables and columns the extraction expects (doc section 3).

Compares the live database against the registry in :mod:`psync_extract.schema` **before** any row
is read. A missing table, a missing column or a changed type fails the run, so a PRINTSYNC
migration cannot silently turn a column we depend on into something else (doc section 6.4).

A column **added** at source is not drift: the extractors name the columns they select, so an
additive migration cannot break a run. The same goes for extra tables.
"""

from __future__ import annotations

from psycopg import Connection

from psync_extract.config import Settings
from psync_extract.db.connection import SourceConnectionError, connect_source
from psync_extract.schema import SOURCE_SCHEMA
from psync_extract.validation.result import CheckResult

__all__ = ["check_schema_drift"]

# information_schema spells types its own way; the registry uses families (see schema.py).
_FAMILIES = {
    "uuid": "uuid",
    "text": "text",
    "character varying": "text",
    "character": "text",
    "numeric": "numeric",
    "integer": "integer",
    "timestamp with time zone": "timestamptz",
    "boolean": "boolean",
}

_MAX_PROBLEMS_SHOWN = 10


def _live_columns(conn: Connection) -> dict[str, dict[str, str]]:
    """Every column in ``public``, keyed by table then column, as a type family."""
    rows = conn.execute(
        """
        select table_name, column_name, data_type
        from information_schema.columns
        where table_schema = 'public'
        """
    ).fetchall()

    live: dict[str, dict[str, str]] = {}
    for table_name, column_name, data_type in rows:
        live.setdefault(table_name, {})[column_name] = _FAMILIES.get(data_type, data_type)
    return live


def _problems(live: dict[str, dict[str, str]]) -> list[str]:
    """Every way the live schema differs from the registry, in registry order."""
    found: list[str] = []

    for spec in SOURCE_SCHEMA:
        actual = live.get(spec.name)
        if actual is None:
            found.append(f"table public.{spec.name} is missing")
            continue

        for column in spec.columns:
            live_type = actual.get(column.name)
            if live_type is None:
                found.append(f"public.{spec.name}.{column.name} is missing")
            elif live_type != column.type:
                found.append(
                    f"public.{spec.name}.{column.name} is {live_type}, expected {column.type}"
                )

    return found


def check_schema_drift(settings: Settings) -> CheckResult:
    """Confirm every table and column the extraction reads is still there, and still the right type."""
    try:
        with connect_source(settings) as conn:
            live = _live_columns(conn)
    except SourceConnectionError as exc:
        return CheckResult(
            check_id="V2",
            status="FAIL",
            severity="critical",
            message=str(exc),
            error_code=exc.error_code,
        )

    found = _problems(live)
    if found:
        shown = "; ".join(found[:_MAX_PROBLEMS_SHOWN])
        hidden = len(found) - _MAX_PROBLEMS_SHOWN
        suffix = f" (+{hidden} more)" if hidden > 0 else ""
        return CheckResult(
            check_id="V2",
            status="FAIL",
            severity="critical",
            message=f"source schema drifted: {shown}{suffix}",
            error_code="SRC_SCHEMA_DRIFT",
        )

    columns = sum(len(spec.columns) for spec in SOURCE_SCHEMA)
    return CheckResult(
        check_id="V2",
        status="PASS",
        severity="critical",
        message=f"{len(SOURCE_SCHEMA)} tables and {columns} columns match the contract",
    )
