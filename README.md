# PRINTSYNC_ETL-Pipeline

Standalone ETL pipeline for the PRINTSYNC printing shop: the nightly analytics batch pipeline
`psync_nightly_analytics` (Extract → Transform → Load).

**All three stages are complete.** Each stage's specification is the contract its code implements —
code follows the document, never the other way round:

| Stage | Package | Specification | Produces |
| --- | --- | --- | --- |
| 1 · Extract | `psync_extract` | [rev 1.10](docs/Extraction/Data-Extraction-Documentation-for-PRINTSYNC.md) | Seven `stg_*` tables and a handover manifest |
| 2 · Transform | `psync_transform` | [rev 1.12](docs/Transformation/Data-Transformation-Documentation-for-PRINTSYNC.md) | Four `dim_*` and four `fct_*` tables in `psync_analytics` |
| 3 · Load | `psync_load` | [rev 1.5](docs/Load/Data-Load-Documentation-for-PRINTSYNC.md) | The same eight tables in `psync_warehouse`, verified and ledgered |

## Constraints

The course's ETL project rules, and where each one is enforced:

| Constraint | How this pipeline holds it |
| --- | --- |
| Batch only | One business day per run. Each stage reads a fixed window and exits; there is no listener, poll loop or stream in any of the three packages. |
| No Pandas | No Pandas, NumPy, Polars or Dask in the dependencies or the imports. Aggregation is set-based SQL in PostgreSQL, which is where the data already is. |
| No Spark / Airflow / Kafka | None of them. The runtime dependencies are Psycopg and Pydantic Settings; Prefect is an **optional extra** (`pip install -e ".[orchestration]"`), so the base install contains no orchestration framework. |
| Single machine | The pipeline runs on one host. Both pipeline databases are local PostgreSQL; the PRINTSYNC source is either a local Supabase stack or the hosted project over TLS, read-only either way. The evidence folder is files on disk. |
| Read-only on tables | Three layers: the source login is read-only, every session sets `default_transaction_read_only = on` before its first read, and no module in `psync_extract` can issue DDL or DML against PRINTSYNC. Writes go only to `psync_analytics` and `psync_warehouse`. |

## Deployment boundary

This project is developed and run separately from PRINTSYNC. It reads from the PRINTSYNC database
over a **read-only** connection and writes only to its own two databases:

| Database | Written by | Read by |
| --- | --- | --- |
| `psync_analytics` | Stage 1 (staging) and Stage 2 (the dimensional tables) | Stage 3, in a session pinned read-only |
| `psync_warehouse` | Stage 3 only, as a restricted DML role with no DDL | Reports and analysis |

No PRINTSYNC code is imported, and no PRINTSYNC file, table, column or trigger is created or
changed. See §1.6 of the extraction specification.

## Running the stages

All pipeline code lives in `pipeline/`, so work from there. Each stage is one command:

```bash
python -m psync_extract   --date 2026-10-24                  # Stage 1: extract one business day
python -m psync_transform --date 2026-10-24                  # Stage 2: transform that day's handover
python -m psync_load      --batch TRF_20261024_d031cb6c      # Stage 3: load an approved batch
```

Each exits 0 when its result may be handed on and 1 when it may not, so a scheduler notices.

- **Stage 2** reads nothing from PRINTSYNC. Its input is Stage 1's handover: the staged rows selected
  by `run_id`, plus the manifest Stage 1 writes on approval.
- **Stage 3** reads nothing from PRINTSYNC either. Its input is Stage 2's ledger row for one
  `batch_id` — no manifest file exists on that side — and it writes to a separate database. It loads
  the whole batch in one transaction, runs L1–L6 before opening it and L7–L13 before committing, and
  records a verdict. Only `APPROVED` and `APPROVED WITH WARNING` publish; the other two roll back.

## The evidence folder

Everything a run leaves behind lives in one folder, `data/`, named by `PSYNC_DATA_DIR` (default: the
repository's `data/`). The layout is tracked in git; the artifacts are not.

```
data/logs/extract/        one .log and one .json per extraction run, sharing a stem
data/logs/transform/      the same pair per transformation batch
data/logs/load/           the same pair per load attempt, stemmed on batch id and run id
data/handover/            the manifest Stage 1 writes on approval and Stage 2 reads
data/exports/<batch_id>/  the quarantine as CSV, with a reconciliation and a README
data/snapshots/<batch>/   the reporting tables as CSV, taken before a load writes anything
data/packs/               one business day's data and its logs, zipped for inspection
data/submission/          a dated zip of the whole folder
```

Four commands produce the portable artifacts, and none of them runs a batch:

```bash
python -m psync_transform --export TRF_20261024_d031cb6c      # the quarantine, as CSV
python -m psync_extract.datapack --date 2026-10-24            # the day's data and logs, together
python -m psync_extract.submission --as-of 2026-11-11         # the whole folder, as one zip
python -m psync_load.retention --dry-run                      # what the retention job would delete
```

**Two lifetimes.** Operational detail — the log narratives, the records and the snapshots — lives 90
days, or 7 for a snapshot. The `load_runs` ledger and its rejects live two years, because they are
the evidence that a published day was produced correctly. The submission archive carries all five
required folders: one per stage, plus the handover and the exports.

A run leaves **two** log files with one stem. `<stem>.json` is the record: written once, at the end,
atomically. `<stem>.log` is the narrative: one line per step with the time and how long it took,
flushed as it happens — which is why a run that fails still says how far it got, ending in an
`ERROR` line with no record beside it.

## Repository layout

```
docs/Extraction/        the extraction specification - the contract Stage 1 implements
docs/Transformation/    the transformation specification, its implementation plan and issue texts
docs/Load/              the load specification, its implementation plan and issue texts
docs/Evidence/          the evidence batches: one file per batch of issues
pipeline/src/           the three packages: psync_extract, psync_transform, psync_load
pipeline/migrations/    the Stage 1 and 2 schema, applied to psync_analytics
pipeline/warehouse_migrations/  the Stage 3 schema, applied to psync_warehouse
pipeline/warehouse_bootstrap.sql  one-off: the warehouse database and its two roles
data/                   the evidence folder - logs, handover, exports, snapshots, packs, submission
```

`pipeline/warehouse_migrations/` is deliberately separate from `pipeline/migrations/`: Stage 1's
applier globs the latter and applies everything it finds to `psync_analytics`, so the reporting
tables there would be created in the wrong database.

## How work is tracked

Every change addresses exactly one GitHub issue; every issue cites the document section it
implements. Branches are named `issue-<N>-<short-slug>` and pull requests close their issue with
`Closes #N`. Each stage's implementation plan records how the work was batched and evidenced:

- [Extraction implementation plan](docs/Implementation-Plan-and-Issue-Breakdown.md)
- [Transformation implementation plan](docs/Transformation/Implementation-Plan-and-Issue-Breakdown.md)
- [Load implementation plan](docs/Load/Implementation-Plan-and-Issue-Breakdown.md)
