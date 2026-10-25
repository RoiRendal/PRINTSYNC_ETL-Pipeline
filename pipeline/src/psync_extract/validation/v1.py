"""V1 — the source is reachable and the credentials work (doc section 3).

The check opens the read-only source connection and runs ``SELECT 1`` inside the configured
timeout. It reports a result rather than raising: section 7.1 turns a V1 failure into a RETRY,
and that decision belongs to the caller, not to the check.
"""

from __future__ import annotations

from psync_extract.config import Settings
from psync_extract.db.connection import SourceConnectionError, connect_source
from psync_extract.validation.result import CheckResult

__all__ = ["check_source_connection"]


def check_source_connection(settings: Settings) -> CheckResult:
    """Confirm PRINTSYNC is reachable before anything is read."""
    try:
        with connect_source(settings) as conn:
            conn.execute("SELECT 1").fetchone()
    except SourceConnectionError as exc:
        return CheckResult(
            check_id="V1",
            status="FAIL",
            severity="critical",
            message=str(exc),
            error_code=exc.error_code,
        )

    return CheckResult(
        check_id="V1",
        status="PASS",
        severity="critical",
        message=(
            "reached the source and ran SELECT 1 within "
            f"{settings.connect_timeout_seconds}s"
        ),
    )
