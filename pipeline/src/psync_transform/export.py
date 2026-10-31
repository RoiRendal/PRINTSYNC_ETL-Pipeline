"""Exporting a batch's quarantine as evidence (doc section 9).

The quarantine lives in ``quarantine_rows``, and that table is the record. This module renders it
into a folder a reader can open without a database client: two CSVs, the batch's reconciliation, and
a README that explains the other three.

Three rules shape it:

* **Nothing is recomputed.** Every number comes from ``transformation_runs`` and ``quarantine_rows``
  — what the batch recorded, not a second derivation from staging. The batch already decided; asking
  the question twice would be a second opinion nobody asked for, and it could disagree.
* **An export is not a run.** It writes no ledger row and no log. Recording it would put a row in
  ``transformation_runs`` for work the pipeline did not do.
* **Two exports of one batch are byte-identical.** Row order is fixed, the summary is ordered by
  count, and no file carries the moment of export — the only timestamps are the rows' own
  ``quarantined_at``. A file that could differ between two exports would be a second version of the
  truth; one that cannot is a rendering.

Identifiers, rule ids, counts and amounts only: the payload is the rejected staging row, which
carries no customer data because Stage 1 never extracts any (doc section 9).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import psycopg

from psync_transform.decisions import REJECT_RATE_LIMIT_PERCENT

__all__ = ["ExportError", "ExportResult", "export_batch"]

# Written before the CSV body so Excel opens the file without an import dialog. It is a BOM, not
# content: a second export writes the same bytes.
BOM = b"\xef\xbb\xbf"

QUARANTINE_CSV = "quarantine.csv"
SUMMARY_CSV = "quarantine_summary.csv"
RECONCILIATION_JSON = "_reconciliation.json"
README_TXT = "README.txt"

# Fixed row order, so two exports of the same batch are byte-identical. The payload is last: a
# reader wants the explanation before the rejected row itself.
_QUARANTINE_SQL = """
    copy (
        select source_table, source_id, rule_id, reason, detail,
               business_date, parent_run_id, quarantined_at, payload
        from public.quarantine_rows
        where batch_id = %s
        order by source_table, source_id, rule_id
    ) to stdout (format csv, header true)
"""

# The first file a reader opens: how many rows each rule caught. Ordered by count so the rule that
# matters is at the top.
_SUMMARY_SQL = """
    copy (
        select source_table, rule_id, reason, count(*) as records
        from public.quarantine_rows
        where batch_id = %s
        group by source_table, rule_id, reason
        order by count(*) desc, rule_id
    ) to stdout (format csv, header true)
"""

_RUN_SQL = """
    select business_date, parent_run_id, decision, transformation_status,
           batch_window_start, batch_window_end, code_version,
           records_read, records_output, records_rejected, records_modified,
           validation_results
    from public.transformation_runs
    where batch_id = %s and table_name is null
"""

_TABLES_SQL = """
    select table_name, records_read, records_output, records_rejected, records_modified
    from public.transformation_runs
    where batch_id = %s and table_name is not null
    order by table_name
"""


class ExportError(RuntimeError):
    """The batch cannot be exported as asked."""


@dataclass(frozen=True)
class ExportResult:
    """What a caller needs to know afterwards."""

    directory: Path
    rows: int
    rules: int


def export_batch(
    conn: psycopg.Connection,
    batch_id: str,
    directory: Path | str,
) -> ExportResult:
    """Write one batch's quarantine evidence into ``<directory>/<batch_id>/``.

    Written into a temporary directory and moved into place, so an interrupted export never leaves a
    folder that looks complete.
    """
    run = _run_row(conn, batch_id)
    tables = _table_rows(conn, batch_id)
    summary = _summary_rows(conn, batch_id)

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / batch_id
    staging = directory / f".staging_{batch_id}"

    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    try:
        _write_csv(conn, staging / QUARANTINE_CSV, _QUARANTINE_SQL, batch_id)
        _write_csv(conn, staging / SUMMARY_CSV, _SUMMARY_SQL, batch_id)

        reconciliation = _reconciliation(batch_id, run, tables, summary)
        (staging / RECONCILIATION_JSON).write_text(
            json.dumps(reconciliation, indent=2) + "\n", encoding="utf-8"
        )
        (staging / README_TXT).write_text(
            _readme(batch_id, run, reconciliation), encoding="utf-8"
        )

        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return ExportResult(
        directory=target,
        rows=sum(row["records"] for row in summary),
        rules=len({(row["source_table"], row["rule_id"]) for row in summary}),
    )


def _write_csv(
    conn: psycopg.Connection,
    path: Path,
    statement: str,
    batch_id: str,
) -> None:
    """COPY a query straight to disk, as UTF-8 with a BOM.

    Written in binary because ``COPY`` hands back bytes: decoding and re-encoding would risk changing
    a cell, and the point of this file is that it is the row, unchanged.
    """
    with path.open("wb") as handle:
        handle.write(BOM)
        with conn.cursor() as cursor, cursor.copy(statement, (batch_id,)) as copy:
            for chunk in copy:
                handle.write(chunk)


def _run_row(conn: psycopg.Connection, batch_id: str) -> dict[str, Any]:
    """The batch's run-level row, or a failure that names the id."""
    row = conn.execute(_RUN_SQL, (batch_id,)).fetchone()
    if row is None:
        raise ExportError(
            f"no batch {batch_id!r} in transformation_runs. An export renders a batch that already "
            "ran; it cannot produce one, and an empty folder would look like a batch with nothing "
            "to reject."
        )
    (
        business_date,
        parent_run_id,
        decision,
        status,
        window_start,
        window_end,
        code_version,
        records_read,
        records_output,
        records_rejected,
        records_modified,
        validation_results,
    ) = row
    return {
        "business_date": business_date,
        "parent_run_id": str(parent_run_id),
        "decision": decision,
        "status": status,
        "window_start": window_start,
        "window_end": window_end,
        "code_version": code_version,
        "records_read": records_read,
        "records_output": records_output,
        "records_rejected": records_rejected,
        "records_modified": records_modified,
        "validation_results": validation_results or {},
    }


def _table_rows(conn: psycopg.Connection, batch_id: str) -> list[dict[str, Any]]:
    """The per-output-table rows, which carry the grain each table was written at."""
    return [
        {
            "table": table,
            "records_read": read,
            "records_output": output,
            "records_rejected": rejected,
            "records_modified": modified,
        }
        for table, read, output, rejected, modified in conn.execute(
            _TABLES_SQL, (batch_id,)
        ).fetchall()
    ]


def _summary_rows(conn: psycopg.Connection, batch_id: str) -> list[dict[str, Any]]:
    """How many records each rule caught, biggest first — the same order as the summary CSV."""
    return [
        {
            "source_table": source_table,
            "rule_id": rule_id,
            "reason": reason,
            "records": records,
        }
        for source_table, rule_id, reason, records in conn.execute(
            "select source_table, rule_id, reason, count(*) "
            "from public.quarantine_rows where batch_id = %s "
            "group by source_table, rule_id, reason "
            "order by count(*) desc, rule_id",
            (batch_id,),
        ).fetchall()
    ]


def _reconciliation(
    batch_id: str,
    run: dict[str, Any],
    tables: Sequence[dict[str, Any]],
    summary: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """The batch's arithmetic as recorded, with T3's verdict quoted rather than re-derived.

    The identity T3 proves is ``records_read = records_retained + records_quarantined``, **per source
    table** — and ``records_retained`` is not a stored column, while ``records_output`` is the rows
    written to an output table, which is a different grain from the source rows a fact was built
    from (twelve sales become one daily row). So ``read = output + rejected`` is not an identity here
    and asserting it would fail on every fact. What this file does instead is report what the batch
    recorded, quote the check that actually reconciled it, and show the threshold arithmetic.
    """
    read = run["records_read"]
    rejected = run["records_rejected"]
    rate = (rejected * 100 / read) if read else 0.0
    within_limit = not (read and rejected * 100 > read * REJECT_RATE_LIMIT_PERCENT)

    t3 = run["validation_results"].get("T3")

    return {
        "batch_id": batch_id,
        "business_date": run["business_date"].isoformat(),
        "parent_run_id": run["parent_run_id"],
        "window": {
            "start": run["window_start"].isoformat(),
            "end": run["window_end"].isoformat(),
        },
        "decision": run["decision"],
        "status": run["status"],
        "code_version": run["code_version"],
        "totals": {
            "records_read": read,
            "records_output": run["records_output"],
            "records_rejected": rejected,
            "records_modified": run["records_modified"],
        },
        "reconciliation": {
            "check": "T3",
            "recorded_status": t3,
            "identity": "records_read = records_retained + records_quarantined, per source table",
            "note": (
                "Quoted from the batch's recorded validation results, not re-derived here. "
                "records_retained is not a stored column and records_output is a different grain "
                "from records_read for the fact tables, so read = output + rejected is not an "
                "identity this export can assert."
            ),
        },
        "quarantine": {
            "records_rejected": rejected,
            "records_read": read,
            "rate_percent": round(rate, 4),
            "limit_percent": REJECT_RATE_LIMIT_PERCENT,
            "within_limit": within_limit,
            "rules": [
                {
                    "source_table": row["source_table"],
                    "rule_id": row["rule_id"],
                    "reason": row["reason"],
                    "records": row["records"],
                }
                for row in summary
            ],
        },
        "tables": list(tables),
        "notes": [
            "records_modified is reported but is outside every reconciliation: a record that was "
            "cleaned and kept is retained, not rejected (doc section 7).",
            "No row here was recomputed from staging. The batch's own record is the source.",
        ],
    }


def _readme(
    batch_id: str,
    run: dict[str, Any],
    reconciliation: dict[str, Any],
) -> str:
    """The folder's own explanation, for a reader who was not there.

    Deliberately carries no export timestamp: the file has to be reproducible, and the only
    timestamps in this folder are the rows' own ``quarantined_at``.
    """
    quarantine = reconciliation["quarantine"]
    rate = quarantine["rate_percent"]
    limit = quarantine["limit_percent"]
    verdict = "within" if quarantine["within_limit"] else "above"

    lines = [
        "psync_analytics - quarantine export",
        "===================================",
        "",
        f"batch          {batch_id}",
        f"parent run     {run['parent_run_id']}",
        f"business day   {run['business_date'].isoformat()}",
        f"window         {run['window_start'].isoformat()} to {run['window_end'].isoformat()}",
        f"decision       {run['decision']}",
        f"status         {run['status']}",
        f"code version   {run['code_version']}",
        "",
        "Files",
        "-----",
        f"{QUARANTINE_CSV:<24} One row per rejected record, ordered by table, id and rule.",
        f"{SUMMARY_CSV:<24} Counts per source table and rule - read this one first.",
        f"{RECONCILIATION_JSON:<24} The batch's recorded counts, T3's verdict, the threshold arithmetic.",
        f"{README_TXT:<24} This file.",
        "",
        "Quarantine",
        "----------",
        f"{quarantine['records_rejected']} of {quarantine['records_read']} rows rejected "
        f"({rate:.2f} %), {verdict} the {limit} % limit in section 10.1.",
        f"The batch's decision was {run['decision']}.",
        "",
        "What this folder is",
        "-------------------",
        "A rendering of public.quarantine_rows and public.transformation_runs for one batch.",
        "It is not a second source of truth: delete it and nothing is lost, because the rows",
        "remain in the database, and exporting the same batch again reproduces these files",
        "byte for byte.",
    ]
    return "\n".join(lines) + "\n"
