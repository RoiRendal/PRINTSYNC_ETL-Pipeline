# Data Load Documentation

**PRINTSYNC Nightly Analytics Batch Pipeline**
Pipeline ID · `psync_nightly_analytics` · Stage 3 of 3 (Extract → Transform → Load)
BAT-405 Analytics Application — Capstone Laboratory Activity 5
Lyell Jasmine D. Bulan · Roi C. Rendal · Ma. Erica Z. Vidal
11 November 2026

---

## Objective

Load the validated, transformed dataset handed over by Stage 2 into a reporting database, and prove
that what arrived is complete, accurate, traceable and ready for reports, dashboards and analysis.

This pipeline is **batch only**. Data is loaded in scheduled, bounded batches — one per approved
transformation batch. Streaming, micro-batch and real-time loading are out of scope. Stage 3 reads
**only** the output of Stage 2; it never connects to PRINTSYNC, never re-extracts a row and never
re-derives a number.

Like the two documents before it, this document is **the contract**. The code is built against it
issue by issue, and when the contract has to change the document is corrected first.

---

## Scope decisions (read this first)

**1. The handover is a ledger row, not a file.** Stage 2 writes no manifest — see Transformation
§10.3 and revision 1.10. Its handover is the run-level row in `transformation_runs` keyed by
`batch_id`, with `decision`, `status`, `code_version`, the window and the per-table counts, plus the
eight `dim_*` / `fct_*` tables that row accounts for. Stage 3 reads that row first and refuses to
load anything it does not name.

**2. The target is a separate database.** Stage 2 publishes into `psync_analytics`. Stage 3 loads
into `psync_warehouse`, a second PostgreSQL database on the same host. Without a separate target
there is no load stage at all — only a second description of the same tables.

**3. "Rejected" means something different here.** Stage 2's `quarantine_rows` holds records rejected
*before* transformation; the template is explicit that those are not counted again. Here,
`records_rejected` means a row the load did not write — a constraint violation, a missing dimension
member, a duplicate key. Every such row goes into `warehouse.load_rejects` with a reason and a
batch ID.

**4. No new cleaning or business logic.** Stage 3 copies published rows and reconciles them. A value
that is wrong at this point is a Stage 2 bug and is reported through §8, not repaired here.

**5. The measure of a successful load is agreement.** The target's rows, keys and amounts must equal
the handover's rows, keys and amounts. Nothing is recomputed from the source tables.

---

## 1. Load Source and Target Specification

### 1.1 Load input

| Item | Detail |
| --- | --- |
| **Name and location** | The eight business-ready tables in `psync_analytics` on `localhost:5432`: four dimensions (`dim_date`, `dim_branch`, `dim_item`, `dim_order_status`) and four facts (`fct_daily_sales`, `fct_daily_product_demand`, `fct_daily_stock_snapshot`, `fct_daily_order_status`). PostgreSQL tables, not Parquet or CSV. |
| **Transformation run ID** | `transformation_runs.run_id` on the run-level row (`table_name IS NULL`) for the batch. |
| **Batch ID** | `transformation_runs.batch_id`, e.g. `TRF_20261024_d031cb6c`. This is the key the whole load is organised around. |
| **Batch window** | `batch_window_start` … `batch_window_end`, e.g. `2026-10-21` … `2026-10-24`. Facts are loaded for this window; dimensions are loaded in full. |
| **Handover status** | Only `APPROVED` or `APPROVED WITH WARNING` with `transformation_status = 'success'` may be loaded (Stage 2 §10.1). A `REJECTED`, `MANUAL REVIEW`, `failed` or `skipped` run has no data to publish. |
| **Counts** | `transformation_runs` holds one row per table the transformation wrote, with `records_output`. For a **fact**, that is exactly the rows written for the window, and it is the number the load must reproduce. For a **dimension** it is only what that run inserted: `dim_date` reports `0` on a re-run because it inserts nothing it has already seen, and the seeded `dim_order_status` has no row at all. A dimension is therefore loaded **in full**, and its expected size is the source table's row count at load time, never `records_output`. L4 compares facts only; L8 reconciles dimensions after the load. |

The one real batch measured so far is `TRF_20261024_d031cb6c`, from the live PRINTSYNC system:
150 published rows — `dim_date` 11, `dim_branch` 2, `dim_item` 60, `dim_order_status` 6,
`fct_daily_sales` 3, `fct_daily_product_demand` 2, `fct_daily_stock_snapshot` 60,
`fct_daily_order_status` 6. Its `fct_daily_sales` carries ₱10,100.00 net revenue across two
branches, and one zero-revenue day with twelve voided sales.

### 1.2 Target system

| Item | Detail |
| --- | --- |
| **Name and purpose** | `psync_warehouse` — the reporting database. It exists so dashboards and ad-hoc analysis never read the pipeline's working tables, and so a load in progress cannot disturb a batch being transformed. |
| **DBMS** | PostgreSQL 16, the same engine as the rest of the project. No new technology is introduced. |
| **Schema** | `public`, containing the eight reporting tables and three bookkeeping tables (`load_runs`, `load_rejects`, `load_validation_results`). |
| **Ownership** | The pipeline owns this database. It is not a PRINTSYNC database and is never read by PRINTSYNC. |

### 1.3 Load method

| Item | Detail |
| --- | --- |
| **Tool** | Python 3.13 with Psycopg 3, in the `psync_load` package. SQL `COPY … TO STDOUT` on the source and `COPY … FROM STDIN` on the target — bulk, set-based, no Pandas and no row-by-row inserts. |
| **Why COPY** | The two databases cannot be joined in a single SQL statement, so the rows travel through the client. `COPY` moves them as one stream per table rather than one statement per row. |
| **Schedule** | Daily at **04:00 Asia/Manila**, after Stage 2 has completed and approved its batch. One batch per run. There is no listener, poll loop or continuous process. |
| **How data is written** | Bulk insert. Dimensions are replaced wholesale; facts are deleted for the batch window and inserted (§3.1). The whole batch is one transaction on the target. |
| **Trigger** | `python -m psync_load --batch TRF_20261024_d031cb6c`. An operator can also run it by hand; the Prefect optional extra calls the same function. |

### 1.4 Load scope

| Order | Table | Type | Rows per batch (measured) |
| --- | --- | --- | --- |
| 1 | `dim_date` | dimension | 11 |
| 2 | `dim_branch` | dimension | 2 |
| 3 | `dim_item` | dimension | 60 |
| 4 | `dim_order_status` | dimension | 6 |
| 5 | `fct_daily_sales` | fact | 3 |
| 6 | `fct_daily_product_demand` | fact | 2 |
| 7 | `fct_daily_stock_snapshot` | fact | 60 |
| 8 | `fct_daily_order_status` | fact | 6 |

Dimensions precede facts because the facts declare foreign keys to them. Expected volume at this
shop is **about 150 rows per batch**, and the load must finish within **five minutes** of starting —
a bound that is generous for this size but makes an open transaction or a lock a detectable failure
rather than an overnight hang.

### 1.5 Limitations and assumptions

| Limitation | Consequence and handling |
| --- | --- |
| Two separate databases cannot be joined in SQL | Row counts and amounts are compared in Python, not in a cross-database query. |
| The reporting role has no DDL | Migrations are applied by `python -m psync_load.db migrate` under the owner role; the nightly loader cannot create or alter a table. |
| Fact tables reference dimensions | A fact whose key is absent is rejected to `load_rejects`, not given an "Unknown" member — Stage 2 already guarantees referential integrity (T11/T12), so an orphan here is a defect, not a legitimate value. |
| Locking during business hours | The 04:00 schedule avoids the shop's trading hours. The target transaction uses `SET LOCAL lock_timeout = '30s'`; a lock that cannot be acquired fails the batch cleanly rather than waiting. |
| Storage | L5 checks free space before the load. A snapshot of the eight tables is written to `<data dir>/snapshots/<batch_id>/` before a dimension replace (§7). |
| Network | The two databases are local. A failed connection fails the batch; there is no retry across hosts. |

**Accounts and privileges** (no passwords or keys are recorded here or anywhere in this document):

| Account | Used for | Privileges |
| --- | --- | --- |
| `psync_pipeline` | Stages 1 and 2 writing their own output; Stage 3 **reading** that output; applying warehouse migrations | Owns `psync_analytics` / `psync_analytics_live` and `psync_warehouse`. On the Stage 2 database it holds full DML — it is the role that wrote the staging and mart tables — while Stage 3's connection sets `default_transaction_read_only = on` for the duration of its read. On the warehouse it holds DDL, because it creates the tables. |
| `psync_loader` | Nightly loads only | `CONNECT` on `psync_warehouse`, `USAGE` on `public`, `SELECT` / `INSERT` / `DELETE` / `UPDATE` on the eight reporting tables and the three bookkeeping tables. No `CREATE`, no `DROP`, no superuser, and **no privilege at all** on the Stage 2 database. This is the role in `PSYNC_WAREHOUSE_DSN`. |

There is no third role. `psync_pipeline` is the owner; migrations are applied under it through a one-off
`PSYNC_WAREHOUSE_DSN` override by the operator, and the nightly load never sees that connection
string. A `psync_loader` attempt to `CREATE TABLE` is refused by PostgreSQL with
`InsufficientPrivilege`.

---

## 2. Target Tables and Column Specification

The target mirrors the transformed contract (Stage 2 §6.1). Only columns the load depends on are
listed; the full column list lives in `pipeline/warehouse_migrations/005_warehouse_schema.sql`. No
rows of data are reproduced here.

That directory is **separate** from `pipeline/migrations/` on purpose: Stage 1's migration applier
globs the latter and applies everything it finds to `psync_analytics`. Putting the reporting tables
there would create them in the wrong database. The one-off `pipeline/warehouse_bootstrap.sql`,
which creates the database itself, is likewise kept outside it because `CREATE DATABASE` cannot run
inside a transaction block.

### 2.1 Overview

| Table | Type | Primary key | Foreign keys | Purpose |
| --- | --- | --- | --- | --- |
| `dim_date` | Dimension | `date_key` | none | One calendar date, so every fact has a date to join |
| `dim_branch` | Dimension | `branch_key` | none | Branch attributes and SCD Type 2 history |
| `dim_item` | Dimension | `item_key` | none | Product identity, price, cost and SCD Type 2 history |
| `dim_order_status` | Dimension | `status_key` | none | The six order statuses and their funnel order |
| `fct_daily_sales` | Fact | `(business_date, branch_key)` | `date_key`, `branch_key` | Daily sales totals per branch |
| `fct_daily_product_demand` | Fact | `(business_date, branch_key, item_key)` | `date_key`, `branch_key`, `item_key` | Demand and 30-day forecast per product |
| `fct_daily_stock_snapshot` | Fact | `(business_date, branch_key, item_key)` | `date_key`, `branch_key`, `item_key` | Stock on hand and reorder recommendation |
| `fct_daily_order_status` | Fact | `(business_date, status_key)` | `date_key`, `status_key` | Order counts by status |

### 2.2 Dimensions

**`dim_date`** — `date_key date PRIMARY KEY`; `year smallint`, `quarter smallint CHECK (1–4)`,
`month smallint CHECK (1–12)`, `month_name text`, `day_of_month smallint`, `iso_week smallint`,
`day_of_week smallint`, `day_name text`, `is_weekend boolean`, all `NOT NULL`. No surrogate column
beyond `date_key`. Index: the primary key. Reason: every fact declares a date foreign key, so a
missing date stops a fact from loading.

**`dim_branch`** — `branch_key bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY`;
`branch_id uuid NOT NULL`; `code text NOT NULL`; `name text NOT NULL`; `is_active boolean NOT NULL`;
`vat_rate numeric(5,2) NOT NULL CHECK (0–100)`; `currency_symbol text NOT NULL`;
`time_zone text NOT NULL`; `valid_from date NOT NULL`; `valid_to date`;
`is_current boolean NOT NULL`. Constraints: `UNIQUE (branch_id, valid_from)`,
`CHECK (valid_to IS NULL OR valid_to > valid_from)`, and a check tying `is_current` to a null
`valid_to`. Indexes: the natural-key unique index and `branch_id` for lookups. Reason: the fact
tables carry `branch_key`, and the VAT rate is needed to explain the tax figures already loaded.

**`dim_item`** — `item_key bigint IDENTITY PRIMARY KEY`; `item_ref text NOT NULL CHECK (item_ref ~
'^(name|inventory):')`; `item_name text NOT NULL`; `inventory_item_id uuid`; `sku text`;
`category text NOT NULL`; `uom text`; `unit_price numeric(14,2)`; `unit_cost numeric(14,2)`;
`is_catalogue_item boolean NOT NULL`; `valid_from date NOT NULL`; `valid_to date`;
`is_current boolean NOT NULL`. Constraints: `UNIQUE (item_ref, valid_from)`, non-negative money,
the validity interval, and `is_catalogue_item = (inventory_item_id IS NOT NULL)`. Indexes: the
natural-key unique index and `item_ref`. Reason: 93.4 % of sale lines have no catalogue link, so
the product identity is the normalised name; the warehouse must carry that identity verbatim.

**`dim_order_status`** — `status_key smallint PRIMARY KEY`; `status_name text UNIQUE NOT NULL`;
`status_order smallint NOT NULL CHECK (1–6)`; `is_backlog boolean NOT NULL`;
`is_terminal boolean NOT NULL`; `CHECK (NOT (is_backlog AND is_terminal))`. Static: seeded by the
migration, never derived. Reason: `fct_daily_order_status` references it.

### 2.3 Facts

**`fct_daily_sales`** — `business_date date NOT NULL REFERENCES dim_date`,
`branch_key bigint NOT NULL REFERENCES dim_branch`; counters `transaction_count`, `line_count`,
`units_sold`, `voided_count` (`integer NOT NULL CHECK >= 0`); money columns `gross_revenue`,
`net_revenue`, `tax_total`, `line_revenue_total`, `discount_total`, `line_discount_total`,
`unallocated_discount`, `cogs`, `revenue_costed`, `settled_total`, `cash_total`, `card_total`,
`custom_order_total`, `voided_amount`, `gross_profit_costed` (`numeric(14,2) NOT NULL CHECK >= 0`);
`cogs_coverage_pct numeric(6,2) CHECK (0–100)`; nullable `gross_profit`, `margin_pct`,
`margin_pct_costed`, `avg_transaction_value`. `PRIMARY KEY (business_date, branch_key)`. Four
identity checks — `gross_revenue = net_revenue + tax_total`, the discount identity, the unallocated
discount identity and the settlement identity — are carried over unchanged, so a value cannot be
silently altered in the warehouse. Index: `business_date` for the reporting query pattern. Reason:
this is the table a revenue dashboard reads first.

**`fct_daily_product_demand`** — `(business_date, branch_key, item_key)` primary key and foreign
keys; `line_count`, `quantity_sold` integers; `line_revenue`, `discount_total`, `revenue`, `cogs`
numeric; `is_costed boolean NOT NULL`; `demand_window_days smallint NOT NULL CHECK >= 1`;
`avg_daily_demand`, `forecast_demand_30d numeric(10,2)`; `CHECK (revenue = line_revenue -
discount_total)`. Reason: demand and forecast per product per day.

**`fct_daily_stock_snapshot`** — `(business_date, branch_key, item_key)` primary key and foreign
keys; `stock_on_hand`, `reorder_level`, `recommended_reorder` integers with non-negative checks;
`stock_status text NOT NULL` constrained to the three known statuses. Reason: the shop's stock
position at the end of the day.

**`fct_daily_order_status`** — `(business_date, status_key)` primary key; foreign keys to
`dim_date` and `dim_order_status`; integer order counts with non-negative checks. Reason: the order
funnel by day.

### 2.4 Columns the load depends on

Every reporting table gains three **load bookkeeping** columns, added by migration `005`. They are
metadata about the load, not business data, and are excluded from the source-to-target comparison:

| Column | Type | Purpose |
| --- | --- | --- |
| `load_batch_id` | `text NOT NULL` | The `batch_id` that wrote the row. The match key for delete-by-batch and the duplicate-batch check (L6). |
| `load_run_id` | `uuid NOT NULL` | The run that wrote the row, for lineage back to `load_runs`. |
| `loaded_at` | `timestamptz NOT NULL` | When the row was written. |

**Match key** per table is its primary key. **History columns** for the two SCD Type 2 dimensions
are `valid_from` (inclusive), `valid_to` (exclusive, `NULL` means current) and `is_current`; the
load copies them unchanged and never re-evaluates them. **Batch ID column** is `load_batch_id` on
every table, so a rerun can find exactly the rows it previously wrote.

### 2.5 Load bookkeeping tables

`load_runs` (§6.1) holds one run-level row and one row per target table per batch.
`load_rejects` holds rows the load did not write, with `batch_id`, `table_name`, `rule_id`, `reason`,
`payload jsonb` and `rejected_at`. `load_validation_results` holds the L1–L13 outcomes as `jsonb`
per run. All three are owned by the pipeline and are never read by reports.

---

## 3. Load Strategy and Rules

### 3.1 Load type and write logic

| Table | Load type | Write logic | Match key | On failure |
| --- | --- | --- | --- | --- |
| `dim_date` | Full | `DELETE` all, bulk `INSERT` | `date_key` | Roll back whole batch, stop |
| `dim_branch` | Full | `DELETE` all, bulk `INSERT` | `branch_key` | Roll back whole batch, stop |
| `dim_item` | Full | `DELETE` all, bulk `INSERT` | `item_key` | Roll back whole batch, stop |
| `dim_order_status` | Full | `DELETE` all, bulk `INSERT` | `status_key` | Roll back whole batch, stop |
| `fct_daily_sales` | Incremental | `DELETE` where `business_date` in window, bulk `INSERT` | `(business_date, branch_key)` | Roll back whole batch, stop |
| `fct_daily_product_demand` | Incremental | `DELETE` where `business_date` in window, bulk `INSERT` | `(business_date, branch_key, item_key)` | Roll back whole batch, stop |
| `fct_daily_stock_snapshot` | Incremental | `DELETE` where `business_date` in window, bulk `INSERT` | `(business_date, branch_key, item_key)` | Roll back whole batch, stop |
| `fct_daily_order_status` | Incremental | `DELETE` where `business_date` in window, bulk `INSERT` | `(business_date, status_key)` | Roll back whole batch, stop |

**Why dimensions are a full load.** They are small — 79 rows in the measured batch — and they carry
SCD Type 2 history. An incremental upsert would leave behind a version that Stage 2 later closed,
so the warehouse would disagree with the source dimension. Replacing the whole table each night is
cheaper than reconciling it and cannot drift.

**Why facts are incremental.** Facts accumulate one day at a time. Only the batch window is
replaced, so earlier published days are untouched. `load_batch_id` still records which batch wrote
each row, so a rerun's delete can be scoped exactly.

### 3.2 Handling of changing data

- **SCD Type 2 dimensions** are copied verbatim. Stage 3 does not open or close a version; it would
  be re-deriving a business decision. A closed version stays closed in the warehouse.
- **Deleted or inactive records** are likewise copied verbatim: `dim_branch.is_active` is an
  attribute, not a delete instruction. There is no soft-delete flag in the load stage.
- **Late-arriving records** are Stage 1's and Stage 2's concern. If Stage 2 republishes a batch
  with a wider window, Stage 3 deletes that window and reloads it. Stage 3 never invents a date.
- **A handover whose schema differs from the target** fails L2 and is rejected before a single row
  is written. Column names, presence and type families are compared against migration `005`; an
  added column in the source is ignored, a missing or retyped column stops the batch. There is no
  "load and flag" path — a shape change is a contract change and the document moves first.

### 3.3 Load order and dependencies

Dimensions are loaded first, in the order `dim_date` → `dim_branch` → `dim_item` →
`dim_order_status`, then facts in the order they appear in §1.4. `dim_date` comes first because all
four facts reference it. The delete phase runs in **reverse** order — facts, then dimensions — so
no foreign key is left pointing at a deleted parent at any point inside the transaction.

**A fact with no matching dimension member is rejected**, recorded in `load_rejects` with rule
`L-10` and counted in `records_rejected`. No "Unknown" member is manufactured: Stage 2's T11 and
T12 already proved referential integrity, so an orphan at this point means the handover and the
target have diverged, and guessing a member would hide it.

### 3.4 Transaction and rollback handling

The **whole batch is one transaction** on `psync_warehouse`. One connection, one `BEGIN`, one
`COMMIT` at the end. `SET LOCAL lock_timeout = '30s'` and `SET LOCAL statement_timeout = '300s'`
bound it. The source connection is read-only and is never part of the transaction.

On any failure — a failed check, a `COPY` error, a constraint violation, a process crash — the
transaction rolls back and no partial load remains. Psycopg's connection context manager rolls back
on an exception; the process being killed leaves the transaction uncommitted, which PostgreSQL
rolls back when the connection closes. The `.log` narrative is streamed to disk as it happens, so
even a run that never commits says how far it got.

### 3.5 Rerun and idempotency

A batch is identified by `batch_id`. Before loading facts, the loader deletes every row whose
`business_date` falls in the batch window; before loading dimensions, it deletes the whole table.
Loading the same batch twice therefore writes the same rows twice, not two sets.

L6 refuses to publish a batch already recorded as `success` in `load_runs` — a **deliberate
difference from Stage 2**, which rebuilds on a rerun. Here the reporting database is the published
product; a second successful load of the same batch is a duplicate publication, and a reader should
say so rather than silently doing it. Recovery after a `FAILED` or `REJECTED` batch is allowed:
there is nothing to duplicate, because the failed transaction rolled back.

---

## 4. Pre-Load Validation Checks

Every check has a name, a target, a purpose, a measurable criterion and a severity. All six run
**before** the target transaction opens. L1–L6 are critical: a failure stops the batch with no
writes.

| ID | Check name | Target | Purpose | Validation criteria | Severity |
| --- | --- | --- | --- | --- | --- |
| L1 | Target connection and write permission | `psync_warehouse` | Prove the load can start and write | Connection succeeds within `connect_timeout`; `has_table_privilege` reports `INSERT`, `UPDATE`, `DELETE` on all eight tables for the current role | Critical |
| L2 | Schema match | All eight target tables | Prevent type or column errors | Every required column exists with its expected type family; every constraint and index named in §2 is present. Extra columns are ignored | Critical |
| L3 | Handover status | `transformation_runs` run-level row | Load approved data only | A row exists for `batch_id`, `decision IN ('APPROVED', 'APPROVED WITH WARNING')`, `transformation_status = 'success'` | Critical |
| L4 | Input record counts | The four fact tables and their `transformation_runs` rows | Confirm the handover's numbers are still true | For each fact table, `count(*)` of the rows in the window equals `records_output`. Dimensions are **not** compared: their `records_output` counts rows that run inserted, not rows to load (§1.1), and L8 reconciles them after the load. A mismatch is not repaired | Critical |
| L5 | Sufficient storage | Target tablespace | Avoid a half-written load | Free space ≥ 100 MB and ≥ 3 × the size of the eight source tables, measured before the transaction | Critical |
| L6 | Duplicate batch | `load_runs.batch_id` | Avoid publishing twice | No run-level row with this `batch_id` and `load_status = 'success'`. A prior `failed` status or a `REJECTED` decision is allowed and is retained for the audit trail | Critical |

L4 is the one that most often catches a real problem: if Stage 2 was re-run between the handover
and the load, the counts no longer describe the rows. The load refuses rather than loading something
the handover did not certify. It deliberately covers only the four facts — a dimension's
`records_output` is not the number of rows to load (§1.1), and comparing it would reject a batch
that is perfectly loadable.

---

## 5. Post-Load Validation and Reconciliation

These run **inside** the target transaction, after the `COPY` statements and before `COMMIT`. A
critical failure rolls the whole batch back. No new cleaning or business transformation is
performed; anything found is reported through §8.

| ID | Check name | Target | Purpose | Validation criteria | Severity |
| --- | --- | --- | --- | --- | --- |
| L7 | Record reconciliation | All eight tables | Detect lost or extra records | For every table, `records_received = records_inserted + records_rejected`; rejected rows are those written to `load_rejects`, not rows removed during transformation | Critical |
| L8 | Row count | All eight tables | Confirm the expected volume arrives | `count(*)` of rows with `load_batch_id = <batch>` equals `records_output` from the handover for that table | Critical |
| L9 | Key uniqueness | Every primary key in §2 | Prevent duplicates | `count(*) - count(distinct pk) = 0` per table | Critical |
| L10 | Referential integrity | Every fact foreign key | Prevent orphan facts | 100 % of `branch_key`, `item_key`, `status_key`, `date_key` values resolve to a dimension row; 0 orphans. An orphan is rejected, not replaced by an Unknown member | Critical |
| L11 | Required columns not null | Every `NOT NULL` column in §2 | Data completeness | Null count = 0 for each required column. Nullable columns (`gross_profit`, `margin_pct`, `unit_cost`, …) are explicitly excluded | Critical |
| L12 | Amount reconciliation | `fct_daily_sales.net_revenue`, `tax_total`, `settled_total`, `voided_amount`; the revenue columns of the other three facts | Confirm no value loss | Sum in the target equals sum in the source for the batch window, to the cent. For the measured batch: ₱10,100.00 net, ₱1,152.00 tax, 12 voids at ₱812.00 | Critical |
| L13 | Load errors and interruptions | `load_rejects`, the load log | Surface constraint violations and partial work | `records_rejected = 0` and no `ERROR` line in the narrative for a clean batch; a non-zero count within 1 % of `records_received` is a warning, above 1 % is critical | Non-critical |

L13 is the only non-critical check. It exists so that a small number of rejected rows produces an
`APPROVED WITH WARNING` decision with a human look, rather than either being ignored or stopping
the whole publication.

---

## 6. Load Metadata and Log Specification

### 6.1 `load_runs`

One **run-level** row (`table_name IS NULL`) and one row per target table per batch, matching the
shape Stages 1 and 2 already use. Fields:

| Field | Purpose | Example |
| --- | --- | --- |
| `run_id` | Unique ID of this load run | `a3f2c1d4-…` (uuid) |
| `transformation_run_id` | Link to the Stage 2 run | `TRF_20261024_d031cb6c`'s `run_id` |
| `batch_id` | Batch being loaded | `TRF_20261024_d031cb6c` |
| `batch_window_start` / `batch_window_end` | Date range covered | `2026-10-21` / `2026-10-24` |
| `table_name` | Target table, `NULL` on the run-level row | `fct_daily_sales` |
| `load_type` | `FULL` or `INCREMENTAL` | `INCREMENTAL` |
| `load_start_ts` / `load_end_ts` | When the table load began and ended | `2026-10-25 04:00:02+08` / `04:00:03+08` |
| `load_duration_sec` | Seconds taken | `1` |
| `records_received` | Rows read from Stage 2 for this table | `3` |
| `records_inserted` | New rows written | `3` |
| `records_updated` | Existing rows changed (0 by design — §3.1 deletes and inserts) | `0` |
| `records_rejected` | Rows the load did not write | `0` |
| `load_status` | `running` / `success` / `failed` | `success` |
| `pre_load_result` / `post_load_result` | Outcome of L1–L6 and L7–L13 | `{"L1":"PASS", …}` (jsonb) |
| `decision` | Verdict from §8 | `APPROVED` |
| `error_code` / `error_message` | Failure reason, if any | `NULL` |
| `code_version` | Version of the load code | `psync_load 0.1.0 / rules 1.0` |

No password, connection string or credential appears in any log field.

### 6.2 The two log files

Following Stages 1 and 2, a run leaves **two** files in `<data dir>/logs/load/`, sharing one stem
(`<batch_id>`):

- `<batch_id>.json` — the record: written once, atomically, at the end. The `stage` field is
  `"load"`, and the payload mirrors the run-level `load_runs` row. A run that fails never produces
  one.
- `<batch_id>.log` — the narrative: one line per step — `time | level | [Load] | step | message` —
  flushed as it happens. Steps run in order: `preload`, each table's `copy`, `validate`, `decision`,
  `record`. A failure ends with an `ERROR` line.

### 6.3 How the metadata is used

- **Monitoring** — `load_runs.load_status`, duration and per-table counts are what a scheduler or an
  operator checks first each morning.
- **Troubleshooting** — the narrative says which step failed and when; `error_code` and
  `load_rejects` say why; the two files together reconstruct the run without a database session.
- **Auditing** — `run_id`, `transformation_run_id` and `batch_id` chain a warehouse row back to the
  transformation batch and, through Stage 2's `parent_run_id`, to the extraction run.
- **Data lineage** — `load_batch_id`, `load_run_id` and `loaded_at` on every reporting row answer
  "which load put this row here".
- **Recovery** — a `FAILED` row has no committed data, so recovery is simply re-running the batch;
  `load_runs` keeps the failed attempt so the operator can see it was tried.

---

## 7. Log Retention, Rejected Data, and Access

| Item | Definition |
| --- | --- |
| **Retention** | Operational detail (the `.log` narrative, the `.json` record, snapshots) — **90 days**. Run-level rows in `load_runs` and rejected rows in `load_rejects` — **24 months**. Ninety days covers a term's worth of re-runs and disputes; two years covers an audit of what was published, and matches Stages 1 and 2 so one policy governs the whole pipeline. |
| **Storage** | `<data dir>/logs/load/` for the two log files; `psync_warehouse.public.load_runs`, `load_rejects`, `load_validation_results` for the ledger and rejects; `<data dir>/snapshots/<batch_id>/` for pre-load snapshots. The layout is tracked in git, its contents are not. |
| **Rejected data** | `load_rejects` in the warehouse, with `batch_id`, `table_name`, `rule_id` (e.g. `L-10`), `reason`, `payload jsonb` and `rejected_at`. Kept 24 months, never silently deleted, and never repaired by the load stage. The `quarantine_rows` from Stage 2 are **not** copied here — those records were already removed before transformation. |
| **Access** | `psync_loader` writes and reads the eight reporting tables and the bookkeeping tables. The analytics team and the panel have `SELECT` on the reporting tables. Only the data team lead may delete log files, and only through the retention job. PRINTSYNC has no account on this database. |
| **Archiving** | The dated submission zip defined in Extraction §5 (revision 1.8) — `data/submission/psync_evidence_<date>.zip` — carries `logs/load/` with everything else. Taken on demand, never scheduled. |
| **Deletion** | `prune_load_logs(data_dir)` runs nightly, reports what it deleted, deletes a run's two files together, never deletes before the retention period expires and cannot reach `handover/`, `exports/` or `submission/`. It is scoped to the log directory — the same rule that stops Stage 1's prune job from reaching the handover. |
| **Snapshot before major loads** | Before the dimension replace, each of the eight tables is streamed to `<data dir>/snapshots/<batch_id>/<table>.csv` via `COPY … TO STDOUT`. Snapshots are kept 7 days and are the recovery path if a full dimension replace is later found wrong. The normal failure path is still the transaction rollback (§3.4); the snapshot is for a mistake discovered *after* commit. |
| **Operational versus audit** | Detail expires; the accounting of what was published does not. Conflating them is how a team either hoards everything or deletes the evidence. |

---

## 8. Load Acceptance, Rollback, and Completion Rules

### 8.1 Decision rules

| Overall condition | Acceptance criteria | Decision | Pipeline action | Automatic or manual | Responsible role |
| --- | --- | --- | --- | --- | --- |
| L1–L12 all pass; L13 clean | Reconciliation matches, keys unique, no orphans, no nulls, amounts equal | **APPROVED** | Commit, mark `success`, publish the reporting tables | Automatic | None |
| All critical checks pass; L13 reports rejects within 1 % | The batch is publishable but a few rows did not load | **APPROVED WITH WARNING** | Commit, flag the run for review within one business day | Automatic, with a flag | Data team |
| One or more non-critical warnings beyond tolerance, or a small count difference within tolerance | A human should look before dashboards read it | **MANUAL REVIEW** | Roll back, hold publication, notify the data team lead | Manual | Data team lead approves or rejects |
| Any critical check fails (L1–L12), or the transaction raises | The batch cannot be trusted | **REJECTED** | Roll back, record `failed`, retry up to **3 times** with 30 s backoff, then stop and alert | Automatic stop; manual restart | Data team investigates |
| The handover is not `APPROVED` (L3) | No approved input | **REJECTED** | Stop before the transaction opens | Automatic | None |
| Batch already loaded with `success` (L6) | Would duplicate a publication | **REJECTED** | Stop without error | Automatic | None |

### 8.2 Who decides

| Decision | Automatic or manual | Responsible role |
| --- | --- | --- |
| APPROVED | Automatic | None — reports read the data |
| APPROVED WITH WARNING | Automatic, with a flag | Data team reviews within one business day |
| MANUAL REVIEW | Manual | Data team lead approves or rejects before publication |
| REJECTED | Automatic stop; manual restart | Data team investigates and re-runs |

**Notification.** A `REJECTED` or `MANUAL REVIEW` batch writes an `ERROR`/`WARN` line to the
narrative and is reported in the batch log; the data team lead is the named owner. There is no
silent failure path.

### 8.3 Completion and handover

A completed batch reports: `batch_id`, `transformation_run_id`, the window, the final decision,
`records_received` / `inserted` / `rejected` per table, the L1–L13 outcomes and `code_version`.
Downstream users are notified that new data is available by the run-level `load_runs` row becoming
`success` and by the reporting tables carrying the new `load_batch_id` — a report can filter on it,
and there is no second file to keep in step.

Explicitly **not** claimed here: no dashboard, no indexing beyond §2, no new business logic. Stage
3's promise is that the warehouse is a faithful, traceable copy of an approved transformation
batch.

### 8.4 Worked example

`TRF_20261024_d031cb6c`, window `2026-10-21` … `2026-10-24`.

| Item | Value |
| --- | --- |
| Input | 150 rows across eight tables, `decision = APPROVED`, `code_version = psync_transform 0.1.0 / rules 1.0` |
| Pre-load | L1–L6 PASS: connection, schema, approved handover, counts, storage, no prior success |
| Loaded | 4 dimensions (79 rows), 4 facts (71 rows); `fct_daily_sales` 3 rows — 2026-10-22 with 0 revenue and 12 voids, 2026-10-24 with 2 sales at ₱500.00 and 8 at ₱9,600.00 |
| Post-load | L7–L13 PASS: 150 received = 150 inserted + 0 rejected; keys unique; no orphans; ₱10,100.00 net, ₱1,152.00 tax, ₱812.00 voided |
| Decision | **APPROVED** — reports may read the warehouse |

---

## 9. Common Load Problems and Mitigation

| Problem | Possible cause | Impact on the load | Mitigation |
| --- | --- | --- | --- |
| Duplicate rows after a rerun | Same `batch_id` loaded twice because the success row was not checked | Inflated totals in every dashboard | L6 refuses a batch already `success`; facts are deleted for the window before insert (§3.5) |
| Foreign key violation | A fact was copied before its dimension, or a dimension row was dropped by the full replace | Load fails, or an orphan fact reaches a report | Fixed order: dimensions first, facts second; deletes in reverse; L10 checks 100 % resolution before commit |
| Partial load after a crash | Each table committed separately | Some tables show the new day and others the old one | One transaction for the whole batch (§3.4); an uncommitted transaction is rolled back when the connection closes |
| Target locked by a long report | A dashboard query holds a lock during the 04:00 window | Load waits, then times out mid-batch | 04:00 schedule, `SET LOCAL lock_timeout = '30s'`, and `statement_timeout = '300s'`; a timeout fails cleanly and retries with backoff |
| Row-by-row inserts on a growing dimension | Loader written with `INSERT … VALUES` per row | Load exceeds the five-minute bound and delays reporting | `COPY … FROM STDIN` in one stream per table; measured volume is ~150 rows, so this never needs a second strategy |
| Handover schema differs from the target | A Stage 2 migration added or retyped a column | Wrong values, or a `COPY` error halfway through a table | L2 compares columns and type families before any write; a missing or retyped column rejects the batch, additive columns are ignored |
| Stage 2 re-ran while the load was starting | Counts in `transformation_runs` no longer describe the rows | Loaded totals disagree with the certified batch | L4 recounts every table against `records_output` and refuses on mismatch; the operator re-runs the load after Stage 2 settles |
| A dimension version was closed upstream | Stage 2 closed an SCD2 version; an incremental upsert would keep the stale one | Warehouse shows a product as current after it was superseded | Dimensions are a full replace (§3.1), so closed versions are removed and the warehouse matches the source exactly |
| Storage fills during the snapshot | Free space fell below the snapshot's needs | Snapshot truncated; recovery path unavailable | L5 requires ≥ 100 MB and ≥ 3 × source size; snapshots are written to a temp file and renamed only when complete |
| A rejected row is silently skipped | Constraint violation swallowed by the `COPY` | Reconciliation passes on fewer rows than received | Every rejected row goes to `load_rejects` with a reason; L7 enforces `received = inserted + rejected` |
| `run_key` or `batch_id` contains a path separator | Windows filenames from an identifier with `:` | Log files collide or overwrite a real run | Log stems are sanitised and keyed on `batch_id` + `run_id[:8]`, the same rule Stages 1 and 2 apply |

---

## Revision history

| Revision | Date | Change |
| --- | --- | --- |
| 1.0 | 11 November 2026 | Initial specification for Stage 3, written against the Laboratory Activity 5 template. Defines `psync_warehouse` as a separate reporting database, the ledger row as the handover, bulk `COPY` loading, L1–L13 validation, `load_runs` metadata, the 90-day / 24-month retention split, and the acceptance and rollback rules. No rule, threshold or table changes from an earlier revision — this is the first. |
| 1.1 | 11 November 2026 | **Two claims corrected after batch 1 was deployed.** §1.5 listed a third role, `psync_warehouse_owner`, and said `psync_pipeline` had no write on the Stage 2 database — but that role owns both databases, wrote the Stage 2 output and applies the warehouse migrations. The table now describes the two roles that actually exist: `psync_pipeline` (owner, migrations, and Stage 3's read-only session) and `psync_loader` (restricted nightly loader, DML only, no privilege on the Stage 2 database), and records that migrations run under a one-off `PSYNC_WAREHOUSE_DSN` override. L6, §3.5, §8.1 and §9 said `SUCCESS`; the column is `load_status` and migration `005` constrains it to lowercase values, so those now read `success`. **Third correction:** §1.1 called `records_output` "the expected counts the load reconciles against", and L4 compared all eight tables. The live batch disproved it — `dim_date` reports `0` because it inserts only dates it has not seen, and the seeded `dim_order_status` has no row at all — so a full-load dimension would have been rejected for a batch that is perfectly loadable. `records_output` is now defined as *rows that run wrote*: facts are compared against it, dimensions are loaded whole and reconciled by L8. Found by verifying the deployed accounts and running the gate against the real batch rather than reading the document. No rule, threshold, table or acceptance criterion changed. |
