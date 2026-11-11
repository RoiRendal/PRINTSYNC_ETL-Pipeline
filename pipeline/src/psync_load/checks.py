"""The outcome of one load check (doc sections 4 and 5).

Deliberately the same shape as Stages 1 and 2: id, status, severity, message and error code.
Severity is fixed by the specification, not chosen by a check, so the decision table in §8.1 can be
applied without looking anything up again.

It lives at the top of the package rather than inside ``validation`` so that the loader can import it
without importing the validation package, which imports the loader.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["CheckResult", "Severity", "Status"]

Status = Literal["PASS", "WARN", "FAIL"]
Severity = Literal["critical", "warning"]


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict, ready for ``load_validation_results`` (doc section 6)."""

    check_id: str
    status: Status
    severity: Severity
    message: str
    error_code: str | None = None

    @property
    def is_critical_failure(self) -> bool:
        """True when this result stops the batch (doc section 8.1)."""
        return self.status == "FAIL" and self.severity == "critical"
