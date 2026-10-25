"""Extraction validation checks V1-V8 (doc section 3).

Each check answers a question about the extraction itself and returns a
:class:`~psync_extract.validation.result.CheckResult`. Whether a failed check stops the run is
decided by its severity and the rules in section 7.1, not here.
"""

from psync_extract.validation.result import CheckResult, Severity, Status
from psync_extract.validation.v1 import check_source_connection
from psync_extract.validation.v2 import check_schema_drift
from psync_extract.validation.v3 import RunResolution, check_window_resolution
from psync_extract.validation.v4 import (
    SettingsResolution,
    ShopSettings,
    check_shop_settings,
)
from psync_extract.validation.v5 import check_identifiers
from psync_extract.validation.v6 import check_primary_key_uniqueness
from psync_extract.validation.v7 import check_row_parity
from psync_extract.validation.v8 import check_non_empty

__all__ = [
    "CheckResult",
    "RunResolution",
    "SettingsResolution",
    "Severity",
    "ShopSettings",
    "Status",
    "check_identifiers",
    "check_non_empty",
    "check_primary_key_uniqueness",
    "check_row_parity",
    "check_schema_drift",
    "check_shop_settings",
    "check_source_connection",
    "check_window_resolution",
]
