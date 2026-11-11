"""Apply the warehouse migrations (doc sections 1.2 and 2).

These live in ``pipeline/warehouse_migrations/``, **not** in ``pipeline/migrations/``. Stage 1's
migration applier globs that directory and applies everything it finds to ``psync_analytics``;
putting the warehouse schema there would create the reporting tables in the wrong database.

The applier records each file in ``schema_migrations`` so a second run is a no-op, and refuses to
run when the source and warehouse DSNs resolve to the same database.

Usage:
    python -m psync_load.db migrate [--dry-run]
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from psync_load.config import Settings
from psync_load.db import connect_warehouse

__all__ = [
    "Migration",
    "MigrationError",
    "apply_migrations",
    "discover_migrations",
    "ensure_separate_databases",
]

# pipeline/src/psync_load/db/migrate.py -> pipeline/warehouse_migrations
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "warehouse_migrations"

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text        PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now(),
    checksum   text        NOT NULL
)
"""


class MigrationError(RuntimeError):
    """The warehouse migrations could not be applied."""


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
    """Every ``*.sql`` file in the warehouse directory, in filename order."""
    if not directory.is_dir():
        raise MigrationError(f"warehouse migrations directory not found: {directory}")
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
    except Exception as exc:
        raise MigrationError(f"could not read a connection string: {exc}") from exc
    return (
        str(info.get("host", "")).lower(),
        int(info.get("port", 5432)),
        str(info.get("dbname", "")),
    )


def ensure_separate_databases(settings: Settings) -> None:
    """Refuse to run when the two DSNs name the same database.

    A load that reads and writes the same database is not a load, and applying the warehouse schema
    there would damage the Stage 2 output.
    """
    source = _endpoint(settings.psync_analytics_dsn)
    target = _endpoint(settings.psync_warehouse_dsn)
    if source == target:
        raise MigrationError(
            "PSYNC_ANALYTICS_DSN and PSYNC_WAREHOUSE_DSN resolve to the same database "
            f"({target[2]}). The load stage needs a separate reporting database."
        )


def apply_migrations(settings: Settings, *, dry_run: bool = False) -> list[str]:
    """Apply pending warehouse migrations; return the versions applied."""
    ensure_separate_databases(settings)
    pending = discover_migrations()
    if dry_run:
        return [migration.version for migration in pending]

    applied: list[str] = []
    with connect_warehouse(settings) as conn:
        conn.execute(_BOOTSTRAP)
        for migration in pending:
            done = conn.execute(
                "select 1 from public.schema_migrations where version = %s",
                (migration.version,),
            ).fetchone()
            if done:
                continue
            conn.execute(migration.sql)
            conn.execute(
                "insert into public.schema_migrations (version, checksum) values (%s, %s)",
                (migration.version, migration.checksum),
            )
            applied.append(migration.version)
    return applied
