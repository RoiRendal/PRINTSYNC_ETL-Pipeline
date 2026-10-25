"""V4 — the shop settings a run needs (doc section 3).

``business_settings`` is per branch now (L5): one row per branch, not one row for the shop. The
pipeline reads the row for **one configured reference branch**, which supplies:

* ``time_zone`` — the zone that defines the business-day boundary;
* ``vat_rate`` and ``currency_symbol`` — for reporting, later.

Without a settings row the run cannot compute a day boundary at all, so a missing row, a blank
time zone, or a time zone the system does not recognise is a critical failure. There is no fallback
to another branch: picking one silently would make the run's boundary depend on whichever row
happened to exist.

The reference branch may be given as a ``branches.code`` (the team's choice: ``BAL``) or as a UUID.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from psync_extract.config import Settings
from psync_extract.db.connection import SourceConnectionError, connect_source
from psync_extract.validation.result import CheckResult

__all__ = ["SettingsResolution", "ShopSettings", "check_shop_settings"]

_BY_CODE = """
    select b.code, bs.time_zone, bs.vat_rate, bs.currency_symbol
    from public.business_settings bs
    join public.branches b on b.id = bs.branch_id
    where b.code = %s
    limit 1
"""

_BY_ID = """
    select b.code, bs.time_zone, bs.vat_rate, bs.currency_symbol
    from public.business_settings bs
    join public.branches b on b.id = bs.branch_id
    where b.id = %s
    limit 1
"""


@dataclass(frozen=True)
class ShopSettings:
    """The values the reference branch contributes to a run."""

    branch_code: str
    time_zone: str
    vat_rate: Decimal
    currency_symbol: str


@dataclass(frozen=True)
class SettingsResolution:
    """V4's answer: the verdict, and the settings when there are any."""

    result: CheckResult
    settings: ShopSettings | None


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def check_shop_settings(settings: Settings) -> SettingsResolution:
    """Read the reference branch's settings, or explain why the run cannot start."""
    reference = settings.reference_branch.strip()
    sql = _BY_ID if _looks_like_uuid(reference) else _BY_CODE

    try:
        with connect_source(settings) as conn:
            row = conn.execute(sql, (reference,)).fetchone()
    except SourceConnectionError as exc:
        return SettingsResolution(
            result=CheckResult(
                check_id="V4",
                status="FAIL",
                severity="critical",
                message=str(exc),
                error_code=exc.error_code,
            ),
            settings=None,
        )
    except psycopg.Error as exc:
        return SettingsResolution(
            result=CheckResult(
                check_id="V4",
                status="FAIL",
                severity="critical",
                message=f"could not read business_settings: {exc}",
                error_code="SRC_QUERY_FAILED",
            ),
            settings=None,
        )

    if row is None:
        return SettingsResolution(
            result=CheckResult(
                check_id="V4",
                status="FAIL",
                severity="critical",
                message=(
                    f"no business_settings row for reference branch {reference!r}; "
                    "the run cannot compute a business-day boundary without it"
                ),
                error_code="SETTINGS_MISSING",
            ),
            settings=None,
        )

    branch_code, time_zone, vat_rate, currency_symbol = row

    if not time_zone or not time_zone.strip():
        return SettingsResolution(
            result=CheckResult(
                check_id="V4",
                status="FAIL",
                severity="critical",
                message=f"branch {branch_code} has no time_zone in business_settings",
                error_code="SETTINGS_INVALID",
            ),
            settings=None,
        )

    try:
        ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        return SettingsResolution(
            result=CheckResult(
                check_id="V4",
                status="FAIL",
                severity="critical",
                message=f"branch {branch_code} has an unknown time_zone: {time_zone!r}",
                error_code="SETTINGS_INVALID",
            ),
            settings=None,
        )

    resolved = ShopSettings(
        branch_code=branch_code,
        time_zone=time_zone,
        vat_rate=vat_rate,
        currency_symbol=currency_symbol,
    )
    return SettingsResolution(
        result=CheckResult(
            check_id="V4",
            status="PASS",
            severity="critical",
            message=(
                f"branch {branch_code}: time_zone={time_zone}, "
                f"vat_rate={vat_rate}, currency_symbol={currency_symbol}"
            ),
        ),
        settings=resolved,
    )
