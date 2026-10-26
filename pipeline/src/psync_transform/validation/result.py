"""The outcome of one transformation validation check (doc section 7).

Each check answers one question about the transformed output — is it complete, is it internally
consistent, does it reconcile to its input — and reports PASS, WARN or FAIL.

Severity is fixed per check by the specification, not chosen by the result: T3 is critical, T6 is a
warning. Keeping severity next to the status means the decision rules in section 10.1 can be applied
without looking the check up again — which is exactly how Stage 1's decision engine works, so the
two stages' verdicts read alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["CheckResult", "Severity", "Status"]

Status = Literal["PASS", "WARN", "FAIL"]
Severity = Literal["critical", "warning"]


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict, ready to be recorded in ``validation_results`` (doc section 8)."""

    check_id: str
    status: Status
    severity: Severity
    message: str
    error_code: str | None = None

    @property
    def is_critical_failure(self) -> bool:
        """True when this result stops the batch (doc section 10.1)."""
        return self.status == "FAIL" and self.severity == "critical"
