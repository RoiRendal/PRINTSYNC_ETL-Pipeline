"""The inspection pack: one business day's data and its logs (doc section 5).

The pipeline keeps the data in the database, and until now that was the only place it lived — a
deliberate choice, because a copy of the rows is a second version of the truth. A reader who has no
database, though, cannot see anything at all: no extracted rows, no transformed rows, no way to
connect a number to the log line that produced it.

This module answers that without changing the rule. It is a **snapshot for inspection**, taken on
request, with a date in its name:

* ``extracted/`` — every staging table, for one extraction run, as it was written.
* ``transformed/`` — every output table, as the batch left it.
* ``logs/`` — the run's text narrative and JSON record, for both stages.
* ``README.txt`` — what each file is, which run produced it, and the counts.

Nothing here is recomputed. Every file is a straight copy of a table or a log, so the pack cannot
disagree with the database it came from — and deleting it loses nothing, because the rows are still
there.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg

from psync_extract.config import ConfigurationError, load_settings
from psync_extract.runlog import log_stem

__all__ = ["PackResult", "PackError", "build_pack", "main"]

PACKS_DIR = "packs"
BOM = b"\xef\xbb\xbf"

# What the extraction wrote. One row per source table, all for the same run.
STAGING_TABLES = (
    "stg_sales_transactions",
    "stg_sales_transaction_items",
    "stg_payments",
    "stg_orders",
    "stg_inventory_items",
    "stg_business_settings",
    "stg_branches",
)

# What the transformation published. Dimensions are cumulative history; the facts are the days.
MART_TABLES = (
    "dim_date",
    "dim_branch",
    "dim_item",
    "dim_order_status",
    "fct_daily_sales",
    "fct_daily_product_demand",
    "fct_daily_stock_snapshot",
    "fct_daily_order_status",
)

_EXTRACTION_RUN_SQL = """
    select run_id, run_key
    from public.pipeline_runs
    where business_date = %s
      and table_name is null
      and extraction_status = 'success'
    order by extraction_started_at desc
    limit 1
"""

_BATCH_SQL = """
    select batch_id
    from public.transformation_runs
    where business_date = %s
      and table_name is null
    order by transformation_started_at desc
    limit 1
"""


class PackError(RuntimeError):
    """The pack cannot be built as asked."""


@dataclass(frozen=True)
class PackResult:
    """Where the pack went, and what it holds."""

    path: Path
    extracted: int
    transformed: int
    log_files: int


def _write_table(conn: psycopg.Connection, path: Path, table: str, where: str, params: tuple) -> int:
    """Copy one table straight to CSV, with its header, as UTF-8 with a BOM.

    ``where`` is written here, never by a caller: the table names are this module's own tuple, so
    neither can carry SQL that was not written in this file.
    """
    sql = (
        f"copy (select * from public.{table} {where} order by 1) "
        "to stdout (format csv, header true)"
    )
    with path.open("wb") as handle:
        handle.write(BOM)
        with conn.cursor() as cursor, cursor.copy(sql, params or None) as copy:
            for chunk in copy:
                handle.write(chunk)
    # Counted by the database, not by counting lines in the file: a value may contain a newline,
    # and a row count that disagrees with the rows is worse than no count.
    return conn.execute(
        f"select count(*) from public.{table} {where}", params or None
    ).fetchone()[0]


def _copy_log(directory: Path, stem: str, into: Path) -> int:
    """Copy a run's two log files, if they are still there."""
    copied = 0
    for suffix in (".log", ".json"):
        source = directory / f"{stem}{suffix}"
        if source.is_file():
            shutil.copy2(source, into / source.name)
            copied += 1
    return copied


def build_pack(
    conn: psycopg.Connection,
    data_dir: Path | str,
    business_date: date,
    *,
    as_of: date | None = None,
    now: datetime | None = None,
) -> PackResult:
    """Write ``<data dir>/packs/psync_pack_<as_of>.zip`` for one business day."""
    data_dir = Path(data_dir)

    run = conn.execute(_EXTRACTION_RUN_SQL, (business_date,)).fetchone()
    if run is None:
        raise PackError(
            f"no successful extraction for {business_date} in pipeline_runs. Run "
            f"`python -m psync_extract --date {business_date}` first."
        )
    run_id, run_key = run

    batch = conn.execute(_BATCH_SQL, (business_date,)).fetchone()
    if batch is None:
        raise PackError(
            f"no transformation batch for {business_date} in transformation_runs. Run "
            f"`python -m psync_transform --date {business_date}` first."
        )
    batch_id = batch[0]

    as_of = as_of or business_date
    staging = data_dir / PACKS_DIR / f".staging_{business_date.isoformat()}"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "extracted").mkdir(parents=True)
    (staging / "transformed").mkdir()
    (staging / "logs").mkdir()

    extracted_counts: dict[str, int] = {}
    transformed_counts: dict[str, int] = {}

    try:
        for table in STAGING_TABLES:
            extracted_counts[table] = _write_table(
                conn, staging / "extracted" / f"{table}.csv", table, "where run_id = %s", (run_id,)
            )
        for table in MART_TABLES:
            transformed_counts[table] = _write_table(
                conn, staging / "transformed" / f"{table}.csv", table, "", ()
            )

        log_files = _copy_log(
            data_dir / "logs" / "extract", log_stem(run_key, run_id), staging / "logs"
        )
        log_files += _copy_log(data_dir / "logs" / "transform", batch_id, staging / "logs")

        (staging / "README.txt").write_text(
            _readme(business_date, run_id, run_key, batch_id, extracted_counts,
                    transformed_counts, log_files, now or datetime.now(timezone.utc)),
            encoding="utf-8",
        )

        target = data_dir / PACKS_DIR / f"psync_pack_{as_of.isoformat()}.zip"
        temporary = target.with_suffix(".zip.tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=path.relative_to(staging).as_posix())
        temporary.replace(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return PackResult(
        path=target,
        extracted=sum(extracted_counts.values()),
        transformed=sum(transformed_counts.values()),
        log_files=log_files,
    )


def _readme(
    business_date: date,
    run_id,
    run_key: str,
    batch_id: str,
    extracted: dict[str, int],
    transformed: dict[str, int],
    log_files: int,
    built_at: datetime,
) -> str:
    """The pack's own explanation, for a reader who has never seen the database."""
    lines = [
        "psync_analytics - inspection pack",
        "=================================",
        "",
        f"business day   {business_date.isoformat()}",
        f"built at       {built_at.isoformat()}",
        f"extraction run {run_key}  ({str(run_id)[:8]})",
        f"batch          {batch_id}",
        "",
        "What is in here",
        "---------------",
        "",
        "extracted/     The data as it was read out of PRINTSYNC, one CSV per source table.",
        "               These are the staging tables, unchanged, exactly as the pipeline wrote",
        "               them. The 'source_id' column is the row's id in PRINTSYNC, so any row",
        "               here can be traced back to the shop's own record.",
        "",
        "transformed/   The data the pipeline published, one CSV per output table. The dim_",
        "               tables are the history of branches, products and dates; the fct_",
        "               tables are the day's totals.",
        "",
        "logs/          The diary. For each stage there is a .log (one line per step, with the",
        "               time and how long it took) and a .json (the same run as a record: the",
        "               counts, the outcome of every check, and the decision).",
        "",
        "Reading the logs",
        "----------------",
        "Each line is:  time | level | [stage] | step | message.",
        "The stage is on every line, so a line read on its own still says whether it came from",
        "the extraction or the transformation.",
        "The steps run in order - the checks, then each table read, then validation, then the",
        "decision - so a line's position tells you what the pipeline was doing when it got",
        "there. A run that failed ends with a line marked ERROR and no .json, because a record",
        "is only written for a run that finished.",
        "",
        "Row counts",
        "----------",
        "extracted:",
    ]
    for table, count in extracted.items():
        lines.append(f"  {table:<32} {count:>5} row(s)")
    lines.append("transformed:")
    for table, count in transformed.items():
        lines.append(f"  {table:<32} {count:>5} row(s)")
    lines += [
        "",
        f"{log_files} log file(s) were copied.",
        "",
        "What this pack is not",
        "---------------------",
        "It is a snapshot for reading, not a backup and not a second source of truth. The",
        "database holds the data of record; delete this zip and nothing is lost. It exists so",
        "that someone with no database, no repository and no credentials can still see what",
        "was read, what was published, and how the pipeline got from one to the other.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Build the pack from the command line."""
    parser = argparse.ArgumentParser(
        prog="psync_extract.datapack",
        description="Zip one business day's extracted data, transformed data and logs.",
    )
    parser.add_argument("--date", type=date.fromisoformat, required=True,
                        help="business date to pack, YYYY-MM-DD")
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="the evidence folder; defaults to PSYNC_DATA_DIR, then <repo>/data")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None,
                        help="the date in the file name; defaults to today")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(
            **({"psync_data_dir": args.data_dir} if args.data_dir else {})
        )
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(
            settings.psync_target_dsn,
            connect_timeout=settings.connect_timeout_seconds,
        ) as conn:
            result = build_pack(conn, settings.psync_data_dir, args.date, as_of=args.as_of)
    except PackError as exc:
        print(f"pack error: {exc}", file=sys.stderr)
        return 1

    print(f"pack        {result.path}")
    print(f"extracted   {result.extracted} row(s)")
    print(f"transformed {result.transformed} row(s)")
    print(f"logs        {result.log_files} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
