"""The load decision (doc section 8.1).

The verdict is derived from the checks, never chosen: severity decides what a failure means, so two
runs with the same results cannot reach different verdicts. The four outcomes map to the two actions
the pipeline can take — publish, or roll back.
"""

from __future__ import annotations

from dataclasses import dataclass

from psync_load.checks import CheckResult

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


@dataclass(frozen=True)
class Decision:
    """One batch's verdict, with the reason a reader can act on."""

    verdict: str
    reason: str

    @property
    def publishes(self) -> bool:
        """True when the reporting tables may keep the rows this batch wrote."""
        return self.verdict in (APPROVED, APPROVED_WITH_WARNING)


def _ids(results: list[CheckResult]) -> str:
    return ", ".join(sorted(result.check_id for result in results))


def decide(checks: dict[str, CheckResult]) -> Decision:
    """Turn the check results into one verdict (doc section 8.1)."""
    critical = [result for result in checks.values() if result.is_critical_failure]
    if critical:
        return Decision(REJECTED, f"critical checks failed: {_ids(critical)}")

    # A warning-severity failure is beyond tolerance but not fatal: a human looks before anything
    # reads the warehouse, and the batch is held rather than published (doc section 8.1).
    beyond = [
        result
        for result in checks.values()
        if result.status == "FAIL" and result.severity == "warning"
    ]
    if beyond:
        return Decision(MANUAL_REVIEW, f"warnings beyond tolerance: {_ids(beyond)}")

    warnings = [result for result in checks.values() if result.status == "WARN"]
    if warnings:
        return Decision(
            APPROVED_WITH_WARNING, f"handed over with warnings: {_ids(warnings)}"
        )

    return Decision(APPROVED, "all critical checks passed with no warnings")
