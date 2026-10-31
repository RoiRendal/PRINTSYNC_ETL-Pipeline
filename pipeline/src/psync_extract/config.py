"""Pipeline configuration (doc sections 1.3, 1.5 L5 and 4).

Every value the pipeline needs is read from the environment or from ``pipeline/.env``.
Nothing is hard-coded, and no credential is ever committed.

Two databases are named here, and they must never be confused:

* ``PSYNC_SOURCE_DSN`` - PRINTSYNC's operational database, reached with a read-only login.
* ``PSYNC_TARGET_DSN`` - the pipeline's own database, ``psync_analytics``.

The pipeline never writes to the source (doc section 1.6).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["ConfigurationError", "Settings", "load_settings"]

# .../pipeline/src/psync_extract/config.py -> .../pipeline
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"

# .../pipeline -> the repository. The evidence folder sits beside docs/, not inside the package:
# what a defense needs to read should not be mixed in with the code that produced it (doc
# section 5). The default is absolute, so the logs do not follow whatever directory a scheduler
# happened to start the process in.
_REPOSITORY_ROOT = _PROJECT_ROOT.parent
DEFAULT_DATA_DIR = _REPOSITORY_ROOT / "data"

DEFAULT_PIPELINE_NAME = "psync_nightly_analytics"
DEFAULT_LOOKBACK_DAYS = 3
DEFAULT_RUN_TIMEZONE = "Asia/Manila"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 300


class ConfigurationError(RuntimeError):
    """The pipeline cannot start because its configuration is missing or invalid."""


class Settings(BaseSettings):
    """Everything a run needs, validated at startup."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- The two databases (doc sections 1.2, 1.6) --------------------------------------
    psync_source_dsn: str = Field(description="Read-only connection to PRINTSYNC.")
    psync_target_dsn: str = Field(description="Connection to the pipeline's own database.")

    # --- Run parameters (doc sections 1.3, 1.5 L5, 4) -----------------------------------
    pipeline_name: str = DEFAULT_PIPELINE_NAME
    business_date: date | None = None
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    run_timezone: str = DEFAULT_RUN_TIMEZONE
    reference_branch: str = Field(
        description="The Balayan branch's code or UUID; supplies time_zone, vat_rate and "
        "currency_symbol through its business_settings row."
    )
    closed_day: date | None = None
    """Operator-supplied closed-day flag (doc section 3).

    Only V8 uses it, and only to tolerate a zero-row day. It is never inferred from the data:
    a quiet night and a broken window look identical, so the operator has to say which it was.
    """

    # --- Connection behaviour (doc sections 1.5 L8, 7.1) --------------------------------
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS
    retry_count: int = DEFAULT_RETRY_COUNT
    retry_backoff_seconds: int = DEFAULT_RETRY_BACKOFF_SECONDS

    # --- Where the evidence lives (doc section 5) ---------------------------------------
    psync_data_dir: Path = Field(
        default=DEFAULT_DATA_DIR,
        description="The evidence folder. The logs, the handover manifests and the exports live "
        "beneath it. One knob: moving it moves all of them together, so the two stages cannot end "
        "up writing to different folders.",
    )

    @property
    def log_directory(self) -> Path:
        """Where this stage's run logs go, inside the evidence folder.

        The stage name is a directory rather than a filename prefix: ``psync_nightly_analytics``
        does not say "extraction" to a reader, and a flat folder made the two stages' logs
        distinguishable only by reading the documentation.
        """
        return self.psync_data_dir / "logs" / "extract"

    @property
    def handover_directory(self) -> Path:
        """Where the handover manifests go (doc section 7.3)."""
        return self.psync_data_dir / "handover"

    @field_validator(
        "psync_source_dsn", "psync_target_dsn", "pipeline_name", "reference_branch"
    )
    @classmethod
    def _not_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name.upper()} must not be blank")
        return value.strip()

    @field_validator("psync_data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        """Anchor a relative path to the repository, never to the working directory.

        ``PSYNC_DATA_DIR=data`` has to mean the same folder whether the pipeline was started from
        the repository root or from ``pipeline/``; a scheduler's working directory is not a property
        of the run.
        """
        return value if value.is_absolute() else (_REPOSITORY_ROOT / value)

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

    @field_validator(
        "lookback_days",
        "connect_timeout_seconds",
        "retry_count",
        "retry_backoff_seconds",
    )
    @classmethod
    def _not_negative(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name.upper()} must be zero or greater")
        return value

    def resolved_business_date(self) -> date:
        """The day this run processes (doc section 1.3).

        The configured date when one was given; otherwise yesterday in the run time zone,
        because a run at 01:00 processes the day that has just ended.
        """
        if self.business_date is not None:
            return self.business_date
        return datetime.now(ZoneInfo(self.run_timezone)).date() - timedelta(days=1)


def load_settings(**overrides: object) -> Settings:
    """Build :class:`Settings`, turning any validation failure into one readable error.

    Missing or invalid values are reported by variable name, so a misconfigured run fails
    immediately with something an operator can act on rather than a raw stack trace.
    """
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            field = str(error["loc"][0]) if error["loc"] else "configuration"
            problems.append(f"{field.upper()}: {error['msg']}")
        raise ConfigurationError(
            "Pipeline configuration is missing or invalid - " + "; ".join(problems)
        ) from exc
