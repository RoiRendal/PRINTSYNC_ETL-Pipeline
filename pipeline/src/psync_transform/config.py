"""Transformation configuration (doc sections 1.2, 1.4 and 10.1).

The transformation stage has far fewer knobs than the extraction stage, on purpose. Everything that
describes *the batch* — the business day, the look-back, the parent extraction run — is read from
the handover and from ``pipeline_runs``, not configured here. What is left is the connection, the
two thresholds the document fixes in advance, and the demand window.

``psync_extract.config`` deliberately is not imported. The two stages share a ``.env`` and one
field name (``PSYNC_TARGET_DSN``), and that is the whole of their coupling; importing one stage's
configuration into the other would let a change in Stage 1 silently alter Stage 2.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from psync_transform import __version__

__all__ = [
    "ConfigurationError",
    "RULES_VERSION",
    "Settings",
    "code_version",
    "load_settings",
]

# .../pipeline/src/psync_transform/config.py -> .../pipeline
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"

DEFAULT_PIPELINE_NAME = "psync_nightly_analytics"
DEFAULT_RUN_TIMEZONE = "Asia/Manila"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10

# The revision of the rule set in the transformation document. Bumped whenever a rule's behaviour
# changes, so a published figure can be traced to the rules that produced it (doc section 8).
RULES_VERSION = "1.0"

# Section 5.6 (A-02, B-13): the trailing window the demand average is taken over. Seven days, not
# the three-day look-back — the look-back exists to catch late voids, and using it as a demand
# window would conflate "we re-read three days" with "demand is measured over three days".
DEFAULT_DEMAND_WINDOW_DAYS = 7

# Section 10.1: fixed before any batch runs, so it cannot be chosen to fit a result.
DEFAULT_MAX_REJECT_RATE_PERCENT = 1


def code_version() -> str:
    """The code and rule revision, as recorded on every batch (doc section 8)."""
    return f"psync_transform {__version__} / rules {RULES_VERSION}"


class ConfigurationError(RuntimeError):
    """The transformation cannot start because its configuration is missing or invalid."""


class Settings(BaseSettings):
    """Everything a transformation batch needs, validated at startup."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- The pipeline's own database (doc section 1.1) ------------------------------------
    psync_target_dsn: str = Field(
        description="Connection to the pipeline's own database, psync_analytics. "
        "PRINTSYNC is never opened by this stage."
    )

    # --- Which batch (doc section 1.1) ----------------------------------------------------
    pipeline_name: str = DEFAULT_PIPELINE_NAME
    business_date: date | None = None
    parent_run_id: UUID | None = Field(
        default=None,
        description="Pin the batch to one extraction run. Unset means 'the latest run handed "
        "over for this business date'.",
    )

    # --- Behaviour (doc sections 5.6, 10.1) -----------------------------------------------
    run_timezone: str = DEFAULT_RUN_TIMEZONE
    demand_window_days: int = DEFAULT_DEMAND_WINDOW_DAYS
    max_reject_rate_percent: int = DEFAULT_MAX_REJECT_RATE_PERCENT
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS

    @field_validator("psync_target_dsn", "pipeline_name")
    @classmethod
    def _not_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name.upper()} must not be blank")
        return value.strip()

    @field_validator("run_timezone")
    @classmethod
    def _known_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"RUN_TIMEZONE is not a known IANA time zone: {value!r}"
            ) from exc
        return value

    @field_validator("connect_timeout_seconds")
    @classmethod
    def _not_negative(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name.upper()} must be zero or greater")
        return value

    @field_validator("demand_window_days")
    @classmethod
    def _at_least_one_day(cls, value: int) -> int:
        """A zero-day window would divide by zero in B-13, so it is refused here, not later."""
        if value < 1:
            raise ValueError("DEMAND_WINDOW_DAYS must be one day or more")
        return value

    @field_validator("max_reject_rate_percent")
    @classmethod
    def _a_percentage(cls, value: int) -> int:
        if not 0 <= value <= 100:
            raise ValueError("MAX_REJECT_RATE_PERCENT must be between 0 and 100")
        return value

    @property
    def code_version(self) -> str:
        return code_version()

    def resolved_business_date(self) -> date:
        """The day this batch processes.

        The configured date when one was given; otherwise yesterday in the run time zone, because
        a nightly transformation at 01:30 processes the day that has just ended — the same rule the
        extraction stage applies to its own default.
        """
        if self.business_date is not None:
            return self.business_date
        return datetime.now(ZoneInfo(self.run_timezone)).date() - timedelta(days=1)


def load_settings(**overrides: object) -> Settings:
    """Build :class:`Settings`, turning any validation failure into one readable error.

    Missing or invalid values are reported by variable name, so a misconfigured batch fails with
    something an operator can act on rather than a raw stack trace.
    """
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            field = str(error["loc"][0]) if error["loc"] else "configuration"
            problems.append(f"{field.upper()}: {error['msg']}")
        raise ConfigurationError(
            "Transformation configuration is missing or invalid - " + "; ".join(problems)
        ) from exc
