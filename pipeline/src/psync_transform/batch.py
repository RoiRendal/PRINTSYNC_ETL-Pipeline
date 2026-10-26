"""What one transformation batch is: a handover, a window, and an id (doc sections 1.1 and 8).

The batch is not a day. Stage 1 re-reads a three-day look-back on every run, so the staged rows for
``business_date = D`` contain sales created on ``D-3 … D``, and every one of those days has to be
rebuilt — the whole reason a sale is re-read is that its day has changed.

The window is therefore ``[business_date - lookback_days, business_date]``, and ``lookback_days``
is read from the **parent run's own record**, not configured again here. Two sources for one window
is two chances to disagree about which days a batch covers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.handover import Handover, HandoverError, load_handover

__all__ = ["Batch", "resolve_batch"]


@dataclass(frozen=True)
class Batch:
    """One handover, and the span of business dates it will rebuild."""

    handover: Handover
    lookback_days: int

    @property
    def parent_run_id(self) -> UUID:
        """The extraction run this batch transforms."""
        return self.handover.run_id

    @property
    def business_date(self) -> date:
        """The day being processed — the one the extraction was run for."""
        return self.handover.business_date

    @property
    def window_start(self) -> date:
        """The oldest business date this batch rebuilds. Inclusive."""
        return self.business_date - timedelta(days=self.lookback_days)

    @property
    def window_end(self) -> date:
        """The business date being processed. Inclusive, and the newest date written."""
        return self.business_date

    @property
    def batch_id(self) -> str:
        """The batch's stable identifier (doc section 8).

        Stable for one handover, so a retry reuses it and rewrites its own record instead of
        appending a second one. It carries the parent run, because two extraction runs for the same
        day are two different batches.
        """
        return f"TRF_{self.business_date:%Y%m%d}_{str(self.parent_run_id)[:8]}"

    def covers(self, day: date) -> bool:
        """True when ``day`` falls inside the window this batch rebuilds."""
        return self.window_start <= day <= self.window_end


def _lookback_days(settings: Settings, parent_run_id: UUID) -> int:
    """The look-back the extraction actually used, from its run-level row.

    Read rather than configured: the handover manifest does not carry it, and a default here could
    silently disagree with the days the extraction really read.
    """
    with connect_target(settings) as conn:
        row = conn.execute(
            "select lookback_days from public.pipeline_runs "
            "where run_id = %s and table_name is null",
            (parent_run_id,),
        ).fetchone()

    if row is None:
        raise HandoverError(
            f"the extraction run {parent_run_id} has no run-level record in pipeline_runs. The "
            "handover names a run the pipeline's own ledger does not know about."
        )

    lookback = row[0]
    if lookback is None:
        raise HandoverError(
            f"the extraction run {parent_run_id} records no lookback_days, so the batch window "
            "cannot be established. Transform nothing rather than guess which days to rebuild."
        )

    return int(lookback)


def resolve_batch(settings: Settings) -> Batch:
    """Find this run's handover and work out the window it rebuilds."""
    business_date = settings.resolved_business_date()
    handover = load_handover(
        settings.handover_directory, business_date, settings.parent_run_id
    )
    return Batch(
        handover=handover,
        lookback_days=_lookback_days(settings, handover.run_id),
    )
