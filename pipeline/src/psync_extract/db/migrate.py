"""Apply the pipeline's own migrations (doc sections 1.6 and 6.1).

The pipeline owns one database, ``psync_analytics``, and its schema is versioned by the SQL files
in ``pipeline/migrations/``. This module applies them in filename order and records each one in
``schema_migrations``, so running it twice is a no-op.

It refuses to run when the target resolves to the same database as the source: PRINTSYNC is never
modified (doc section 1.6).

Usage:
    python -m psync_extract.db migrate [--dry-run]
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from psync_extract.config import Settings

__all__ = [
    "Migration",
    "MigrationError",
    "apply_migrations",
    "discover_migrations",
    "ensure_separate_databases",
]

# pipeline/src/psync_extract/db/migrate.py -> pipeline/migrations
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text        PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now(),
    checksum   text        NOT NULL
)
"""

_BEGIN = re.compile(r"^\s*BEGIN\s*;", re.IGNORECASE)
_COMMIT = re.compile(r"COMMIT\s*;\s*$", re.IGNORECASE)


class MigrationError(RuntimeError):
    """The migrations could not be applied."""


@dataclass(frozen=True)
class Migration:
    """One SQL file, identified by its filename without the extension."""

    version: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Every ``*.sql`` file in the directory, in filename order."""
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")

    files = sorted(directory.glob("*.sql"))
    if not files:
        raise MigrationError(f"no migration files in {directory}")

    return [
        Migration(version=path.stem, path=path, sql=path.read_text(encoding="utf-8"))
        for path in files
    ]


def _endpoint(dsn: str) -> tuple[str, int, str]:
    """The (host, port, database) a connection string points at."""
    try:
        info = conninfo_to_dict(dsn)
    except Exception as exc:  # psycopg raises its own error type here
        raise MigrationError(f"could not read a connection string: {exc}") from exc

    return (
        str(info.get("host", "")).lower(),
        int(info.get("port", 5432)),
        str(info.get("dbname", "")).lower(),
    )


def ensure_separate_databases(settings: Settings) -> None:
    """Refuse to run when the target would be the PRINTSYNC database (doc section 1.6)."""
    source = _endpoint(settings.psync_source_dsn)
    target = _endpoint(settings.psync_target_dsn)

    if source == target:
        host, port, database = target
        raise MigrationError(
            "refusing to run: PSYNC_TARGET_DSN and PSYNC_SOURCE_DSN point at the same database "
            f"({host}:{port}/{database}). The pipeline must never modify PRINTSYNC."
        )


def _body(sql: str) -> str:
    """Drop the file's own BEGIN/COMMIT so the applier owns the transaction."""
    return _COMMIT.sub("", _BEGIN.sub("", sql.strip())).strip()


def apply_migrations(
    settings: Settings,
    *,
    dry_run: bool = False,
    directory: Path = MIGRATIONS_DIR,
    migrations: list[Migration] | None = None,
) -> list[str]:
    """Apply every migration not yet recorded, and return their versions.

    A migration that is already recorded is skipped. A migration whose file has changed since it
    was applied is an error: applied migrations are immutable, so a correction goes in a new file.
    """
    ensure_separate_databases(settings)
    pending = migrations if migrations is not None else discover_migrations(directory)

    applied: list[str] = []

    with psycopg.connect(settings.psync_target_dsn, autocommit=True) as conn:
        conn.execute(_BOOTSTRAP)
        rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
        recorded = {version: checksum for version, checksum in rows}

        for migration in pending:
            if migration.version in recorded:
                if recorded[migration.version] != migration.checksum:
                    raise MigrationError(
                        f"{migration.path.name} changed after it was applied "
                        f"(recorded {recorded[migration.version][:12]}..., now "
                        f"{migration.checksum[:12]}...). Applied migrations are immutable; "
                        "add a new file instead of editing this one."
                    )
                continue

            if dry_run:
                applied.append(migration.version)
                continue

            # One transaction per file: the schema change and its record commit together.
            with conn.transaction():
                conn.execute(_body(migration.sql))
                conn.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (migration.version, migration.checksum),
                )

            applied.append(migration.version)

    return applied
