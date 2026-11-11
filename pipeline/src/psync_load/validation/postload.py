"""The post-load checks (doc section 5).

L7–L13 run **inside** the target transaction, after the rows are written and before `COMMIT`, so a
critical failure rolls the batch back rather than reporting a problem that is already published.

They reconcile the warehouse against the handover and the source — they never repair anything. A
value that is wrong at this point is a Stage 2 bug, and §8 is where it is reported.
"""

from __future__ import annotations

from decimal import Decimal

import psycopg

from psync_load.handover import FACT_TABLES, REPORTING_TABLES, Handover
from psync_load.loader import FK_PREDICATE, PRIMARY_KEY, TableLoad
from psync_load.checks import CheckResult

__all__ = ["run_post_load_checks"]

# Money columns reconciled to the cent between source and warehouse (doc section 5, L12).
MONEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "fct_daily_sales": ("net_revenue", "tax_total", "settled_total", "voided_amount"),
    "fct_daily_product_demand": ("revenue", "cogs"),
}

_NOT_NULL_SQL = """
    select column_name
    from information_schema.columns
    where table_schema = 'public' and table_name = %s and is_nullable = 'NO'
    order by ordinal_position
"""


def _ok(check_id: str, message: str) -> CheckResult:
    return CheckResult(check_id, "PASS", "critical", message)


def _fail(check_id: str, message: str, error_code: str, severity: str = "critical") -> CheckResult:
    return CheckResult(check_id, "FAIL", severity, message, error_code)  # type: ignore[arg-type]


def _l7_reconciliation(loads: dict[str, TableLoad]) -> CheckResult:
    """records_received = records_inserted + records_rejected, per table."""
    problems = [
        f"{table}: {load.received} received, {load.inserted} inserted, {load.rejected} rejected"
        for table, load in loads.items()
        if load.received != load.inserted + load.rejected
    ]
    if problems:
        return _fail("L7", "; ".join(problems[:5]), "LOAD_RECONCILIATION")
    total = sum(load.received for load in loads.values())
    return _ok("L7", f"{total} received = {total} inserted + 0 rejected")


def _l8_row_count(
    target: psycopg.Connection, handover: Handover, loads: dict[str, TableLoad]
) -> CheckResult:
    """Each table holds the rows the handover said it would."""
    problems = []
    for table in REPORTING_TABLES:
        actual = target.execute(
            f"select count(*) from public.{table} where load_batch_id = %s",
            (handover.batch_id,),
        ).fetchone()[0]
        expected = handover.expected_rows(table)
        if expected is None:
            load = loads.get(table)
            if load is None:
                problems.append(f"{table}: no load record for this table")
                continue
            expected = load.received
        if actual != expected:
            problems.append(f"{table}: {actual} in the warehouse, {expected} expected")
    if problems:
        return _fail("L8", "; ".join(problems[:5]), "LOAD_ROW_COUNT")
    return _ok("L8", f"every table holds its expected rows for {handover.batch_id}")


def _l9_uniqueness(target: psycopg.Connection, handover: Handover) -> CheckResult:
    """No duplicate primary keys."""
    problems = []
    for table in REPORTING_TABLES:
        keys = ", ".join(PRIMARY_KEY[table])
        duplicates = target.execute(
            f"select count(*) - count(distinct ({keys})) from public.{table} "
            "where load_batch_id = %s",
            (handover.batch_id,),
        ).fetchone()[0]
        if duplicates:
            problems.append(f"{table}: {duplicates} duplicate key(s) on ({keys})")
    if problems:
        return _fail("L9", "; ".join(problems[:5]), "LOAD_KEY_DUPLICATE")
    return _ok("L9", f"every primary key in {len(REPORTING_TABLES)} tables is unique")


def _l10_referential(target: psycopg.Connection, handover: Handover) -> CheckResult:
    """No orphan facts: every foreign key resolves to a dimension row."""
    problems = []
    for table, predicate in FK_PREDICATE.items():
        orphans = target.execute(
            f"select count(*) from public.{table} s "
            f"where s.load_batch_id = %s and not ({predicate})",
            (handover.batch_id,),
        ).fetchone()[0]
        if orphans:
            problems.append(f"{table}: {orphans} orphan row(s)")
    if problems:
        return _fail("L10", "; ".join(problems[:5]), "LOAD_ORPHAN_FACT")
    return _ok("L10", f"every foreign key in {len(FK_PREDICATE)} fact tables resolves")


def _l11_required(target: psycopg.Connection, handover: Handover) -> CheckResult:
    """No null in a column declared NOT NULL."""
    problems = []
    for table in REPORTING_TABLES:
        columns = [
            row[0] for row in target.execute(_NOT_NULL_SQL, (table,)).fetchall()
        ]
        if not columns:
            continue
        filters = ", ".join(f"count(*) filter (where {name} is null)" for name in columns)
        counts = target.execute(
            f"select {filters} from public.{table} where load_batch_id = %s",
            (handover.batch_id,),
        ).fetchone()
        for name, nulls in zip(columns, counts):
            if nulls:
                problems.append(f"{table}.{name}: {nulls} null(s)")
    if problems:
        return _fail("L11", "; ".join(problems[:5]), "LOAD_REQUIRED_NULL")
    return _ok("L11", "no required column holds a null")


def _l12_amounts(
    source: psycopg.Connection, target: psycopg.Connection, handover: Handover
) -> CheckResult:
    """Every reconciled money column sums to the same figure on both sides."""
    problems = []
    for table, columns in MONEY_COLUMNS.items():
        for name in columns:
            src = source.execute(
                f"select coalesce(sum({name}), 0) from public.{table} "
                "where business_date between %s and %s",
                (handover.window_start, handover.window_end),
            ).fetchone()[0]
            tgt = target.execute(
                f"select coalesce(sum({name}), 0) from public.{table} "
                "where load_batch_id = %s",
                (handover.batch_id,),
            ).fetchone()[0]
            if Decimal(str(src)) != Decimal(str(tgt)):
                problems.append(f"{table}.{name}: source {src}, warehouse {tgt}")
    if problems:
        return _fail("L12", "; ".join(problems[:5]), "LOAD_AMOUNT_MISMATCH")
    return _ok("L12", "every reconciled money column matches to the cent")


def _l13_errors(loads: dict[str, TableLoad], max_percent: int) -> CheckResult:
    """Rows the load refused, as a share of the rows received.

    Severity is warning: a small number of rejects is a day that needs a look, not a batch that must
    be thrown away (doc section 5).
    """
    received = sum(load.received for load in loads.values())
    rejected = sum(load.rejected for load in loads.values())
    if rejected == 0:
        return _ok("L13", "no row was rejected")
    share = rejected * 100 / received if received else 0
    message = f"{rejected} of {received} rows rejected ({share:.2f} %)"
    if share > max_percent:
        return _fail("L13", message + f", above the {max_percent} % limit", "LOAD_REJECT_RATE", "warning")
    return CheckResult("L13", "WARN", "warning", message + ", within tolerance")


def run_post_load_checks(
    source: psycopg.Connection,
    target: psycopg.Connection,
    handover: Handover,
    loads: dict[str, TableLoad],
) -> dict[str, CheckResult]:
    """Run L7–L13 against the open transaction. A check that raises is a failure, not a crash."""
    results: dict[str, CheckResult] = {}
    runners = (
        ("L7", lambda: _l7_reconciliation(loads)),
        ("L8", lambda: _l8_row_count(target, handover, loads)),
        ("L9", lambda: _l9_uniqueness(target, handover)),
        ("L10", lambda: _l10_referential(target, handover)),
        ("L11", lambda: _l11_required(target, handover)),
        ("L12", lambda: _l12_amounts(source, target, handover)),
        ("L13", lambda: _l13_errors(loads, 1)),
    )
    for check_id, runner in runners:
        try:
            results[check_id] = runner()
        except psycopg.Error as exc:
            results[check_id] = _fail(
                check_id, f"could not check: {exc}", "LOAD_CHECK_ERROR"
            )
    return results
