<!--
STAGE 2 — BATCH 1: three issues, ready to post.

Create them in this order; they should land as #57, #58 and #59 (the last issue was #55 and PR #56
was merged, so numbering continues from there). Each block below is one issue: post the TITLE line
as the title, and everything below the --- as the description.

They are deliberately one PR: #57 gives the package somewhere to live, #58 gives it a way to be
configured, #59 gives it a schema to write into. Nothing else can start until all three exist.
-->

---

TITLE: [Transformation] Scaffold the psync_transform package

---

## Why

Stage 2 has a published contract — `docs/Transformation/Data-Transformation-Documentation-for-PRINTSYNC.md`
— and no code. Start where Stage 1 started: a package that exists, imports, and has a version, so
every later issue has somewhere to add a module.

## Task

- Add `pipeline/src/psync_transform/__init__.py`, with a module docstring that states the stage's
  input (the handover, never PRINTSYNC) and points at the document its section references cite.
- Export `__version__ = "0.1.0"`.
- Update the distribution description in `pipeline/pyproject.toml` to cover both stages.
- **Do not rename the distribution** (`psync-extract`). Renaming it would force a reinstall in every
  environment for no functional gain; the name is recorded here as a decision, not an oversight.

## Done when

- [ ] `python -c "import psync_transform; print(psync_transform.__version__)"` prints `0.1.0`.
- [ ] `python -c "import psync_extract"` still works — the new package disturbs nothing in Stage 1.
- [ ] No reinstall was needed: the editable install points at `pipeline/src`, so a new top-level
      package is importable immediately.

## Depends on

Nothing. This is the first issue of the stage.

---

TITLE: [Transformation] Configure the transformation stage

---

## Why

A batch needs a connection, a day, a demand window and a reject limit before it can do anything.
Everything else about the batch — the look-back, the parent extraction run, the window — comes from
the handover and from `pipeline_runs`, and must not be configured a second time here.

## Task

- Add `psync_transform/config.py`: `Settings`, `load_settings`, `ConfigurationError`, `code_version()`.
- Fields: `PSYNC_TARGET_DSN` (required), `PIPELINE_NAME`, `BUSINESS_DATE`, `PARENT_RUN_ID`,
  `RUN_TIMEZONE`, `DEMAND_WINDOW_DAYS` (default 7), `MAX_REJECT_RATE_PERCENT` (default 1),
  `CONNECT_TIMEOUT_SECONDS`.
- Validate at startup, by variable name: DSN and pipeline name not blank; a known IANA time zone;
  `DEMAND_WINDOW_DAYS >= 1` (a zero-day window divides by zero in rule B-13); the reject rate
  between 0 and 100; `PARENT_RUN_ID` a UUID when it is given.
- Do **not** import `psync_extract.config`. The two stages share one `.env` field and nothing else;
  importing one stage's configuration into the other lets a Stage 1 change alter Stage 2 silently.
- Do **not** add a look-back knob. The batch window is `[business_date - lookback_days, business_date]`,
  and `lookback_days` is read from the parent run's `pipeline_runs` row.

## Done when

- [ ] `load_settings()` reads `pipeline/.env` and, with no date given, resolves yesterday in
      `Asia/Manila` — the day a 01:30 batch has just finished.
- [ ] `DEMAND_WINDOW_DAYS=0` raises `ConfigurationError` naming the variable.
- [ ] `MAX_REJECT_RATE_PERCENT=140` raises `ConfigurationError` naming the variable.
- [ ] `code_version()` returns `psync_transform 0.1.0 / rules 1.0`.

## Depends on

#57.

---

TITLE: [Transformation] Create the transformation schema

---

## Why

The contract's §6.1 defines eleven tables. Nothing can be built, profiled or validated until they
exist, and the constraints in them are the second line of defence behind the document's checks:
a figure that contradicts itself should not be storable at all.

## Task

- Add `pipeline/migrations/003_transformation_schema.sql`. A new file — `001` and `002` are applied
  and immutable.
- Four dimensions (`dim_date`, `dim_branch`, `dim_item`, `dim_order_status`), four facts
  (`fct_daily_sales`, `fct_daily_product_demand`, `fct_daily_stock_snapshot`, `fct_daily_order_status`),
  `quarantine_rows`, `transformation_runs`, `transformation_rule_counts`.
- Seed `dim_order_status` with the six statuses in funnel order — seeded, never derived, so a
  seventh status at the source fails check T16 instead of becoming a row.
- Constraints that state the document's identities: the three money identities on `fct_daily_sales`
  (§6.1), `stock_status` against its thresholds (B-11), `gross_profit` only at 100 % cost coverage
  (B-10), and exactly one current version per natural key (T15).
- `transformation_runs.parent_run_id` references `pipeline_runs.run_id` **logically, not by foreign
  key**: that table's natural key is `(run_id, COALESCE(table_name, '__run__'))`, so there is no
  single column to point at.

## Done when

- [ ] `python -m psync_extract.db migrate` reports `applied: 003_transformation_schema`, and
      `schema_migrations` lists all three versions.
- [ ] All eleven tables exist; `dim_order_status` holds six rows in funnel order.
- [ ] A `fct_daily_sales` row whose `gross_revenue <> net_revenue + tax_total` is rejected.
- [ ] A `fct_daily_stock_snapshot` row whose `stock_status` disagrees with its numbers is rejected.
- [ ] Two `is_current` versions of one `item_ref` cannot both exist.

## Depends on

Nothing beyond the migrator, which already exists.
