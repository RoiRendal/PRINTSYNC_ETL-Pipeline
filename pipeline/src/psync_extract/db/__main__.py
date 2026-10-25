"""Command line entry point for the pipeline's database commands.

    python -m psync_extract.db migrate [--dry-run]

The configuration is read exactly as a run reads it (environment or ``pipeline/.env``), so a
mistake in ``.env`` surfaces here too, before anything touches a database.
"""

from __future__ import annotations

import argparse
import sys

from psync_extract.config import ConfigurationError, load_settings
from psync_extract.db.migrate import MigrationError, apply_migrations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m psync_extract.db")
    commands = parser.add_subparsers(dest="command", required=True)

    migrate = commands.add_parser(
        "migrate",
        help="Apply pending migrations to the pipeline's own database.",
    )
    migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be applied without changing anything.",
    )

    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        applied = apply_migrations(settings, dry_run=args.dry_run)
    except (ConfigurationError, MigrationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not applied:
        print("nothing to do: the database is up to date")
        return 0

    verb = "would apply" if args.dry_run else "applied"
    for version in applied:
        print(f"{verb}: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
