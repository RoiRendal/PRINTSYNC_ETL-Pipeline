"""The run's decision (doc section 7.1).

Eight check results arrive separately; this turns them into one verdict and says whether the data
may be handed on. The order of the rules matters as much as the rules themselves — a day that is
already done should be skipped before anyone asks whether the source was reachable, and an
unreachable source is a RETRY rather than a REJECTED, because the data was never the problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from psync_extract.validation.result import CheckResult

__all__ = [
    "APPROVED",
    "APPROVED_WITH_WARNING",
    "MANUAL_REVIEW",
    "REJECTED",
    "RETRY",
    "SKIPPED",
    "Decision",
    "decide",
    "status_for",
]

APPROVED = "APPROVED"
APPROVED_WITH_WARNING = "APPROVED WITH WARNING"
REJECTED = "REJECTED"
RETRY = "RETRY"
SKIPPED = "SKIPPED"
MANUAL_REVIEW = "MANUAL REVIEW"

# Doc section 7.1: a rejection rate above one percent means the source changed, not that the
# data is merely messy, so the run is held rather than published.
REJECT_RATE_LIMIT_PERCENT = 1

# pipeline_runs.extraction_status only allows these four values.
_STATUS_BY_DECISION = {
    APPROVED: "success",
    APPROVED_WITH_WARNING: "success",
    REJECTED: "failed",
    RETRY: "failed",
    MANUAL_REVIEW: "failed",
    SKIPPED: "skipped",
}


@dataclass(frozen=True)
class Decision:
    """The verdict, why it was reached, and whether the data may be handed over."""

    decision: str
    reason: str

    @property
    def handover(self) -> bool:
        return self.decision in (APPROVED, APPROVED_WITH_WARNING)

    @property
    def retry(self) -> bool:
        return self.decision == RETRY


def status_for(decision: str) -> str:
    """Map a decision onto the four statuses ``pipeline_runs`` permits."""
    return _STATUS_BY_DECISION[decision]


def decide(
    results: Mapping[str, CheckResult],
    *,
    rows_read: int = 0,
    rows_rejected: int = 0,
    already_completed: bool = False,
) -> Decision:
    """Apply section 7.1's table, in precedence order."""
    if already_completed:
        return Decision(SKIPPED, "run_key already completed; the day is done")

    critical_failures = [
        r for r in results.values() if r.status == "FAIL" and r.severity == "critical"
    ]
    warnings = [
        r
        for r in results.values()
        if r.status == "WARN" or (r.status == "FAIL" and r.severity == "warning")
    ]

    source = results.get("V1")
    if source is not None and source.status == "FAIL":
        return Decision(
            RETRY,
            f"source unreachable ({source.error_code}); retry before rejecting the day",
        )

    if critical_failures:
        named = ", ".join(sorted(r.check_id for r in critical_failures))
        return Decision(REJECTED, f"critical checks failed: {named}")

    if rows_read and rows_rejected * 100 > rows_read * REJECT_RATE_LIMIT_PERCENT:
        return Decision(
            MANUAL_REVIEW,
            f"{rows_rejected} of {rows_read} rows rejected, above the 1% limit",
        )

    if warnings:
        named = ", ".join(sorted(r.check_id for r in warnings))
        return Decision(
            APPROVED_WITH_WARNING, f"handed over with warnings: {named}"
        )

    return Decision(APPROVED, "all critical checks passed with no warnings")
