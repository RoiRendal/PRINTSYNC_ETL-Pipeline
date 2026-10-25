"""V3 — the business date is processable, and has not already been processed (doc section 3).

Two rules, and they lead to different outcomes:

* a date that is **not in the past** cannot be extracted — that is a critical failure;
* a ``run_key`` that already **completed** is not an error at all. Section 7.1 turns it into
  SKIPPED: the day is done, there is nothing to redo, and running twice stays harmless by design
  (P7). Reporting it as a failure would train everyone to ignore the alert.

So this check returns a :class:`RunResolution`, which carries the verdict *and* whether the run
should stop quietly. V1 and V2 answer "is it safe to continue?"; V3 also answers "is there any
point?".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg

from psync_extract.config import Settings
from psync_extract.db.target import connect_target
from psync_extract.validation.result import CheckResult

__all__ = ["RunResolution", "build_run_key", "check_window_resolution"]


def build_run_key(pipeline_name: str, business_date: date) -> str:
    """The key that makes a re-run safe: one successful run per business date (doc section 4)."""
    return f"{pipeline_name}:{business_date.isoformat()}"


@dataclass(frozen=True)
class RunResolution:
    """V3's answer: proceed, skip, or stop."""

    run_key: str
    business_date: date
    result: CheckResult
    already_completed: bool

    @property
    def decision(self) -> str:
        """What the caller should do with this resolution."""
        if self.result.status == "FAIL":
            return "STOP"
        return "SKIP" if self.already_completed else "PROCEED"


def check_window_resolution(
    settings: Settings,
    business_date: date,
    *,
    time_zone: str | None = None,
) -> RunResolution:
    """Confirm the date is in the past and its ``run_key`` has not already completed.

    ``time_zone`` is the zone the shop actually runs in — the one V4 reads from
    ``business_settings``. It defaults to the configured zone so the check still works before V4
    has run, but the caller should pass the resolved value: the shop's zone, not the config
    default, decides what "today" is.
    """
    run_key = build_run_key(settings.pipeline_name, business_date)
    zone = time_zone or settings.run_timezone
    today = datetime.now(ZoneInfo(zone)).date()

    if business_date >= today:
        return RunResolution(
            run_key=run_key,
            business_date=business_date,
            already_completed=False,
            result=CheckResult(
                check_id="V3",
                status="FAIL",
                severity="critical",
                message=(
                    f"business_date {business_date.isoformat()} is not in the past "
                    f"(today is {today.isoformat()} in {zone}); "
                    "only a completed day can be extracted"
                ),
                error_code="RUN_DATE_INVALID",
            ),
        )

    try:
        with connect_target(settings) as conn:
            row = conn.execute(
                """
                select extraction_status
                from pipeline_runs
                where run_key = %s and table_name is null
                order by extraction_started_at desc nulls last
                limit 1
                """,
                (run_key,),
            ).fetchone()
    except psycopg.Error as exc:
        return RunResolution(
            run_key=run_key,
            business_date=business_date,
            already_completed=False,
            result=CheckResult(
                check_id="V3",
                status="FAIL",
                severity="critical",
                message=f"could not read pipeline_runs for {run_key}: {exc}",
                error_code="TGT_QUERY_FAILED",
            ),
        )

    already_completed = row is not None and row[0] == "success"
    message = (
        f"{run_key} already completed on {business_date.isoformat()}; the run will be skipped"
        if already_completed
        else f"{run_key} has not been processed; {business_date.isoformat()} is ready to extract"
    )

    return RunResolution(
        run_key=run_key,
        business_date=business_date,
        already_completed=already_completed,
        result=CheckResult(
            check_id="V3",
            status="PASS",
            severity="critical",
            message=message,
        ),
    )
