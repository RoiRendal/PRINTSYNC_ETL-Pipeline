# PRINTSYNC_ETL-Pipeline

Standalone ETL pipeline for the PRINTSYNC printing shop: the nightly analytics batch
pipeline `psync_nightly_analytics` (Extract → Transform → Load).

**Stages 1 (Extract) and 2 (Transform) are complete.** Stage 3 (Load) is out of scope for the
current laboratory. Each stage's specification is the contract its code implements — code follows
the document, never the other way round:

- [Extraction specification](docs/Extraction/Data-Extraction-Documentation-for-PRINTSYNC.md) — Stage 1, implemented (rev 1.8)
- [Transformation specification](docs/Transformation/Data-Transformation-Documentation-for-PRINTSYNC.md) — Stage 2, implemented (rev 1.10)

## Constraints

The course's ETL project rules, and where each one is enforced:

| Constraint | How this pipeline holds it |
| --- | --- |
| Batch only | One business day per run. `python -m psync_extract --date YYYY-MM-DD` reads a fixed window and exits; there is no listener, poll loop or stream in either package. |
| No Pandas | No Pandas, NumPy, Polars or Dask in the dependencies or the imports. Aggregation is set-based SQL in PostgreSQL, which is where the data already is. |
| No Spark / Airflow / Kafka | None of them. The runtime dependencies are Psycopg and Pydantic Settings; Prefect is an **optional extra** (`pip install -e ".[orchestration]"`), so the base install contains no orchestration framework. |
| Single machine | Both databases run locally — source `127.0.0.1:54322`, target `localhost:5432` — and the evidence folder is files on disk. Nothing is distributed. |
| Read-only on tables | Three layers: the source login is read-only, every session sets `default_transaction_read_only = on` before its first read, and no module in `psync_extract` can issue DDL or DML. Writes go only to `psync_analytics`. |

## Deployment boundary

This project is developed and run separately from PRINTSYNC. It reads from the PRINTSYNC
database over a **read-only** connection and writes only to its own database,
`psync_analytics`. No PRINTSYNC code is imported, and no PRINTSYNC file, table, column or
trigger is created or changed. See §1.6 of the specification.

## Running the stages

All pipeline code lives in `pipeline/`, so work from there. Each stage is one command:

```bash
python -m psync_extract   --date 2026-10-18   # Stage 1: extract one business day
python -m psync_transform --date 2026-10-18   # Stage 2: transform that day's handover
```

Both exit 0 when the run may be handed over and 1 when it may not, so a scheduler notices.
Stage 2 reads nothing from PRINTSYNC — its input is Stage 1's handover (the staged rows selected
by `run_id`, plus the manifest Stage 1 writes on approval).

## The evidence folder

Everything a run leaves behind lives in one folder, `data/`, named by `PSYNC_DATA_DIR` (default:
the repository's `data/`). The layout is tracked in git; the artifacts are not.

```
data/logs/extract/        one .log and one .json per extraction run, sharing a stem
data/logs/transform/      the same pair per transformation batch
data/handover/            the manifest Stage 1 writes on approval and Stage 2 reads
data/exports/<batch_id>/  the quarantine as CSV, with a reconciliation and a README
data/packs/               one business day's data and its logs, zipped for inspection
data/submission/          a dated zip of the whole folder
```

Three commands produce the portable artifacts, and none of them runs a batch:

```bash
python -m psync_transform --export TRF_20261018_1463a0d4   # the quarantine, as CSV
python -m psync_extract.datapack --date 2026-10-18         # the day's data and logs, together
python -m psync_extract.submission --as-of 2026-11-01      # the whole folder, as one zip
```

A run leaves **two** log files with one stem. `<stem>.json` is the record: written once, at the
end, atomically. `<stem>.log` is the narrative: one line per step with the time and how long it
took, flushed as it happens — which is why a run that fails still says how far it got, ending in a
`FAILED` line with no record beside it.

## Repository layout

```
docs/Extraction/        the extraction specification - the contract Stage 1 implements
docs/Transformation/    the transformation specification, its implementation plan and issue texts
docs/Evidence/          the evidence batches: one file per batch of issues
pipeline/               the entire ETL pipeline: two packages, psync_extract and psync_transform
data/                   the evidence folder - logs, handover, exports, packs, submission
```

## How work is tracked

Every change addresses exactly one GitHub issue; every issue cites the document section it
implements. Branches are named `issue-<N>-<short-slug>` and pull requests close their issue
with `Closes #N`. Stage 2's implementation plan records how the work was batched and evidenced:

- [Transformation implementation plan](docs/Transformation/Implementation-Plan-and-Issue-Breakdown.md)
