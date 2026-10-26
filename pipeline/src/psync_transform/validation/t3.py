"""T3 — record reconciliation (doc section 7).

For every source table the batch read:

```
records_read  =  records_retained  +  records_quarantined
```

What this check is really for is the **reporting**, not the arithmetic. The batch's own numbers —
what it read, what it rejected — are what the run record carries and what the reject-rate threshold
in section 10.1 is applied to. If the build silently skipped a table, or quarantined a row without
recording it, every downstream decision would be made on a figure that was never true.

So the check does not trust the report: it recounts the staging rows and the quarantine rows itself
and compares. A table that carries quarantined rows but was never reported is a failure too — that
is a quarantine nobody accounted for.

Note what this check does **not** do: prove that a retained record reached a measure. That is the
business of T5 and T12, which reconcile amounts rather than rows. A voided sale is retained and
counted; it simply feeds `voided_count` rather than revenue.
"""

from __future__ import annotations

from typing import Mapping

import psycopg

from psync_transform.batch import Batch
from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.facts import SourceCounts
from psync_transform.schema import STAGING_TABLES
from psync_transform.validation.result import CheckResult

__all__ = ["check_record_reconciliation"]


def check_record_reconciliation(
    settings: Settings,
    batch: Batch,
    counts: Mapping[str, SourceCounts],
) -> CheckResult:
    """Every staged row was either retained or quarantined, and the report says so."""
    problems: list[str] = []
    checked = 0

    try:
        with connect_target(settings) as conn:
            for source_table, staging in STAGING_TABLES.items():
                live_read = conn.execute(
                    f"select count(*) from public.{staging} where run_id = %s",
                    (batch.parent_run_id,),
                ).fetchone()[0]
                live_quarantined = conn.execute(
                    "select count(*) from public.quarantine_rows "
                    "where batch_id = %s and source_table = %s",
                    (batch.batch_id, source_table),
                ).fetchone()[0]

                reported = counts.get(source_table)
                if reported is None:
                    if live_quarantined:
                        problems.append(
                            f"{source_table}: {live_quarantined} row(s) quarantined but the table "
                            "was never reported"
                        )
                    continue

                checked += 1
                if reported.read != live_read:
                    problems.append(
                        f"{source_table}: reported {reported.read} rows read, staging holds "
                        f"{live_read}"
                    )
                if reported.quarantined != live_quarantined:
                    problems.append(
                        f"{source_table}: reported {reported.quarantined} quarantined, "
                        f"{live_quarantined} are recorded"
                    )
                if reported.read != reported.retained + reported.quarantined:
                    problems.append(
                        f"{source_table}: {reported.read} read but "
                        f"{reported.retained} retained + {reported.quarantined} quarantined"
                    )
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T3",
            status="FAIL",
            severity="critical",
            message=f"could not reconcile the record counts: {exc}",
            error_code="TRF_RECONCILIATION_UNREADABLE",
        )

    if problems:
        return CheckResult(
            check_id="T3",
            status="FAIL",
            severity="critical",
            message="records do not reconcile: " + "; ".join(problems[:6]),
            error_code="TRF_RECORD_RECONCILIATION",
        )

    return CheckResult(
        check_id="T3",
        status="PASS",
        severity="critical",
        message=(
            f"{checked} source table(s) reconcile: every staged row is retained or quarantined, "
            "and the quarantine holds what the batch says it rejected"
        ),
    )
