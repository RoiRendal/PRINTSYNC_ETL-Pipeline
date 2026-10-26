"""Transformation validation checks T1-T17 (doc section 7).

Each check answers a question about the transformed output and returns a
:class:`~psync_transform.validation.result.CheckResult`. Whether a failed check stops the batch is
decided by its severity and the rules in section 10.1, not here.

All seventeen are implemented, in three modules grouped by what they look at:

* :mod:`t_boundary` — T6, T13, T14: the batch's dates, and whether what it wrote is worth reading.
* :mod:`t_integrity` — T7, T8, T9: the structure of the published output.
* :mod:`t_money` — T4, T10, T11: the money and its coverage.
* :mod:`t1`, `t2`, `t3`, `t5`, `t12`, `t15`, `t16`, `t17` — one module each, matching Stage 1's
  one-check-per-module layout.
"""

from psync_transform.validation.result import CheckResult, Severity, Status
from psync_transform.validation.t1 import check_input_contract
from psync_transform.validation.t2 import check_handover_counts
from psync_transform.validation.t3 import check_record_reconciliation
from psync_transform.validation.t5 import check_line_to_header_identity
from psync_transform.validation.t12 import check_fact_reconciliation
from psync_transform.validation.t15 import check_version_continuity
from psync_transform.validation.t16 import check_status_domain
from psync_transform.validation.t17 import check_item_identity
from psync_transform.validation.t_boundary import (
    check_business_date_boundary,
    check_non_empty_output,
    check_vat_conformance,
)
from psync_transform.validation.t_integrity import (
    check_key_uniqueness,
    check_referential_integrity,
    check_required_columns,
)
from psync_transform.validation.t_money import (
    check_business_rules,
    check_cost_coverage,
    check_internal_money_arithmetic,
)

__all__ = [
    "CheckResult",
    "Severity",
    "Status",
    "check_business_date_boundary",
    "check_business_rules",
    "check_cost_coverage",
    "check_fact_reconciliation",
    "check_handover_counts",
    "check_input_contract",
    "check_internal_money_arithmetic",
    "check_item_identity",
    "check_key_uniqueness",
    "check_line_to_header_identity",
    "check_non_empty_output",
    "check_referential_integrity",
    "check_record_reconciliation",
    "check_required_columns",
    "check_status_domain",
    "check_version_continuity",
    "check_vat_conformance",
]
