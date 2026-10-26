"""The batch's verdict (doc section 10.1).

The order of the rules matters as much as the rules. A rejected batch and a manual review look
similar in a log; they are different days in an operator's morning. Precedence, from the document:

1. **a critical check failed → REJECTED.** Stop, clear the affected dates, and re-run after fixing.
2. **the quarantine exceeds 1 % of what was read → MANUAL REVIEW.** At this volume that is not a
   data-quality signal, it is a rule that stopped matching — and a human looks before it becomes a
   number nobody questions.
3. **warnings → APPROVED WITH WARNING.** The day is published and flagged for review within one
   business day.
4. **otherwise → APPROVED**, automatically.

A non-critical check that FAILs is treated as a warning, exactly as Stage 1's decision engine treats
it: the day is published and the shop is told. And the threshold is fixed in advance (section 10.1),
so it cannot be chosen to fit a result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from psync_transform.validation.result import CheckResult

__all__ = [
    "APPROVED",
    "APPROVED_WITH_WARNING",
    "MANUAL_REVIEW",
    "REJECTED",
    "Decision",
    "decide",
]

APPROVED = "APPROVED"
APPROVED_WITH_WARNING = "APPROVED WITH WARNING"
MANUAL_REVIEW = "MANUAL REVIEW"
REJECTED = "REJECTED"

# Section 10.1, fixed in advance: at ~28 sale lines a batch, 1 % is a fraction of a line, so in
# practice any quarantine holds the batch for review. That is the honest reading of the threshold at
# this size — a single rejected line is a rule that stopped matching.
REJECT_RATE_LIMIT_PERCENT = 1


@dataclass(frozen=True)
class Decision:
    """The verdict, and why it was reached."""

    decision: str
    reason: str


def decide(
    results: Mapping[str, CheckResult],
    *,
    records_read: int,
    records_quarantined: int,
) -> Decision:
    """Apply section 10.1's table, in precedence order."""
    critical = sorted(
        result.check_id for result in results.values() if result.is_critical_failure
    )
    if critical:
        return Decision(
            REJECTED, f"critical checks failed: {', '.join(critical)}"
        )

    if records_read and records_quarantined * 100 > records_read * REJECT_RATE_LIMIT_PERCENT:
        return Decision(
            MANUAL_REVIEW,
            f"{records_quarantined} of {records_read} rows quarantined, "
            f"above the {REJECT_RATE_LIMIT_PERCENT}% limit",
        )

    warnings = sorted(
        result.check_id
        for result in results.values()
        if result.status == "WARN"
        or (result.status == "FAIL" and result.severity == "warning")
    )
    if warnings:
        return Decision(
            APPROVED_WITH_WARNING,
            f"handed over with warnings: {', '.join(warnings)}",
        )

    return Decision(APPROVED, "all critical checks passed with no warnings")
