"""Load configuration (doc sections 1.2, 1.3 and 3.4).

Stage 3 has two connections and one batch identifier — that is the whole of its configuration.
Everything else about the batch (its window, its decision, its per-table counts) comes from the
``transformation_runs`` ledger row, never from here.

``psync_extract.config`` and ``psync_transform.config`` are deliberately not imported: a shared
module would let a change in an earlier stage silently alter this one. The three stages share an
``.env`` file and one evidence folder, and that is the whole of their coupling.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from psync_load import __version__

__all__ = [
    "ConfigurationError",
    "RULES_VERSION",
    "Settings",
    "code_version",
    "load_settings",
]

# .../pipeline/src/psync_load/config.py -> .../pipeline
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"

# .../pipeline -> the repository. The evidence folder sits beside docs/, not inside the package.
_REPOSITORY_ROOT = _PROJECT_ROOT.parent
DEFAULT_DATA_DIR = _REPOSITORY_ROOT / "data"

DEFAULT_PIPELINE_NAME = "psync_nightly_analytics"
DEFAULT_RUN_TIMEZONE = "Asia/Manila"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_LOCK_TIMEOUT_SECONDS = 30
DEFAULT_STATEMENT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_REJECT_RATE_PERCENT = 1

# The revision of the rule set in the load document. Bumped whenever a rule's behaviour changes.
RULES_VERSION = "1.0"


def code_version() -> str:
    """The code and rule revision, as recorded on every load run (doc section 6.1)."""
    return f"psync_load {__version__} / rules {RULES_VERSION}"


class ConfigurationError(RuntimeError):
    """The load cannot start because its configuration is missing or invalid."""


class Settings(BaseSettings):
    """Everything a load batch needs, validated at startup."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- The two databases (doc sections 1.1 and 1.2) --------------------------------------
    psync_analytics_dsn: str = Field(
        description="Read connection to the Stage 2 output in psync_analytics. "
        "PRINTSYNC is never opened by this stage."
    )
    psync_warehouse_dsn: str = Field(
        description="Write connection to the reporting database, psync_warehouse. "
        "It must resolve to a different database from psync_analytics_dsn."
    )

    # --- Which batch (doc section 1.1) ----------------------------------------------------
    pipeline_name: str = DEFAULT_PIPELINE_NAME
    batch_id: str | None = None

    # --- Where the evidence lives (doc sections 6.2 and 7) --------------------------------
    psync_data_dir: Path = Field(
        default=DEFAULT_DATA_DIR,
        description="The evidence folder, shared with Stages 1 and 2. One knob, so the three "
        "stages cannot be pointed at different folders.",
    )

    # --- Behaviour (doc sections 3.4 and 5) ------------------------------------------------
    run_timezone: str = DEFAULT_RUN_TIMEZONE
    lock_timeout_seconds: int = DEFAULT_LOCK_TIMEOUT_SECONDS
    statement_timeout_seconds: int = DEFAULT_STATEMENT_TIMEOUT_SECONDS
    max_reject_rate_percent: int = DEFAULT_MAX_REJECT_RATE_PERCENT
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS

    @property
    def log_directory(self) -> Path:
        """Where this stage's two log files go, inside the shared evidence folder."""
        return self.psync_data_dir / "logs" / "load"

    @property
    def snapshot_directory(self) -> Path:
        """Where pre-load snapshots go (doc section 7)."""
        return self.psync_data_dir / "snapshots"

    @field_validator("psync_analytics_dsn", "psync_warehouse_dsn", "pipeline_name")
    @classmethod
    def _not_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name.upper()} must not be blank")
        return value.strip()

    @field_validator("batch_id")
    @classmethod
    def _batch_id_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("BATCH_ID must not be blank")
        return value.strip() if value else value

    @field_validator("run_timezone")
    @classmethod
    def _known_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone: {value}") from exc
        return value

    @field_validator("psync_data_dir")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        """A relative data dir would move with the caller's working directory."""
        return value if value.is_absolute() else _REPOSITORY_ROOT / value


def load_settings(**overrides: object) -> Settings:
    """Read the environment and ``.env``, with the caller's overrides winning."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        names = ", ".join(
            str(error["loc"][0]).upper() for error in exc.errors() if error.get("loc")
        )
        raise ConfigurationError(f"invalid configuration: {names}") from exc
