"""Re-export of the check result type (see ``psync_load.checks``)."""

from psync_load.checks import CheckResult, Severity, Status

__all__ = ["CheckResult", "Severity", "Status"]
