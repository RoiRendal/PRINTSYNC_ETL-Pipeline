"""Transformation validation checks T1-T17 (doc section 7).

Each check answers a question about the transformed output and returns a
:class:`~psync_transform.validation.result.CheckResult`. Whether a failed check stops the batch is
decided by its severity and the rules in section 10.1, not here.

T1, T2, T3, T5, T15 and T17 are implemented; the rest arrive with the rules they verify.
"""

from psync_transform.validation.result import CheckResult, Severity, Status
from psync_transform.validation.t1 import check_input_contract
from psync_transform.validation.t2 import check_handover_counts
from psync_transform.validation.t3 import check_record_reconciliation
from psync_transform.validation.t5 import check_line_to_header_identity
from psync_transform.validation.t15 import check_version_continuity
from psync_transform.validation.t17 import check_item_identity

__all__ = [
    "CheckResult",
    "Severity",
    "Status",
    "check_handover_counts",
    "check_input_contract",
    "check_item_identity",
    "check_line_to_header_identity",
    "check_record_reconciliation",
    "check_version_continuity",
]
