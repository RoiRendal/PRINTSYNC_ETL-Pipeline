"""Extraction validation checks V1-V8 (doc section 3).

Each check answers a question about the extraction itself and returns a
:class:`~psync_extract.validation.result.CheckResult`. Whether a failed check stops the run is
decided by its severity and the rules in section 7.1, not here.
"""

from psync_extract.validation.result import CheckResult, Severity, Status
from psync_extract.validation.v1 import check_source_connection
from psync_extract.validation.v2 import check_schema_drift

__all__ = [
    "CheckResult",
    "Severity",
    "Status",
    "check_schema_drift",
    "check_source_connection",
]
