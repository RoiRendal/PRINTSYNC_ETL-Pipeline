"""The business day, and the range the extractors actually read (doc section 1.3).

A run processes one calendar day in ``Asia/Manila``. It also re-reads a few days behind that day,
because some records change after their day has closed — a sale gets voided, for instance (P1), and
``sales_transactions`` has no ``updated_at`` to ask "what changed since yesterday?" (P2). The
look-back is the blunt answer to that: re-read, and let the Transformation stage overwrite the
day's output.

Two ranges, deliberately kept apart:

* the **business day** — ``[window_start, window_end)``, the day being processed;
* the **read range** — ``[read_start, read_end)``, the day plus the look-back.

Confusing the two is how a sale voided after its day closed gets missed, so both are named
explicitly and neither is computed by a caller.

This module is arithmetic only: no clock, no database, no configuration lookup. Whether a date is
*acceptable* to process is V3's question, not this one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["ExtractionWindow", "resolve_window"]


@dataclass(frozen=True)
class ExtractionWindow:
    """One run's business day and read range, as timezone-aware instants."""

    business_date: date
    time_zone: str
    lookback_days: int
    window_start: datetime
    window_end: datetime
    read_start: datetime

    @property
    def read_end(self) -> datetime:
        """End of the read range, exclusive — the same instant the business day ends."""
        return self.window_end

    def describe(self) -> str:
        """A one-line summary for the run log."""
        return (
            f"business_date={self.business_date.isoformat()} "
            f"window=[{self.window_start.isoformat()}, {self.window_end.isoformat()}) "
            f"read=[{self.read_start.isoformat()}, {self.read_end.isoformat()}) "
            f"lookback_days={self.lookback_days}"
        )


def resolve_window(
    business_date: date,
    *,
    time_zone: str = "Asia/Manila",
    lookback_days: int = 3,
) -> ExtractionWindow:
    """Turn a business date into the two ranges a run uses.

    ``Asia/Manila`` has no daylight saving, so a day is always 24 hours and the offset is always
    ``+08:00``. The zone is still applied properly rather than hard-coded, so a branch in another
    zone would work the day the branch model settles (P5).
    """
    if lookback_days < 0:
        raise ValueError(f"lookback_days must be zero or greater, got {lookback_days}")

    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone: {time_zone!r}") from exc

    def midnight(day: date) -> datetime:
        return datetime.combine(day, time.min, tzinfo=zone)

    window_start = midnight(business_date)
    window_end = midnight(business_date + timedelta(days=1))
    read_start = midnight(business_date - timedelta(days=lookback_days))

    return ExtractionWindow(
        business_date=business_date,
        time_zone=time_zone,
        lookback_days=lookback_days,
        window_start=window_start,
        window_end=window_end,
        read_start=read_start,
    )
