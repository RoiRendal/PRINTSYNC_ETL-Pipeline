"""The pre-load validation checks (doc section 4).

L1–L6 run before the target transaction opens. All six are critical: a failure stops the batch with
no writes. Every check is a pure read — none of them changes either database.

Each one returns a CheckResult with a measurable criterion, so the outcome can be recorded in
load_validation_results (batch 5) and read in the log without a second lookup.
"""

from __future__ import annotations

import shutil
from typing import Callable

import psycopg

from psync_load.config import Settings
from psync_load.db import connect_source, connect_warehouse
from psync_load.handover import FACT_TABLES, REPORTING_TABLES, Handover
from psync_load.validation.result import CheckResult

__all__ = ["run_pre_load_checks"]

BOOKKEEPING_TABLES = ("load_runs", "load_rejects", "load_validation_results")
LOAD_COLUMNS = frozenset({"load_batch_id", "load_run_id", "loaded_at"})

_COLUMNS_SQL = """
    select column_name, data_type
    from information_schema.columns
    where table_schema = 'public' and table_name = %s
"""


def _ok(check_id: str, message: str) -> CheckResult:
    return CheckResult(check_id, "PASS", "critical", message)


def _fail(check_id: str, message: str, error_code: str) -> CheckResult:
    return CheckResult(check_id, "FAIL", "critical", message, error_code)


def _l1_connection(settings: Settings, handover: Handover) -> CheckResult:
    """Target connection and write permission."""
    try:
        with connect_warehouse(settings) as conn:
            # SET does not accept a bind parameter; the value is an int from validated settings,
            # so formatting it cannot carry anything but a number.
            conn.execute(f"set local lock_timeout = {int(settings.lock_timeout_seconds) * 1000}")
            tables = REPORTING_TABLES + BOOKKEEPING_TABLES
            problems = []
            for table in tables:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    allowed = conn.execute(
                        "select has_table_privilege(%s, %s)",
                        (f"public.{table}", privilege),
                    ).fetchone()[0]
                    if not allowed:
                        problems.append(f"{table}:{privilege}")
    except psycopg.Error as exc:
        return _fail("L1", f"target connection failed: {exc}", "LOAD_TARGET_UNREACHABLE")

    if problems:
        return _fail(
            "L1",
            "missing privileges: " + ", ".join(problems[:8]),
            "LOAD_TARGET_PERMISSION",
        )
    return _ok("L1", f"connection and write permission on {len(tables)} tables verified")


def _l2_schema(settings: Settings, handover: Handover) -> CheckResult:
    """Schema match: the warehouse mirrors Stage 2, plus the three load columns.

    Compared against the live information_schema on both databases rather than a hardcoded
    registry, so a second list cannot drift from migration 005.
    """
    problems: list[str] = []
    try:
        with connect_source(settings) as source, connect_warehouse(settings) as target:
            for table in REPORTING_TABLES:
                src = dict(source.execute(_COLUMNS_SQL, (table,)).fetchall())
                tgt = dict(target.execute(_COLUMNS_SQL, (table,)).fetchall())
                if not src:
                    problems.append(f"{table}: absent from the source")
                    continue
                missing = sorted(set(src) - set(tgt))
                if missing:
                    problems.append(f"{table}: missing {', '.join(missing[:4])}")
                mismatched = [
                    f"{name} ({src[name]} -> {tgt[name]})"
                    for name in sorted(set(src) & set(tgt))
                    if src[name] != tgt[name]
                ]
                if mismatched:
                    problems.append(f"{table}: retyped {', '.join(mismatched[:3])}")
                absent_load = sorted(LOAD_COLUMNS - set(tgt))
                if absent_load:
                    problems.append(f"{table}: no {', '.join(absent_load)}")
    except psycopg.Error as exc:
        return _fail("L2", f"could not compare schemas: {exc}", "LOAD_SCHEMA_UNREADABLE")

    if problems:
        return _fail("L2", "; ".join(problems[:5]), "LOAD_SCHEMA_MISMATCH")
    return _ok("L2", f"all {len(REPORTING_TABLES)} tables match, with the load columns present")


def _l3_status(settings: Settings, handover: Handover) -> CheckResult:
    """Handover status: only an approved, successful batch may be loaded."""
    if handover.status != "success" or handover.decision not in (
        "APPROVED",
        "APPROVED WITH WARNING",
    ):
        return _fail(
            "L3",
            f"batch {handover.batch_id}: status={handover.status}, "
            f"decision={handover.decision}; only a successful APPROVED batch may be loaded",
            "LOAD_HANDOVER_NOT_APPROVED",
        )
    return _ok("L3", f"{handover.batch_id}: {handover.decision} / {handover.status}")


def _l4_counts(settings: Settings, handover: Handover) -> CheckResult:
    """The facts' input counts still match the handover metadata.

    Only the facts are compared. A fact's ``records_output`` is exactly the rows written for the
    window, so the source must still hold that many. A dimension is loaded whole, and its
    ``records_output`` counts only what that run inserted — 0 for ``dim_date`` on a re-run, absent
    for the seeded ``dim_order_status`` — so comparing it would fail on a batch that is perfectly
    loadable. Dimensions are reconciled after the load instead (L8).
    """
    problems: list[str] = []
    checked = 0
    try:
        with connect_source(settings) as conn:
            for table in sorted(FACT_TABLES):
                actual = conn.execute(
                    f"select count(*) from public.{table} "
                    "where business_date between %s and %s",
                    (handover.window_start, handover.window_end),
                ).fetchone()[0]
                expected = handover.expected_rows(table)
                checked += 1
                if actual != expected:
                    problems.append(f"{table}: {actual} present, {expected} in the handover")
    except psycopg.Error as exc:
        return _fail("L4", f"could not count the input: {exc}", "LOAD_COUNTS_UNREADABLE")

    if problems:
        return _fail("L4", "; ".join(problems[:5]), "LOAD_COUNT_MISMATCH")
    total = sum(handover.counts.get(table, 0) for table in FACT_TABLES)
    return _ok("L4", f"{total} fact rows in the window match the handover")


def _l5_storage(settings: Settings, handover: Handover) -> CheckResult:
    """Sufficient free space for the load and its snapshot."""
    minimum = 100 * 1024 * 1024
    try:
        free = shutil.disk_usage(settings.psync_data_dir).free
        with connect_source(settings) as conn:
            source_size = 0
            for table in REPORTING_TABLES:
                source_size += conn.execute(
                    "select pg_total_relation_size(%s::regclass)",
                    (f"public.{table}",),
                ).fetchone()[0]
    except (OSError, psycopg.Error) as exc:
        return _fail("L5", f"could not measure storage: {exc}", "LOAD_STORAGE_UNREADABLE")

    required = max(minimum, 3 * source_size)
    if free < required:
        return _fail(
            "L5",
            f"{free // (1024 * 1024)} MB free, {required // (1024 * 1024)} MB required",
            "LOAD_STORAGE_LOW",
        )
    return _ok(
        "L5",
        f"{free // (1024 * 1024)} MB free, {required // (1024 * 1024)} MB required",
    )


def _l6_duplicate(settings: Settings, handover: Handover) -> CheckResult:
    """The batch has not already been published successfully."""
    try:
        with connect_warehouse(settings) as conn:
            already = conn.execute(
                "select count(*) from public.load_runs "
                "where batch_id = %s and table_name is null and load_status = 'success'",
                (handover.batch_id,),
            ).fetchone()[0]
    except psycopg.Error as exc:
        return _fail("L6", f"could not check for a prior load: {exc}", "LOAD_LEDGER_UNREADABLE")

    if already:
        return _fail(
            "L6",
            f"{handover.batch_id} was already loaded successfully; refusing to publish twice",
            "LOAD_DUPLICATE_BATCH",
        )
    return _ok("L6", "no prior successful load for this batch")


_CHECKS: tuple[tuple[str, Callable[[Settings, Handover], CheckResult]], ...] = (
    ("L1", _l1_connection),
    ("L2", _l2_schema),
    ("L3", _l3_status),
    ("L4", _l4_counts),
    ("L5", _l5_storage),
    ("L6", _l6_duplicate),
)


def run_pre_load_checks(settings: Settings, handover: Handover) -> dict[str, CheckResult]:
    """Run L1–L6 in id order. A check that raises is itself a failure, not a crash."""
    results: dict[str, CheckResult] = {}
    for check_id, check in _CHECKS:
        try:
            results[check_id] = check(settings, handover)
        except Exception as exc:  # noqa: BLE001 - a check must never abort the other five
            results[check_id] = _fail(
                check_id, f"check raised {type(exc).__name__}: {exc}", "LOAD_CHECK_ERROR"
            )
    return results
