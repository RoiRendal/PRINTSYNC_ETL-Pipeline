"""Recording a batch in ``transformation_runs`` (doc sections 6.1 and 8).

One row per output table, plus one run-level row whose ``table_name`` is null. The same grain as
``pipeline_runs``, so the two stages' ledgers read alike — and the same "replace, do not accumulate"
rule: the batch's rows are deleted before they are written, so calling this twice produces one
record instead of two.

Three things are recorded that the document is specific about:

* **`records_modified` is not part of any reconciliation** (section 7). A record that was cleaned and
  kept is retained, not rejected. It is reported because "nothing changed" is the answer most nights
  and a silent zero is indistinguishable from a broken rule.
* **`rules_applied` is rows, not a jsonb blob** — ``transformation_rule_counts``, one row per rule
  per table, because a blob cannot be indexed, summed or charted.
* **`code_version`** ties a published figure to the code and the rule revision that produced it.

The caller owns the transaction: nothing commits here, so a failure leaves the record unwritten
rather than half-written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Mapping

import psycopg
from psycopg.types.json import Jsonb

from psync_transform.batch import Batch
from psync_transform.config import DEFAULT_PIPELINE_NAME, code_version
from psync_transform.decisions import APPROVED, APPROVED_WITH_WARNING, Decision
from psync_transform.validation.result import CheckResult

__all__ = ["RuleCount", "TableRecord", "record_batch"]

_SUCCESS = (APPROVED, APPROVED_WITH_WARNING)

_DELETE_COUNTS_SQL = "delete from public.transformation_rule_counts where batch_id = %s"
_DELETE_RUNS_SQL = "delete from public.transformation_runs where batch_id = %s"

_INSERT_COLUMNS = """
    run_id, batch_id, parent_run_id, pipeline_name, business_date,
    batch_window_start, batch_window_end, table_name,
    transformation_started_at, transformation_ended_at, transformation_duration_seconds,
    transformation_status, records_read, records_output, records_rejected,
    records_modified, validation_results, decision, error_code, error_message, code_version
"""

_INSERT_PLACEHOLDERS = """
    %(run_id)s, %(batch_id)s, %(parent_run_id)s, %(pipeline_name)s, %(business_date)s,
    %(start)s, %(end)s, %(table_name)s,
    %(started_at)s, %(ended_at)s, %(duration)s,
    %(status)s, %(read)s, %(output)s, %(rejected)s,
    %(modified)s, %(validation)s, %(decision)s, %(error_code)s, %(error_message)s, %(code_version)s
"""

_TABLE_ROW_SQL = f"insert into public.transformation_runs ({_INSERT_COLUMNS}) values ({_INSERT_PLACEHOLDERS})"

# The run-level row differs from the per-table row in exactly one column: `table_name` is null. It
# is written out with the same placeholders rather than derived by string replacement, so a reader
# sees both statements as they will run.
_RUN_LEVEL_ROW_SQL = f"insert into public.transformation_runs ({_INSERT_COLUMNS}) values ({_INSERT_PLACEHOLDERS})"

_RULE_COUNT_SQL = """
insert into public.transformation_rule_counts (
    batch_id, table_name, rule_id, business_date, records_affected
) values (%s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class TableRecord:
    """What one output table's build did, in the terms §8 records."""

    table: str
    records_read: int
    records_output: int
    records_rejected: int
    records_modified: int


@dataclass(frozen=True)
class RuleCount:
    """How many records one rule touched, on one table, in one batch."""

    table: str
    rule_id: str
    business_date: date
    records_affected: int


def record_batch(
    conn: psycopg.Connection,
    *,
    batch: Batch,
    tables: Iterable[TableRecord],
    checks: Mapping[str, CheckResult],
    decision: Decision,
    started_at: datetime,
    ended_at: datetime,
    rule_counts: Iterable[RuleCount] = (),
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Write one row per output table, the run-level summary and the rule counts.

    Replaces whatever the batch recorded before, so a retry rewrites its own record instead of
    appending a second one (doc section 1.2).
    """
    validation = {check_id: result.status for check_id, result in checks.items()}
    duration = int((ended_at - started_at).total_seconds())
    total_read = sum(record.records_read for record in tables)
    total_output = sum(record.records_output for record in tables)
    total_rejected = sum(record.records_rejected for record in tables)
    total_modified = sum(record.records_modified for record in tables)

    base = {
        "run_id": str(batch.parent_run_id),
        "batch_id": batch.batch_id,
        "parent_run_id": str(batch.parent_run_id),
        "pipeline_name": DEFAULT_PIPELINE_NAME,
        "business_date": batch.business_date,
        "start": batch.window_start,
        "end": batch.window_end,
        # The run-level row's value; the per-table loop overrides it with the table's name.
        "table_name": None,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration": duration,
        "status": "success" if decision.decision in _SUCCESS else "failed",
        "validation": Jsonb(validation),
        "decision": decision.decision,
        "error_code": error_code,
        "error_message": error_message or decision.reason,
        "code_version": code_version(),
    }

    conn.execute(_DELETE_COUNTS_SQL, (batch.batch_id,))
    conn.execute(_DELETE_RUNS_SQL, (batch.batch_id,))

    for record in tables:
        conn.execute(
            _TABLE_ROW_SQL,
            {
                **base,
                "table_name": record.table,
                "read": record.records_read,
                "output": record.records_output,
                "rejected": record.records_rejected,
                "modified": record.records_modified,
            },
        )

    conn.execute(
        _RUN_LEVEL_ROW_SQL,
        {
            **base,
            "read": total_read,
            "output": total_output,
            "rejected": total_rejected,
            "modified": total_modified,
        },
    )

    for count in rule_counts:
        conn.execute(
            _RULE_COUNT_SQL,
            (batch.batch_id, count.table, count.rule_id, count.business_date,
             count.records_affected),
        )
