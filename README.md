# PRINTSYNC_ETL-Pipeline

Standalone ETL pipeline for the PRINTSYNC printing shop: the nightly analytics batch
pipeline `psync_nightly_analytics` (Extract → Transform → Load).

**Stages 1 (Extract) and 2 (Transform) are complete.** Stage 3 (Load) is out of scope for the
current laboratory. Each stage's specification is the contract its code implements — code follows
the document, never the other way round:

- [Extraction specification](docs/Extraction/Data-Extraction-Documentation-for-PRINTSYNC.md) — Stage 1, implemented (rev 1.6)
- [Transformation specification](docs/Transformation/Data-Transformation-Documentation-for-PRINTSYNC.md) — Stage 2, implemented (rev 1.5)

## Constraints

The course's ETL project rules, and where each one is enforced:

| Constraint | How this pipeline holds it |
| --- | --- |
| Batch only | One business day per run. `python -m psync_extract --date YYYY-MM-DD` reads a fixed window and exits; there is no listener, poll loop or stream in either package. |
| No Pandas | No Pandas, NumPy, Polars or Dask in the dependencies or the imports. Aggregation is set-based SQL in PostgreSQL, which is where the data already is. |
| No Spark / Airflow / Kafka | None of them. The runtime dependencies are Psycopg and Pydantic Settings; Prefect is an **optional extra** (`pip install -e ".[orchestration]"`), so the base install contains no orchestration framework. |
| Single machine | Both databases run locally — source `127.0.0.1:54322`, target `localhost:5432` — and the handover and logs are files on disk. Nothing is distributed. |
| Read-only on tables | Three layers: the source login is read-only, every session sets `default_transaction_read_only = on` before its first read, and no module in `psync_extract` can issue DDL or DML. Writes go only to `psync_analytics`. |

## Deployment boundary

This project is developed and run separately from PRINTSYNC. It reads from the PRINTSYNC
database over a **read-only** connection and writes only to its own database,
`psync_analytics`. No PRINTSYNC code is imported, and no PRINTSYNC file, table, column or
trigger is created or changed. See §1.6 of the specification.

## Running the stages

All pipeline code lives in `pipeline/`, so work from there. Each stage is one command:

```bash
python -m psync_extract   --date 2026-10-17   # Stage 1: extract one business day
python -m psync_transform --date 2026-10-17   # Stage 2: transform that day's handover
```

Both exit 0 when the run may be handed over and 1 when it may not, so a scheduler notices.
Stage 2 reads nothing from PRINTSYNC — its input is Stage 1's handover (the staged rows selected
by `run_id`, plus the manifest Stage 1 writes on approval).

## Repository layout

```
docs/Extraction/        the extraction specification - the contract Stage 1 implements
docs/Extraction/issues/ the Stage 1 issue texts (local working set)
docs/Transformation/    the transformation specification, its implementation plan and issue texts
pipeline/               the entire ETL pipeline: two packages, psync_extract and psync_transform
```

## How work is tracked

Every change addresses exactly one GitHub issue; every issue cites the document section it
implements. Branches are named `issue-<N>-<short-slug>` and pull requests close their issue
with `Closes #N`. Stage 2's implementation plan records how the work was batched and evidenced:

- [Transformation implementation plan](docs/Transformation/Implementation-Plan-and-Issue-Breakdown.md)
