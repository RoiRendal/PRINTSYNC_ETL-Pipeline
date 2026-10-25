"""The outcome of one extraction validation check (doc section 3).

Each check answers one question about the extraction itself — did we reach the source, did we get
the right rows, is the copy structurally sound — and reports PASS, WARN or FAIL.

Severity is fixed per check by the specification, not chosen by the result: V8 is a warning, the
other checks are critical. Keeping severity next to the result means the decision rules in
section 7.1 can be applied without looking the check up again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["CheckResult", "Severity", "Status"]

Status = Literal["PASS", "WARN", "FAIL"]
Severity = Literal["critical", "warning"]


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict, ready to be recorded in ``validation_results`` (doc section 4)."""

    check_id: str
    status: Status
    severity: Severity
    message: str
    error_code: str | None = None

    @property
    def is_critical_failure(self) -> bool:
        """True when this result stops the run (doc section 7.1)."""
        return self.status == "FAIL" and self.severity == "critical"
