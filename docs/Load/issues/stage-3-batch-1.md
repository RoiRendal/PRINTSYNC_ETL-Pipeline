<!--
STAGE 3 — BATCH 1: two issues, ready to post.

Create them in this order; they should land as #123 and #124 (the last issue was #121 and PR #122
was merged, so numbering continues from there). Each block below is one issue: post the TITLE line
as the title, and everything below the --- as the description.

They are deliberately one PR: #123 gives the package somewhere to live and a way to be configured,
#124 gives it a separate database to write into. Nothing else can start until both exist.

The specification — docs/Load/Data-Load-Documentation-for-PRINTSYNC.md revision 1.0 — and this
plan go up on main before these issues are created.
-->

---

TITLE: [Load] Scaffold the psync_load package

---

## Why

Stage 3 has a published contract and no code. Start where Stages 1 and 2 started: a package that
exists, imports, and can resolve its configuration, so every later issue has somewhere to add a
module.

## Task

- Add `pipeline/src/psync_load/__init__.py` with a module docstring stating this stage's input —
  the eight `dim_*` / `fct_*` tables handed over by Stage 2, never PRINTSYNC — and pointing at the
  document its section references cite. Export `__version__ = "0.1.0"`.
- Add `psync_load/config.py`: `Settings`, `load_settings`, `ConfigurationError`, `code_version()`.
  Fields: `PSYNC_ANALYTICS_DSN` (the Stage 2 database, read), `PSYNC_WAREHOUSE_DSN` (the reporting
  database, write), `PIPELINE_NAME`, `BATCH_ID`, `RUN_TIMEZONE`, `PSYNC_DATA_DIR`,
  `LOCK_TIMEOUT_SECONDS` (30), `STATEMENT_TIMEOUT_SECONDS` (300),
  `MAX_REJECT_RATE_PERCENT` (1), `CONNECT_TIMEOUT_SECONDS` (10).
- Derive the log directory from the data dir as `<data dir>/logs/load/`, so all three stages share
  one evidence folder and cannot diverge.
- Add `psync_load/__main__.py` with `--batch BATCH_ID`; for now it resolves and prints the
  configuration. The loader itself arrives in batch 3.
- Update the distribution description in `pipeline/pyproject.toml` to cover all three stages.
  **Do not rename the distribution** (`psync-extract`): a rename would force a reinstall in every
  environment for no functional gain. Record that as a decision in a comment.
- Keep Stage 3's config and db modules its own. Do not import the other stages' modules; a shared
  module would let a change on one side reach the other without anyone noticing.

## Done when

- [ ] `python -c "import psync_load; print(psync_load.__version__)"` prints `0.1.0`.
- [ ] `python -m psync_load --batch TRF_20261024_d031cb6c` prints the resolved configuration
      without a password.
- [ ] `python -c "import psync_extract, psync_transform"` still works — nothing earlier is
      disturbed, and no reinstall was needed.

## Depends on

Nothing. This is the first issue of the stage.

---

TITLE: [Load] Create the warehouse database, roles and schema

---

## Why

Stage 2 already publishes the finished tables into `psync_analytics`. Without a separate target
there is no load stage — only a second description of the same tables. §1.2 names the target, and
§2 names the tables and their columns.

## Task

- Add `pipeline/warehouse_bootstrap.sql`, a one-off operator script (run under the instance owner,
  not by the nightly loader): create database `psync_warehouse`; create `psync_loader` with
  `CONNECT`, `USAGE` and `SELECT`/`INSERT`/`UPDATE`/`DELETE` via `ALTER DEFAULT PRIVILEGES` but
  **no DDL**; keep `psync_pipeline` unable to write here. No password appears in the file —
  credentials are set out of band, as §1.5 requires. `CREATE DATABASE` cannot run inside a
  transaction, so this file is **not** a migration.
- Add `pipeline/warehouse_migrations/005_warehouse_schema.sql`: the eight reporting tables from §2, with the
  same columns, types, primary keys, foreign keys and check constraints as Stage 2's migration
  `003`, so a value cannot be silently altered in the warehouse. Add the three load bookkeeping
  columns — `load_batch_id text NOT NULL`, `load_run_id uuid NOT NULL`,
  `loaded_at timestamptz NOT NULL` — to every reporting table.
- Add `load_runs`, `load_rejects` and `load_validation_results` with the fields in §6.1 and §7.
- Add `psync_load/db/` with `connect_source`, `connect_warehouse` and a `migrate` command:
  `python -m psync_load.db migrate`. It applies migrations in filename order, records each in
  `schema_migrations` so a second run is a no-op, and **refuses to run when the two DSNs resolve to
  the same database** — PRINTSYNC is never modified (§1.6 of the extraction specification).
- Indexes named in §2, and nothing else: the stage does not add reporting indexes it cannot justify.

## Done when

- [ ] `python -m psync_load.db migrate` applies `005` and a second run reports zero applied.
- [ ] `psync_loader` can `INSERT` into `dim_date` and cannot `CREATE TABLE`.
- [ ] `psync_pipeline` cannot write to `psync_warehouse`.
- [ ] A configuration with both DSNs pointing at the same database is refused with a clear message.

## Depends on

#123 — merged.
