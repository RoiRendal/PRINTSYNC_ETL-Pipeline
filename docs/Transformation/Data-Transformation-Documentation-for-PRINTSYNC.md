# Data Transformation Documentation

**PRINTSYNC Nightly Analytics Batch Pipeline**
Pipeline ID · `psync_nightly_analytics` · Stage 2 of 3 (Extract → Transform → Load)
BAT-405 Analytics Application — Capstone Laboratory Activity 4
Lyell Jasmine D. Bulan · Roi C. Rendal · Ma. Erica Z. Vidal
26 October 2026

---

## Objective

Take the validated dataset handed over by the Extraction stage, clean it, standardise it, and
shape it into the business-ready dimensional tables the Load stage will publish — and prove that
the result is correct, complete, and traceable back to the batch that produced it.

Stage 2 **reads nothing from PRINTSYNC**. Its only input is the extraction handover: seven `stg_*`
tables in the pipeline's own `psync_analytics` database, selected by `run_id` and `business_date`
(Stage 1 §7.3). Stage 2 writes its output to the same database, in its own tables, and stops
there. Loading, indexing, and warehouse tuning belong to Stage 3.

Like Stage 1, this document is **the contract**. The code is built against it issue by issue, and
when the contract has to change the document is corrected first (§6.4).

---

## Scope decisions (read this first)

**1. The input is the handover, not the source.** The professor's instruction is explicit — do not
re-extract, and do not restate Stage 1's description of the source database. Everything below
starts from the staged rows. Where this document needs to explain a value, it cites the extraction
document (§2.x of Stage 1) instead of re-describing the table.

**2. One finding changed the Stage 1 contract, and it has to be said before anything else.**
`sales_transaction_items.inventory_item_id` is empty on **93.4 % of sale lines** (1,241 of 1,329)
— see §2, finding F-01. A product dimension keyed on the catalogue therefore cannot see most of
what the shop sells. The only other identifier a line carries is its `name`, and revision 1.3 of
the extraction contract did not extract it (§2.2 there listed six columns; `name` was not among
them). Stage 2 cannot build a product dimension without it.

This is recorded as a hard input requirement (D1, §1.4) and as problem P10 (§11). The remedy is
small and contained: one column added to the extraction scope, one to the staging table, one to
the extractor.

**Decision (26 October 2026): the column is added.** Stage 1 was revised to **1.4** — §2.2 and §6.3
now carry `sales_transaction_items.name`, migration `002_stg_item_name.sql` adds the column to
`stg_sales_transaction_items`, and the schema registry and the items extractor select it. It is a
pass-through: no cleaning happens in Stage 1.

The requirement stays in this contract as a guard rather than being deleted once satisfied. A
staging table built from an older revision — a database that was never migrated, or a hand-built
one — must **fail** check T1 rather than produce a demand table in which 93 % of revenue has no
product. The failure is the feature.

**3. Profit is published only where the cost is known.** `inventory_items.cost_price` reaches
**6.9 % of itemised revenue** (F-09). A gross-profit figure that treats the other 93 % as free
goods would be wildly overstated, so `gross_profit` and `margin_pct` are **NULL** unless the cost
of every peso of revenue is known. The costed slice is published alongside — with its coverage — so
the number is never read as a whole-day figure. This is the same judgement Stage 1 made about
`expense_total`: better an absent number than a wrong one.

**4. A batch does not process one day. It processes up to four.** Stage 1 re-reads a three-day
look-back on every run (§1.3), so the staged rows for `business_date = D` contain sales created
on `D-3 … D`. Every one of those days must be rebuilt, because the whole reason a sale is re-read
is that its day has changed. The business date of a fact row therefore comes from
`created_at` in `Asia/Manila`, **never** from the staging control column `business_date` — which
is the same value on every row in the batch and would silently pile four days of revenue onto one.
See P1.

**5. Branch is part of the grain; branch *days* are not.** Stage 1 carried `branch_id` as an
unresolved attribute and deferred per-branch summaries (§"Scope decisions", item 2). Stage 2
delivers the summaries — the data has been carried for exactly this — but keeps one business-day
boundary for every branch, taken from the reference branch's `time_zone`. That is safe today:
both rows in `business_settings` are `Asia/Manila` (F-12). If a branch is ever opened in another
zone, the boundary becomes per-branch and §5 has to be revised, not patched.

**6. Demand and stock are two facts, not one.** Lab 2 put `stock_on_hand` and the reorder figures
in the same table as units sold. That cannot survive a look-back: demand must be rebuilt for four
dates every night, while stock is a snapshot taken on the night the batch runs. Rebuilding an old
date would overwrite its stock with tonight's, destroying the only record of what was on the shelf
that day. They are therefore separate tables with separate lifetimes (§5.6, A-07).

---

## 1. Transformation Input and Processing Specification

### 1.1 Input source

| Item | Detail |
| --- | --- |
| Name | The extraction handover of `psync_nightly_analytics` (Stage 1 §7.3) |
| Format and location | Seven PostgreSQL staging tables in the pipeline's own database, `psync_analytics`: `stg_sales_transactions`, `stg_sales_transaction_items`, `stg_payments`, `stg_orders`, `stg_inventory_items`, `stg_business_settings`, `stg_branches`. No files, no CSV, no Parquet. |
| How the batch is selected | `run_id` (the extraction run) and `business_date` (the day being processed). Both come from the handover manifest, `<run_key>_<run_id[:8]>.handover.json`. |
| What the handover must say | `decision` is `APPROVED` or `APPROVED WITH WARNING`. A `REJECTED`, `RETRY`, `MANUAL REVIEW`, or `SKIPPED` run has no manifest at all — `build_handover` returns nothing — so there is nothing to transform. |
| Extraction run ID | The parent run: `parent_run_id`. Recorded on every transformation batch (§8). |
| Batch window | `[business_date - LOOKBACK_DAYS, business_date]` in `Asia/Manila`. With the configured look-back of 3, a batch for 2026-10-02 rebuilds 2026-09-29 … 2026-10-02. |
| Reference values carried from Stage 1 | Per-table `rows_read` / `rows_extracted` / `rows_rejected`, the validation results V1–V8, and the window boundaries. Used as the reference side of the reconciliation in §7. Nothing else is re-derived. |
| What is **not** read | PRINTSYNC. No source connection is opened by this stage, and no credential for it is loaded. |

**Example batch.** Extraction run `9f1c0b6e…` covers `business_date = 2026-10-02` and hands over
**18 sales (6 live, 12 voided), 28 sale lines (10 live), 18 payments, 23 orders, a 15-row catalogue
snapshot, two settings rows and two branch rows**. The 23 orders are the whole table, not the day's
orders: a bulk update touched every row's `updated_at` (F-10), which is exactly the case C-06
exists for. Stage 2 receives those staged rows, profiles them, applies the cleaning rules (§3),
standardises them (§4), builds the dimensions and facts (§5), validates the result (§7), and hands
four rebuilt business dates to the Load stage.

### 1.2 Batch processing method

**Tool.** A second Python package in the same repository, `psync_transform`, built the same way as
`psync_extract`: **Psycopg 3** against `psync_analytics`, **Prefect 3** for orchestration and
retries, Python 3.12 or newer. The transformation itself is **set-based SQL**, executed statement
by statement through Psycopg; Python orchestrates, measures, validates, and records. Two entry
points, as in Stage 1: `python -m psync_transform --date YYYY-MM-DD` and the `transformation_flow`
Prefect flow.

**Why SQL and not Polars.** Lab 2 proposed Polars lazy frames for the conform step, and that is
still the right answer *if the data has to leave the database*. It does not: the staged rows are
already in PostgreSQL, the dimensions and facts are tables in the same database, and every rule in
§3–§5 is a join, a window function, or an aggregate. Pulling a thousand rows into a columnar engine
to compute them would add a dependency, a second type system, and a copy step — and a place for the
two to disagree about rounding — for no measurable gain at this volume. Polars stays the documented
choice for the day an archive or a multi-year backfill makes an out-of-database engine worth it.

**Schedule.** Nightly at **01:30 Asia/Manila**, thirty minutes after extraction starts. The flow is
triggered by the extraction flow's success, not by the clock, so a failed extraction can never be
followed by a transformation of yesterday's staging rows. A manual run for a chosen date is
supported for backfill and repair.

**Batch size and window.** One extraction handover: one business day plus its three-day look-back,
which at current volumes is about 18 sales and 28 sale lines, 23 orders, and a 15-row catalogue per
batch (measured, §2.1). The design capacity is 5,000 sale lines per batch; beyond that the facts are
rebuilt one output date per transaction rather than one batch per transaction.

**How a failed batch is rerun.** The batch is rebuilt from staging, never resumed from a partial
state. `python -m psync_transform --date 2026-10-02` re-runs the most recent handed-over extraction
run for that date; `--parent-run <uuid>` pins it to a specific one. Every date's write happens in
one transaction, so a failure leaves the previous output untouched rather than half-replaced. The
orchestration layer retries three times, 60 seconds apart; a batch that still fails is marked
`failed` and the day is not handed to Load.

**Idempotency — and the mechanism.** Rerunning the same batch produces the same rows and no
duplicates, by construction:

| Object | Mechanism | Why it is safe |
| --- | --- | --- |
| Facts (`fct_*`) | **Delete-and-insert by `business_date`** (C-09). The publish step deletes every fact row for every date in the batch window — not only the dates that produced rows — then inserts this batch's rows, in one transaction. | A day that has become empty (every sale voided) is emptied, not left stale. A rerun replaces its own output exactly. |
| `fct_daily_stock_snapshot` | Delete-and-insert for the **target date only** | It is a snapshot of the night the batch ran. Look-back dates are never touched, so an earlier night's snapshot survives (see §6, A-07). |
| Dimensions (`dim_*`) | **Upsert, keyed on the natural key plus `valid_from`** (C-07, C-08). `INSERT … ON CONFLICT (natural_key, valid_from) DO UPDATE`. | A rerun updates the version it created instead of adding a second one, and the surrogate key assigned on first insert is kept — so facts written by an earlier batch still point at the right row. |
| Batch record | **Unique index** on `(batch_id, COALESCE(table_name, '__run__'))`. `batch_id` is `TRF_<YYYYMMDD>_<parent_run_id[:8]>`, so it is stable for one handover. | A second attempt at the same handover rewrites its own record instead of appending a second one. |
| Quarantine | **Unique index** on `(batch_id, source_table, source_id, rule_id)`. | A rerun does not quarantine the same row twice. |

Because the facts are keyed on `business_date` and the batch window is derived from the same
`business_date`, two consecutive nights overlap on three dates by design. Each night replaces those
dates with its own view of them, which is exactly what a look-back is for.

### 1.3 Transformation scope

| Dimension | Scope |
| --- | --- |
| Input tables | All seven staging tables. None is optional. |
| Output tables | Four dimensions (`dim_date`, `dim_branch`, `dim_item`, `dim_order_status`), four facts (`fct_daily_sales`, `fct_daily_product_demand`, `fct_daily_stock_snapshot`, `fct_daily_order_status`), one quarantine table, two metadata tables. Defined in §6.1. |
| Business dates written | Every date in the batch window for the sales, demand and order facts, whether or not the date produced rows. The stock snapshot is written for the target date only. |
| Columns cleaned | `name` (trim, whitespace collapse), `sku` (case), `category` (blank to default), `uom` (case), `payment_method` and `method` (code map), `status` (code map), every money column (type and precision), every timestamp (business-date derivation). Listed rule by rule in §3 and §4. |
| Columns derived | `net_revenue`, `tax_total`, `line_revenue_total`, `line_discount_total`, `unallocated_discount`, `cogs`, `revenue_costed`, `cogs_coverage_pct`, `gross_profit`, `margin_pct`, `gross_profit_costed`, `margin_pct_costed`, `avg_transaction_value`, `settled_total`, `line_revenue`, `revenue`, `avg_daily_demand`, `forecast_demand_30d`, `recommended_reorder`, `stock_status`, `avg_order_value`, `item_ref`, and every surrogate key. |
| Columns aggregated | Daily sales per branch; daily demand per item per branch; daily order counts per status per branch; one stock snapshot per item per branch. Grouping levels are in §5.6. |
| Records excluded | Voided sales and voided payments (counted, §5.4); orders that are in the batch only because their `updated_at` moved (counted, §3.1 C-06). No row is ever dropped without a count. |
| Out of scope | Loading, indexing, partitioning, dashboard queries, and any write to PRINTSYNC. |

### 1.4 Dependencies and assumptions

**Processing order.** Dimensions before facts, and within each group a fixed order — a fact row
cannot resolve a surrogate key that does not exist yet.

```
1  input contract check      T1, T2        read the handover, confirm the columns exist
2  profile and stage          -            per-rule counts, written before any output
3  dim_date                  M-01          generated, not derived
4  dim_branch                M-02, M-05    upsert, SCD Type 2
5  dim_item                  M-03, M-05    upsert, SCD Type 2
6  dim_order_status          M-04          seeded by migration 003, never derived
7  fct_daily_sales           A-01          delete-and-insert by business_date
8  fct_daily_product_demand  A-02          delete-and-insert by business_date
9  fct_daily_stock_snapshot  A-07          delete-and-insert for the target date only
10 fct_daily_order_status    A-05          delete-and-insert by business_date
11 validation                T3…T17        reconciliation, keys, integrity, business rules
12 decide, record, hand over §10, §8       one transaction, then the manifest
```

**Assumptions that could change the output.** Each one is a real condition of this data, not a
placeholder.

| # | Assumption | Consequence if it stops holding |
| --- | --- | --- |
| D1 | **`sales_transaction_items.name` is present in staging.** Revision 1.3 of Stage 1 did not extract it (F-02); revision 1.4 does, and migration `002` adds the column. | T1 fails the batch. Without the column, 93.4 % of sale lines have no product identity at all — and a stale staging table is exactly the case T1 exists to catch. |
| D2 | The handover it reads is `APPROVED` or `APPROVED WITH WARNING`. | No manifest exists for any other decision, so the batch cannot start. It never re-checks Stage 1's work. |
| D3 | Staged rows for one `source_id` may appear up to four times (one per look-back run). | Deduplication (C-03) is what keeps a re-read from becoming a second sale. If Stage 1 ever stopped re-reading, C-03 becomes a no-op rather than a bug. |
| D4 | A product is identified by the name printed on the sale line. | A rename starts a new product history (P2). Fixing it properly requires PRINTSYNC to require a catalogue link at the point of sale, which we cannot do (§1.6 of Stage 1). |
| D5 | Every branch shares one time zone, taken from the reference branch. | Two zones would mean two day boundaries in one fact table. §5 has to be revised first. |
| D6 | `business_settings` has exactly one row per branch, and the reference branch's row exists. | Stage 1 check V4 already fails the run when the settings row is missing, so the batch is never handed a settings-less handover. |
| D7 | The catalogue snapshot is complete — `inventory_items` is extracted in full every run. | A partial snapshot would close dimension versions that still apply. Stage 1 extracts it in full (§1.3), so this holds. |
| D8 | Late-arriving data is handled by the look-back, not here. | A sale corrected more than three days after its day will not be re-read, so its fact row stays wrong. That is a Stage 1 limitation (P2 there), inherited, and it is why a manual re-run for an old date is supported. |
| D9 | Lookup tables (dimensions) are always available to the facts, because they are built in the same transaction. | There is no "dimension missing" state to handle; a fact row that cannot resolve a dimension key is quarantined, not written with a null key. |
| D10 | The stock snapshot describes the night the batch ran, not a reconstruction of that day's shelf. | A manual re-run of an old date refreshes its stock figures with today's catalogue. That is what a snapshot means, and it is why the stock fact is separate from demand (§5.6). |

---

## 2. Data Profiling and Issue Identification

### 2.1 How the data was profiled

Profiling ran **before any rule was written**, and every rule in §3–§5 traces back to a finding
here. That order matters: a rule with no finding behind it is a rule that fixes an imaginary
problem.

| Item | Detail |
| --- | --- |
| Dataset | The PRINTSYNC export of **2 October 2026**, the most recent complete export of the operational database: 867 sales, 1,329 sale lines, 867 payments, 23 orders, 15 catalogue items, 2 settings rows. |
| Why the export and not a staged batch | Stage 1 copies rows without cleaning them (Stage 1 §7.3), so a staged batch and the export hold the same values. Profiling the export makes the figures reproducible without a running database, which is what a reader checking this document needs. |
| Coverage | Every column this stage reads, plus the arithmetic relationships between them (line totals against header totals, payments against sale totals, VAT against the rate in `business_settings`). |
| Volume observed | 241 distinct trading days, 2026-02-01 to 2026-10-02, between 1 and 11 sales a day. The last ten days range from 1 to 11 sales and 1 to 20 sale lines — a night is small. |
| Output of the profile | The findings table below. The per-rule counts it produces are also what `transformation_rule_counts` records on every batch (§8), so the profile is not a one-off document: it is the same measurement the pipeline takes every night. |

**The questions asked.** For each table: how many rows, what is the date range, how many nulls per
column, how many blanks versus nulls, how many duplicates on the primary key and on any natural
key, how many values sit outside their documented domain, how many text values carry leading or
trailing whitespace or repeated internal spaces, how many child rows have no parent, how many
references dangle, and — the part that found most of what follows — how many rows do the arithmetic
relationships between tables actually reconcile.

### 2.2 Findings

| # | Table / column | Issue type | Example | Affected records | Planned treatment |
| --- | --- | --- | --- | --- | --- |
| F-01 | `sales_transaction_items.inventory_item_id` | Missing reference — the catalogue link is absent on almost every line | `"Tarpaulin Printing (per sq ft)"`, qty 2, ₱45.00, no `inventory_item_id` | **1,241 of 1,329 (93.4 %)**; only 88 lines (6.6 %) link to the catalogue | Resolve the product from the line name; never drop the line (C-02, B-02) |
| F-02 | `sales_transaction_items.name` | **Required column not in the input contract** — it exists at source but revision 1.3 of Stage 1 does not extract it | The 40 product names that carry 93.4 % of the lines | 100 % of lines, until fixed | **Resolved: Stage 1 rev. 1.4 extracts it** (§2.2, §6.3, migration `002_stg_item_name.sql`). D1 keeps T1 as a guard so a stale staging table still fails |
| F-03 | `sales_transactions.discount` | Header discount not itemised on any line | subtotal ₱1,000.00, discount ₱40.00, `Σ line_discount` ₱0.00 | **75 of 867 (8.6 %)**; 82 sales carry a discount at all | Keep the header discount as the day's figure and record the unallocated part (B-05, T4) |
| F-04 | `sales_transactions.created_at` | Mixed business-day boundary — timestamps are UTC, the shop's day is `Asia/Manila` | `2026-10-01T16:30:00+00:00` is 2 October in Manila | **7 of 867 (0.8 %)** fall on a different Manila date | Derive `business_date` in `Asia/Manila` (S-01, T13) |
| F-05 | `sales_transactions.status`, `payments.status` | Records that must not count as revenue, present in the batch by design | `status = 'voided'`, `voided_at` set | **16 sales (1.8 %)** and 16 payments; 12 of the 18 sales in the 2026-10-02 batch | Exclude from revenue, count them (X-01, X-02) |
| F-06 | `sales_transactions.tax` | Value inconsistent with the configured VAT rate | net ₱3,240.00, tax ₱0.00, expected ₱388.80 | **5 of 867 (0.6 %)**: four ₱10.00 voided test sales and one completed ₱3,240.00 sale | Never recompute a recorded tax; warn (T6) |
| F-07 | `inventory_items.sku` | Mixed case in a code column | `PCK-MAILER-10x13`, `SCR-FRAME-20x24` | 2 of 15 | Upper-case the code (S-11) |
| F-08 | `inventory_items.uom` | A single value for every item while the names carry the real unit | `uom = 'pc'` for `"Tarpaulin Printing (per sq ft)"` and `"Business Cards (100 pcs)"` | 15 of 15 | Treat `uom` as a label, never as a conversion factor (S-18) |
| F-09 | `inventory_items.cost_price` | Cost known for a small slice of revenue | 73 of 1,305 completed lines have a costed product | **₱79,145.00 of ₱1,140,000.00 itemised revenue (6.9 %)** | Publish costed profit plus its coverage; NULL the whole-day figure (B-09, T9) |
| F-10 | `orders.updated_at` | Bulk touch — every order shares one timestamp | all 23 rows: `2026-10-02T11:22:50.736631+00:00` | 23 of 23 | Cohort the order fact on `created_at`, and count the orders the window over-collects (B-11, C-06) |
| F-11 | `orders.status` | Free-text status with no order | six values, unsorted, no funnel position | 23 of 23 | Resolve through a status dimension with an explicit order (B-14, S-17) |
| F-12 | `business_settings` | Two rows, identical settings, one branch with no transactions | `IC Printing Services`, `IC Printing Services - Nasugbu`, both `Asia/Manila` / 12 / ₱ | 2 of 2 | Branch dimension; the reference-branch assumption (L5) still holds (B-04) |
| F-13 | `payments` | One payment per sale today, but the schema allows several | 867 payments for 867 sales, maximum 1 each | 867 of 867 | Build the split from `payments`, not from the header column (B-06) |
| F-14 | every money column | Binary floating point cannot hold `numeric(12,2)` exactly | ₱1,267,387.08 across 851 sales | all money | Sum in `numeric`, never in float (S-02) |
| F-15 | all seven staging tables | Duplicate rows across look-back runs | the same `source_id` under four different `run_id`s | up to 4× per row | Deduplicate, keeping the latest `extracted_at` (C-03) |

### 2.3 What the profile cleared

Half the value of a profile is the list of problems that are **not** there. Each of the classic
cleaning targets was measured and came back empty, and the reason is that PRINTSYNC already
enforces it with a `CHECK` constraint (Lab 2 §5.2). The rules still exist — §3 — because that
constraint is on their side of the boundary and could be dropped by a migration we are not told
about; but a reader deserves to know that on this data they will count zero.

| Checked | Result | Why it is already clean |
| --- | --- | --- |
| Null primary keys | 0 | Every key is `NOT NULL` at source |
| Duplicate primary keys | 0 | `PRIMARY KEY` at source |
| Negative or zero money | 0 | `CHECK >= 0` on every amount column |
| Zero or negative quantity | 0 | `CHECK > 0` on `sales_transaction_items.quantity` |
| `status` / `payment_method` outside the documented set | 0 | `CHECK IN (...)` at source |
| Child rows with no parent | 0 | `FK … ON DELETE CASCADE` at source |
| Dangling catalogue references | 0 | `FK … ON DELETE SET NULL` — a deleted product nulls the link rather than dangling it, which is precisely F-01 |
| Leading/trailing whitespace in text | 0 | Checked on 1,329 line names, 15 catalogue rows, 23 order customers: none |
| Blank `category` or blank `uom` | 0 | `length(trim()) > 0` at source |
| Price below cost | 0 | No `CHECK` for it — genuinely absent from this data, not prevented |
| `Σ (quantity × unit_price)` against `subtotal` | **0 mismatches in 867 sales** | The header is built from the lines |
| Captured payments against sale total | **0 mismatches in 851 completed sales** | The payment is written from the total |
| `voided_at` missing on a voided row | 0 | Both sales and payments set it |
| `line_discount` greater than the header discount | **0 sales** | The unallocated discount is never negative (T4 depends on this) |

The line-to-header identity and the payment-to-total identity are the most useful things in the
profile. They mean the header is authoritative for what was charged, and the payments prove it.
That is why F-03 is handled by trusting the header and recording the difference rather than by
redistributing the discount onto the lines.

---

## 3. Data Cleaning Rules

Every rule below cites the finding it answers. **No record is ever dropped silently**: a record is
either retained (possibly modified) or written to `quarantine_rows` with the rule ID, the batch ID
and the reason (§7, §9).

### 3.1 Missing and null values

| Rule | Target | Condition | Action | Justification |
| --- | --- | --- | --- | --- |
| C-01 | `sales_transaction_items.name` → `dim_item.item_name` | The name is null, empty, or whitespace only | **Quarantine** the line (`reason = missing_product_name`) | A line with no name has no product identity at all — not a fallback, an absence. Quarantining keeps the revenue visible as rejected instead of invisible. F-02 |
| C-02 | `sales_transaction_items.inventory_item_id` → `dim_item.item_ref` | The catalogue link is null (F-01) | **Resolve by name.** `item_ref = 'name:' \|\| normalised(name)`; `inventory_item_id` stays NULL on the dimension row; the line is **retained** | 93.4 % of the shop's revenue is print services that were never catalogued. Dropping them, or bucketing them as "unknown", would delete the business to protect the schema. The name on the line is a real, printed product identifier. |
| C-03 | All seven staging tables | The same `(source_table, source_id)` appears more than once, because the look-back re-read it | **Keep the row with the greatest `extracted_at`**; tie-break on `run_id`. The others are counted by C-03 and discarded | A re-read is a correction, not a second sale. The latest copy is the one that reflects the void or edit that caused the re-read. F-15 |
| C-04 | `inventory_items.category` → `dim_item.category` | Category is null or blank | **Fill with `'Uncategorised'`** | A product still has to appear in the dimension, and a reported bucket named "Uncategorised" is honest. |
| C-05 | `inventory_items.cost_price` → `dim_item.unit_cost` | No cost is known for the product | **Leave NULL. Never default to 0** | A cost of zero is a claim that the goods were free, and it would inflate profit by the whole line. NULL means "unknown", and B-09 turns unknown into an absent profit figure rather than a wrong one. F-09 |
| C-06 | `orders` | The order is in the batch only because `updated_at` moved, not because it was created in the window | **Exclude from the order fact**, count by C-06 | The fact reports orders *raised* on a day. An order raised in February and touched by a bulk update in October is not October demand. F-10 |

### 3.2 Duplicates

| Rule | Target | Condition | Action | Justification |
| --- | --- | --- | --- | --- |
| C-07 | `dim_branch` | Two versions of a branch with the same `branch_id` and the same `valid_from` | **Keep the latest `extracted_at`**, enforced by the unique index and an upsert | A rerun must not create a second version of the same day. C-03 |
| C-08 | `dim_item` | Two versions of a product with the same `item_ref` and the same `valid_from` | **Keep the latest `extracted_at`**, same mechanism | Same reason. A batch that sees the same product twice has been re-read, not re-priced. |
| C-09 | `fct_*` | A fact row already exists for the same `business_date` (and the same dimension keys) | **Delete before insert** — the whole batch window is cleared first | The fact is a replacement, not an accumulation. This is the idempotency mechanism in §1.2, and the only defence against a doubled revenue figure. |

**Which record is kept, stated plainly.** For a re-read: the one with the greatest `extracted_at`,
because the extraction that ran last saw the source last. For a dimension version: the same. For a
fact row: none — the old row is deleted and the new one is written from the batch, because a fact
row is a recomputation, not a record to choose between.

### 3.3 Whitespace and invalid characters

| Rule | Target | Condition | Action | Justification |
| --- | --- | --- | --- | --- |
| C-10 | `name`, `category`, `uom`, `code`, `sku` | Leading or trailing whitespace, or repeated internal spaces | **Trim, then collapse internal runs to one space** | The profile found none today (§2.3), but a name is the product's identity here (C-02), so `"A4 Bond"` and `"A4 Bond "` would become two products and split one product's demand in half. This rule protects the key, not the display. |
| C-11 | `name`, `category` | Non-breaking space, tab, or other invisible separator | **Replace with a single space**, then C-10 | The same failure mode, one character class further out. |
| C-12 | `sales_transactions.customer` | Empty string rather than NULL | **Not applicable — the column is not extracted** (Stage 1 §2.2) | Recorded so it is not mistaken for a gap. 857 of 867 sales carry `customer = ''` at source; the pipeline never sees it, and no output needs it. |

### 3.4 Invalid and out-of-range values

| Rule | Target | Condition | Action | Justification |
| --- | --- | --- | --- | --- |
| C-13 | `sales_transaction_items` | `quantity <= 0`, `unit_price < 0`, `line_discount < 0`, or `line_discount > quantity × unit_price` | **Quarantine** the line (`reason = invalid_line_value`) | A line that cannot be true cannot be aggregated. The profile found none (§2.3); the rule exists because the source constraint is not ours. |
| C-14 | `sales_transactions` | `subtotal`, `discount`, `tax`, or `total` is negative, or `total <> subtotal - discount + tax` | **Quarantine** the sale and its lines (`reason = invalid_sale_total`) | The header is authoritative for revenue (B-01). If it is internally inconsistent, there is no trustworthy figure to publish. Zero occurrences today. |
| C-15 | `sales_transactions.status`, `payments.status` | A value outside `('completed','voided')` / `('captured','voided')` | **Quarantine** (`reason = unknown_status`) | An unknown status cannot be classified as revenue or not. Guessing "probably completed" is how a refund becomes income. |
| C-16 | `orders.status` | A value outside the six documented statuses | **Quarantine** (`reason = unknown_order_status`) | The status dimension fixes the six values (B-14); a seventh must be a deliberate contract change, not a new row. |
| C-17 | `payments` | `amount <= 0` | **Quarantine** (`reason = invalid_payment_amount`) | A settlement of zero or less is not a settlement. Zero occurrences today. |

### 3.5 Orphan records

| Rule | Target | Condition | Action | Justification |
| --- | --- | --- | --- | --- |
| C-18 | `sales_transaction_items` | `transaction_id` has no sale in this batch | **Quarantine** (`reason = orphan_transaction_id`) | Stage 1 already rejects these structurally (`reject_orphans`), so this is a second line of defence: revenue must never attach to a sale that is not in the batch. |
| C-19 | `payments` | `transaction_id` has no sale in this batch | **Quarantine** (`reason = orphan_transaction_id`) | Same reason. A payment without a sale cannot be attributed to a branch or a day. |
| C-20 | `sales_transaction_items` | `inventory_item_id` is set but no catalogue row with that id is in the batch snapshot | **Keep the line**, resolve it by name (C-02), and count it under C-20 | The link is a convenience, not the identity. Losing the revenue to protect a foreign key would be the wrong trade. Zero occurrences today (the source nulls the link instead of dangling it). |
| C-21 | facts | A dimension key cannot be resolved for a fact row | **Quarantine the fact row** (`reason = unresolved_dimension_key`) | A fact with a null key is unqueryable. This is the one case where a fact row is rejected rather than written — and it is counted, so it cannot hide. |

---

## 4. Standardization and Data Type Rules

### 4.1 Data types

| Rule | Column | Source type | Target type | Conversion rule | On failure |
| --- | --- | --- | --- | --- | --- |
| S-01 | every timestamp → `business_date` | `timestamptz` (UTC) | `date` in `Asia/Manila` | `(created_at AT TIME ZONE 'Asia/Manila')::date`. The instant itself is kept as `timestamptz`; only the day is derived. | Quarantine (`reason = unreadable_timestamp`) — zero occurrences |
| S-02 | every money column | `numeric(14,2)` in staging | `numeric(14,2)` in the facts | Sum and multiply in `numeric`; round half-up **once**, at the measure being published, never at the line | Quarantine (`reason = unreadable_amount`) |
| S-03 | every percentage | computed | `numeric(6,2)`, `0.00`–`100.00` | Round half-up to two decimals; **NULL when the denominator is zero** | Never divide by zero — the denominator is checked first |
| S-04 | `quantity`, `stock`, `reorder_level` | `integer` | `integer` | No conversion. Cast is explicit, never implicit. | Quarantine |
| S-05 | `business_date`, `valid_from`, `valid_to` | — | `date` | Calendar dates, no time, no zone | — |
| S-06 | every surrogate key | — | `bigint` (`dim_branch`, `dim_item`), `smallint` (`dim_order_status`), `date` (`dim_date`) | Generated by the database on first insert, then never reassigned | — |

### 4.2 Formats

| Rule | Target | Rule | Justification |
| --- | --- | --- | --- |
| S-07 | Timestamps in output and logs | **ISO 8601 with an explicit offset**, `2026-10-02T01:14:44+08:00` | An offset-free timestamp is ambiguous the moment a branch opens in another zone. Stage 1 already writes them this way (§4). |
| S-08 | Dates in output and filenames | `YYYY-MM-DD` | Matches the business date everywhere else in the pipeline, and sorts correctly as text. |
| S-09 | Money | `numeric(14,2)`, two decimals, no currency symbol in the value | The symbol lives in `dim_branch.currency_symbol` (F-12). Embedding it in a number makes the number unsummable. |
| S-10 | Text casing — names | **Preserved**, only trimmed and collapsed (C-10) | `"A4 Bond Paper (ream, 500s)"` is what the shop printed on the receipt; upper-casing it would make the dimension harder to read, and the case carries meaning (`pcs` vs `Pcs`). |
| S-11 | Text casing — codes | **Upper-case**: `sku`, and the mapped `payment_method` / `status` values | A code is an identifier, not prose. F-07 |
| S-12 | `item_ref` | `'name:' \|\| normalised name`, lower-cased for matching, original case kept in `item_name` | The prefix states the basis of identity at a glance, which matters when 93 % of products have no other identifier (F-01). |

### 4.3 Reference values and code maps

| Rule | Column | Source values observed | Standard value | On an unmapped value |
| --- | --- | --- | --- | --- |
| S-13 | `payments.method` → `payment_method` | `Cash` (601), `Card` (258), `Custom Order` (8) | `CASH`, `CARD`, `CUSTOM_ORDER` | Quarantine (`reason = unknown_payment_method`) |
| S-14 | `sales_transactions.payment_method` | same three values | same three codes; used only to cross-check the split from `payments` (B-06) | Warning, not a reject — the header value is not the measure |
| S-15 | `sales_transactions.status` | `completed` (851), `voided` (16) | `LIVE`, `VOID` | Quarantine (C-15) |
| S-16 | `payments.status` | `captured` (851), `voided` (16) | `LIVE`, `VOID` | Quarantine (C-15) |
| S-17 | `orders.status` | `Pending`, `Designing`, `In Production`, `Ready for Pickup`, `Completed`, `Delivered` | The same six names, with `status_order` 1–6 and `is_backlog` / `is_terminal` flags | Quarantine (C-16) |
| S-18 | `inventory_items.uom` | `pc` (15 of 15) | Lower-cased and trimmed, kept as a **label only** | Never used in arithmetic — F-08 shows it does not describe the real unit |
| S-19 | Currency | `₱` on both settings rows | Carried on `dim_branch.currency_symbol`, not on any measure | — |
| S-20 | VAT rate | `12` on both settings rows | `dim_branch.vat_rate = 12.00`, interpreted as **12 per cent**, not 0.12 | A rate of 0 or above 100 fails T6 rather than silently zeroing every tax figure |

### 4.4 Handling of conversion failures

A value that cannot be converted is **never coerced, defaulted, or skipped**. It is written to
`quarantine_rows` with the rule that caught it, the column, the offending value, the batch ID, and
the parent run ID, and it is counted in `transformation_runs.records_rejected`. The one exception
is a documented default — `category = 'Uncategorised'` (C-04) — and it is an exception precisely
because it states "we do not know" rather than inventing a value. `unit_cost` gets no default
(C-05), and the difference between those two decisions is the whole principle: a default is
acceptable when the value is descriptive, and unacceptable when it is a measurement.

---

## 5. Business Transformation Rules

### 5.1 The dimensional model

Four dimensions, four facts. The facts answer the four questions the dashboard actually asks: what
did we sell today, what did each product do, what is on the shelf, and where are the custom orders
sitting.

```
        dim_date            dim_branch                 dim_item              dim_order_status
     (date_key = date)   (branch_key bigint)        (item_key bigint)        (status_key smallint)
            |                   |                          |                        |
            |                   |                          |                        |
   +--------+--------+----------+-----------+--------------+------------+-----------+
   |                 |                      |                           |
fct_daily_sales  fct_daily_product_   fct_daily_stock_          fct_daily_order_status
(date × branch)   demand               snapshot                  (date × branch × status)
                  (date × branch ×     (date × branch × item,
                   item)                target date only)
```

**Why the facts have no surrogate key of their own.** A fact table's primary key *is* its grain —
the combination of its dimension keys — and a generated integer on top of that would be a second
identifier for the same row, with no consumer. Surrogate keys exist to insulate the facts from
changes in a natural key, which is a problem only for dimensions. Every dimension therefore has
one (`branch_key`, `item_key`, `status_key`), every fact references them, and no fact invents one.

**Why `dim_date`'s key is the date.** There is nothing to insulate: a calendar date does not get
renamed, and its natural key is already the smallest thing that identifies it. Storing
`date_key = 20261002` alongside `business_date = '2026-10-02'` would be two columns carrying one
fact, and the pair could disagree. The key is the date, and the facts reference it directly.

### 5.2 Derived columns

| Rule | Input columns | Logic | Output column | Business reason |
| --- | --- | --- | --- | --- |
| B-01 | `sales_transactions.total`, `status` | `Σ total` where status is `LIVE` | `fct_daily_sales.gross_revenue` | What the shop actually took, VAT included. The header is authoritative because captured payments equal it on all 851 completed sales (§2.3). |
| B-02 | `total`, `tax` | `gross_revenue - tax_total` | `fct_daily_sales.net_revenue` | Revenue with VAT removed. This is the figure a margin can be computed against — a margin on VAT-inclusive revenue overstates itself by the tax rate. |
| B-03 | `sales_transaction_items.name`, `inventory_item_id` | Build `item_ref` (C-02, S-12) | `dim_item.item_ref` | Gives 93.4 % of the lines an identity they otherwise do not have. F-01 |
| B-04 | `quantity`, `unit_price`, `line_discount`, `cost_price` | `line_revenue = quantity × unit_price`; `revenue = line_revenue - line_discount`; `cogs = quantity × unit_cost` when the cost is known | `fct_daily_product_demand.line_revenue`, `revenue`, `cogs`, `is_costed` | Revenue and cost at the line, which is the only level where they are both known. |
| B-05 | `subtotal` and the line sums | `Σ (quantity × unit_price) = Σ subtotal` is an identity in this data (867/867) | `fct_daily_sales.line_revenue_total` | The itemised revenue the lines add up to. It is the denominator for cost coverage and the reference side of the product reconciliation (T12), so it has to be a column, not a hidden intermediate. |
| B-06 | `discount` (header), `line_discount` (lines) | `discount_total = Σ header discount`; `line_discount_total = Σ line_discount`; `unallocated_discount = discount_total - line_discount_total` | `fct_daily_sales.discount_total`, `line_discount_total`, `unallocated_discount` | 75 sales carry a discount that no line knows about (F-03). Publishing the gap keeps the product-level discount honest without inventing an allocation. |
| B-07 | `payments.amount`, `method`, `status` | `Σ amount` where status is `LIVE`, split by mapped method | `settled_total`, `cash_total`, `card_total`, `custom_order_total` | How the money arrived. Kept separate from revenue because a sale can be settled after its day closes, or by more than one payment. F-13 |
| B-08 | `quantity` | `Σ quantity` over live lines | `fct_daily_sales.units_sold`, `fct_daily_product_demand.quantity_sold` | Units are not comparable to money and are needed separately for demand. |
| B-09 | `total`, `transaction_count` | `gross_revenue / NULLIF(transaction_count, 0)` | `avg_transaction_value` | Basket size, and the first number to look at when revenue moves without a volume change. NULL on a zero-transaction day (S-03). |
| B-10 | `revenue_costed`, `line_revenue_total`, `line_discount_total`, `cogs` | `itemised_revenue = line_revenue_total - line_discount_total`; `cogs_coverage_pct = 100 × revenue_costed / itemised_revenue`; `gross_profit_costed = revenue_costed - cogs`; `margin_pct_costed = 100 × gross_profit_costed / revenue_costed`; `gross_profit = net_revenue - cogs` **only when coverage = 100**, else NULL; `margin_pct` NULL on the same condition | `gross_profit`, `margin_pct`, `gross_profit_costed`, `margin_pct_costed`, `cogs_coverage_pct` | Cost is known for 6.9 % of itemised revenue (F-09). A whole-day profit that treats the other 93 % of goods as free would be a fabricated number; the costed slice is real, and it is published with the coverage that qualifies it. Coverage is measured against **itemised** revenue, not `net_revenue`, so both sides of the ratio are at the same discount level — comparing a line-level numerator to a header-level denominator produced a 100.1 % coverage in the 2026-09-30 batch, which is how the mistake was caught. |
| B-11 | `reorder_level`, `stock` | `stock_status`: `critical` when `stock_on_hand = 0`; `warning` when `stock_on_hand <= reorder_level`; else `healthy` | `fct_daily_stock_snapshot.stock_status` | Turns two integers into the one word a shopkeeper acts on. |
| B-12 | `stock` | Snapshot value per business date, never summed across dates | `fct_daily_stock_snapshot.stock_on_hand` | Stock is a point-in-time measure: summing a week of snapshots gives a number with no meaning. Semi-additive, and documented as such. |
| B-13 | `quantity_sold`, `demand_window_days` | `avg_daily_demand = Σ quantity_sold over the trailing window / demand_window_days`; `forecast_demand_30d = 30 × avg_daily_demand`; `recommended_reorder = greatest(0, ceil(forecast_demand_30d - stock_on_hand))` | `avg_daily_demand`, `forecast_demand_30d`, `recommended_reorder` | The reorder figure the inventory screen needs. The 30-day forecast is Lab 2's stated placeholder for a model that does not exist yet, and it is labelled as a straight-line projection, not a prediction. |
| B-14 | `orders.amount`, `status`, `is_custom` | `Σ amount`, `count(*)`, `Σ (is_custom)` per status | `order_count`, `order_value`, `custom_order_count` | Where the production work sits, and what it is worth. |
| B-15 | `order_value`, `order_count` | `order_value / NULLIF(order_count, 0)` | `avg_order_value` | Distinguishes "more orders" from "bigger orders". |
| B-16 | `created_at` | Year, quarter, month, ISO week, day of week, weekend flag | `dim_date` columns | Monthly and weekly reporting without a date function in every query. |

### 5.3 Joins and lookups

| Rule | From | To | Join key | Type | Unmatched records |
| --- | --- | --- | --- | --- | --- |
| J-01 | `sales_transaction_items` | `dim_item` | `item_ref`, and the version valid on the line's `business_date` (`valid_from <= d < COALESCE(valid_to, 'infinity')`) | Inner | Quarantine (`unresolved_dimension_key`, C-21). It cannot happen for a name-derived ref, which is the point of C-02. |
| J-02 | `sales_transactions` | `dim_branch` | `branch_id`, version valid on `business_date` | Inner | Quarantine. Stage 1 guarantees `branch_id` is `NOT NULL` and `branches` is extracted in full, so a miss means the snapshot is wrong. |
| J-03 | `sales_transaction_items` | `sales_transactions` | `transaction_id` | Inner | Quarantine (C-18) |
| J-04 | `payments` | `sales_transactions` | `transaction_id` | Inner | Quarantine (C-19) |
| J-05 | `orders` | `dim_order_status` | `status` | Inner | Quarantine (C-16) |
| J-06 | `orders` | `dim_branch` | `branch_id` | Inner | Quarantine (J-02 rule) |
| J-07 | `fct_daily_stock_snapshot` | `fct_daily_product_demand` | `(business_date, branch_key, item_key)` | **Left** | No match is normal: an item that did not sell has no demand row, and its `avg_daily_demand` is 0 |
| J-08 | facts | `dim_date` | `business_date = date_key` | Inner | Impossible by construction — `dim_date` is generated for every date in the batch window first (step 3 of §1.4) |

**Cardinality is stated, not assumed.** Every join above is many-to-one: a line has exactly one
product version on a given day, a sale exactly one branch version, an order exactly one status.
T7 checks it — the number of fact rows must not exceed the number of input rows for the same grain,
and a join that multiplies rows fails the batch rather than inflating revenue. The dimension
versions are the only place where a many-to-one join could silently become many-to-many (two open
versions of the same product), which is why T15 checks that exactly one version of each natural key
is current.

### 5.4 Filtering and conditional logic

| Rule | Target | Condition | Action | Records |
| --- | --- | --- | --- | --- |
| X-01 | `sales_transactions` | `status = 'VOID'` | **Exclude from revenue.** The sale is counted in `voided_count` and its total in `voided_amount`. | 16 of 867 (1.8 %); 12 of the 18 in the 2026-10-02 batch |
| X-02 | `payments` | `status = 'VOID'` | **Exclude from `settled_total`** | 16 of 867 |
| X-03 | `sales_transaction_items` | The parent sale is voided | **Exclude from the product fact** | the voided sales' lines |
| X-04 | `orders` | `created_at` (Manila) is not in the batch window | **Exclude from the order fact**, counted by C-06 | 23 orders are extracted per night; on 2026-10-02, **none** of them was raised in the window |
| X-05 | all facts | `business_date` outside the batch window | **Exclude and fail** — this is T13, not a filter | 0 |

**Voided records are extracted on purpose and excluded here.** Stage 1 deliberately copies them
(§1.4 of the extraction contract: "Cancelled and voided records **are** extracted — they are
filtered out later, in Transformation"). Stage 2 is the later. A void is not a data-quality
problem to be cleaned away: it is a business event, and it is reported as a count and an amount so
the shop can see how much it voided, not just what it kept.

### 5.5 Dimensional modelling steps

| Rule | Step | Detail |
| --- | --- | --- |
| M-01 | `dim_date` | Generated for every date in `[batch_window_start - DEMAND_WINDOW_DAYS, business_date]`, so the trailing demand window in B-13 always has dates to join. `INSERT … ON CONFLICT (date_key) DO NOTHING` — a date is never rewritten. |
| M-02 | `dim_branch` | SCD **Type 2**. Attributes: `code`, `name`, `is_active`, `vat_rate`, `currency_symbol`, `time_zone`. Compared against the current version each batch; a difference closes the current version (`valid_to = business_date`, `is_current = false`) and opens a new one (`valid_from = business_date`). `branch_key` is assigned once, on first insert, and survives every later version and every rerun. |
| M-03 | `dim_item` | SCD **Type 2**. Attributes: `item_name`, `inventory_item_id`, `sku`, `category`, `uom`, `unit_price`, `unit_cost`, `is_catalogue_item`. A price or cost change, or a product being added to the catalogue, opens a new version. `stock_on_hand` is deliberately **not** an attribute — it changes daily, and versioning on it would create a new dimension row every night for every product (P7). |
| M-04 | `dim_order_status` | **Static.** Seeded by migration `003` with the six statuses, their funnel order, and their backlog/terminal flags. Never derived from the batch, so a seventh status fails T16 instead of quietly becoming a dimension row. |
| M-05 | Surrogate keys | `bigint GENERATED BY DEFAULT AS IDENTITY` for `branch_key` and `item_key`; `smallint` for `status_key`; `date` for `date_key`. Assigned by the database, never computed by the transformation, so two concurrent batches cannot mint the same key. |
| M-06 | Version validity | `valid_from` is **inclusive**, `valid_to` is **exclusive**, and `valid_to IS NULL` means "still current". A fact row joins the version where `valid_from <= business_date < valid_to`. Half-open intervals are used because a closed interval makes the boundary day belong to two versions. |
| M-07 | SCD Type 1 where history is worthless | `dim_item.category` corrections for a mis-categorised product are still Type 2 here, because the dimension is small and a category change genuinely changes how history should be read. The exception is `'Uncategorised'` (C-04), which is a default, not a change. |

### 5.6 Aggregations

| Rule | Fact | Grouping level | Measures | Source |
| --- | --- | --- | --- | --- |
| A-01 | `fct_daily_sales` | `business_date × branch_key` | `transaction_count`, `line_count`, `units_sold`, `gross_revenue`, `net_revenue`, `tax_total`, `line_revenue_total`, `discount_total`, `line_discount_total`, `unallocated_discount`, `cogs`, `revenue_costed`, `cogs_coverage_pct`, `gross_profit`, `margin_pct`, `gross_profit_costed`, `margin_pct_costed`, `avg_transaction_value`, `settled_total`, `cash_total`, `card_total`, `custom_order_total`, `voided_count`, `voided_amount` | Live sales for the date, their live lines, and their live payments |
| A-02 | `fct_daily_product_demand` | `business_date × branch_key × item_key` | `line_count`, `quantity_sold`, `line_revenue`, `discount_total`, `revenue`, `cogs`, `is_costed`, `demand_window_days`, `avg_daily_demand`, `forecast_demand_30d` | Live lines grouped by product |
| A-03 | `fct_daily_order_status` | `business_date × branch_key × status_key` | `order_count`, `order_value`, `custom_order_count`, `avg_order_value` | Orders raised that day, grouped by status |
| A-04 | `fct_daily_product_demand` | **Only products that sold** — no densification | all of A-02 | A zero row would be indistinguishable from a day the batch never processed. The unsold items a reorder decision needs are in the stock snapshot (A-07), which is where stock belongs. |
| A-05 | `fct_daily_order_status` | **Densified** — all six statuses appear for every `(date, branch)` that has at least one order | all of A-03 | A funnel with a missing step reads as a broken funnel. A branch with no orders at all gets no rows, so "no orders" is not confused with "no data". |
| A-06 | `fct_daily_sales` | **Not** densified — a row exists for every `(date, branch)` that appears in the batch's sales rows, including a day whose sales were all voided | all of A-01 | A day with zero revenue because everything was voided is a real, reportable fact (`transaction_count = 0`, `voided_count = 4` on 2026-10-02). A day with no sales at all is recorded by the extraction's closed-day flag, not invented here. |
| A-07 | `fct_daily_stock_snapshot` | `business_date × branch_key × item_key` — **every catalogue item in the branch, target date only** | `stock_on_hand`, `reorder_level`, `stock_status`, `recommended_reorder` | The only fact written for one date instead of four. Demand is rebuilt for the whole look-back because voids change it; stock is a snapshot of the night the batch ran, and rebuilding an old date's stock with tonight's catalogue would destroy the record of what was on the shelf then (D10). |

### 5.7 What changed since Lab 2

Lab 2's target schema was proposed before the data was profiled and before multi-branch scoping
landed. Seven deliberate changes follow, each traceable to a finding or a Stage 1 decision.

| # | Lab 2 | This document | Why |
| --- | --- | --- | --- |
| 1 | `fct_daily_sales` is one row per `business_date` | One row per `business_date × branch` | `branch_id` became `NOT NULL` on every transaction table on 2 October 2026. A day-level row would discard a dimension the data now carries. |
| 2 | No date, branch, or status dimension | `dim_date`, `dim_branch`, `dim_order_status` added | Reporting needs a calendar, a branch label, and a funnel order. All three were being re-derived in every query. |
| 3 | Facts keyed on natural keys (`inventory_item_id`) | Facts keyed on surrogate keys (`item_key`, `branch_key`, `status_key`) | A product's price and cost change; a fact row must keep pointing at the version that was true on its day (M-03, M-06). |
| 4 | `fct_daily_product_demand` carries `stock_on_hand`, `recommended_reorder`, `status` | Stock split into `fct_daily_stock_snapshot` | A look-back rebuild would overwrite history's stock with tonight's. See §6 and D10. |
| 5 | Product demand keyed on `inventory_item_id` | Keyed on `item_ref`, a name-based identity | 93.4 % of lines have no catalogue link (F-01). |
| 6 | `gross_profit` and `margin_pct` always populated | NULL unless cost coverage is complete; costed variants added | 6.9 % coverage (F-09). A whole-day profit would be fabricated. |
| 7 | `fct_daily_sales.expense_total` | Not produced | Stage 1 does not extract `operating_expenses`, and already said so (L11 there). The column is absent rather than permanently zero. |

The table names keep Lab 2's `fct_` and `dim_` prefixes rather than the laboratory template's
`fact_`, because Stage 1 §6.2 reserved exactly those prefixes for this stage. The convention that
matters — a prefix that states the table's role — is already published, and renaming would break a
contract to satisfy an example.

---

## 6. Transformed Data Contract and Naming Convention

### 6.1 Required output schema

Eleven tables in `psync_analytics`, all created by `pipeline/migrations/003_transformation_schema.sql`.
Types, nullability and keys are the contract; a column not listed here does not exist.

**`dim_date`** — one row per calendar date, generated.

| Column | Type | Null | Key | Note |
| --- | --- | --- | --- | --- |
| `date_key` | `date` | no | PK | The calendar date itself (S-06) |
| `year` | `smallint` | no | | |
| `quarter` | `smallint` | no | | 1–4 |
| `month` | `smallint` | no | | 1–12 |
| `month_name` | `text` | no | | `January` … `December` |
| `day_of_month` | `smallint` | no | | 1–31 |
| `iso_week` | `smallint` | no | | 1–53 |
| `day_of_week` | `smallint` | no | | 1 = Monday … 7 = Sunday |
| `day_name` | `text` | no | | `Monday` … `Sunday` |
| `is_weekend` | `boolean` | no | | |

**`dim_branch`** — one row per branch version (SCD Type 2).

| Column | Type | Null | Key | Note |
| --- | --- | --- | --- | --- |
| `branch_key` | `bigint` identity | no | PK | Surrogate |
| `branch_id` | `uuid` | no | unique with `valid_from` | Natural key, `branches.id` |
| `code` | `text` | no | | Trimmed (C-10) |
| `name` | `text` | no | | Trimmed |
| `is_active` | `boolean` | no | | |
| `vat_rate` | `numeric(5,2)` | no | | 12.00, per cent (S-20) |
| `currency_symbol` | `text` | no | | `₱` |
| `time_zone` | `text` | no | | `Asia/Manila` |
| `valid_from` | `date` | no | | Inclusive |
| `valid_to` | `date` | yes | | Exclusive; NULL = current |
| `is_current` | `boolean` | no | | Exactly one true per `branch_id` (T15) |

**`dim_item`** — one row per product version (SCD Type 2).

| Column | Type | Null | Key | Note |
| --- | --- | --- | --- | --- |
| `item_key` | `bigint` identity | no | PK | Surrogate |
| `item_ref` | `text` | no | unique with `valid_from` | Natural key, `name:<normalised>` (S-12) |
| `item_name` | `text` | no | | Original casing, trimmed (C-10) |
| `inventory_item_id` | `uuid` | yes | | NULL when the product is not in the catalogue (C-02) |
| `sku` | `text` | yes | | Upper-cased (S-11); NULL when not catalogued |
| `category` | `text` | no | | `Uncategorised` when unknown (C-04) |
| `uom` | `text` | yes | | Label only, never arithmetic (S-18) |
| `unit_price` | `numeric(14,2)` | yes | | Catalogue price; NULL when not catalogued |
| `unit_cost` | `numeric(14,2)` | yes | | NULL when unknown — never 0 (C-05) |
| `is_catalogue_item` | `boolean` | no | | |
| `valid_from` | `date` | no | | Inclusive |
| `valid_to` | `date` | yes | | Exclusive; NULL = current |
| `is_current` | `boolean` | no | | Exactly one true per `item_ref` (T15) |

**`dim_order_status`** — six rows, seeded.

| Column | Type | Null | Key | Note |
| --- | --- | --- | --- | --- |
| `status_key` | `smallint` | no | PK | 1–6 |
| `status_name` | `text` | no | unique | The source spelling |
| `status_order` | `smallint` | no | | Funnel position, 1 = `Pending` |
| `is_backlog` | `boolean` | no | | Work still in hand: Pending, Designing, In Production, Ready for Pickup |
| `is_terminal` | `boolean` | no | | Completed, Delivered |

**`fct_daily_sales`** — one row per `business_date × branch`.

| Column | Type | Null | Key | Note |
| --- | --- | --- | --- | --- |
| `business_date` | `date` | no | PK, FK → `dim_date` | Manila day (S-01) |
| `branch_key` | `bigint` | no | PK, FK → `dim_branch` | |
| `transaction_count` | `integer` | no | | Live sales |
| `line_count` | `integer` | no | | Live sale lines |
| `units_sold` | `integer` | no | | `Σ quantity` |
| `gross_revenue` | `numeric(14,2)` | no | | VAT-inclusive (B-01) |
| `net_revenue` | `numeric(14,2)` | no | | VAT-exclusive, after all discounts (B-02) |
| `tax_total` | `numeric(14,2)` | no | | |
| `line_revenue_total` | `numeric(14,2)` | no | | Itemised revenue, pre-discount (B-05) |
| `discount_total` | `numeric(14,2)` | no | | Header discounts (B-06) |
| `line_discount_total` | `numeric(14,2)` | no | | |
| `unallocated_discount` | `numeric(14,2)` | no | | `discount_total - line_discount_total`, `>= 0` (T4) |
| `cogs` | `numeric(14,2)` | no | | Known-cost only |
| `revenue_costed` | `numeric(14,2)` | no | | Itemised revenue whose cost is known |
| `cogs_coverage_pct` | `numeric(6,2)` | no | | 0.00–100.00 (B-10) |
| `gross_profit` | `numeric(14,2)` | **yes** | | NULL unless coverage = 100 (B-10) |
| `margin_pct` | `numeric(6,2)` | **yes** | | NULL unless coverage = 100 |
| `gross_profit_costed` | `numeric(14,2)` | no | | The costed slice's profit |
| `margin_pct_costed` | `numeric(6,2)` | yes | | NULL when `revenue_costed = 0` |
| `avg_transaction_value` | `numeric(14,2)` | yes | | NULL when `transaction_count = 0` |
| `settled_total` | `numeric(14,2)` | no | | Captured payments (B-07) |
| `cash_total` | `numeric(14,2)` | no | | |
| `card_total` | `numeric(14,2)` | no | | |
| `custom_order_total` | `numeric(14,2)` | no | | |
| `voided_count` | `integer` | no | | |
| `voided_amount` | `numeric(14,2)` | no | | |

The arithmetic that ties the money columns together, and which T4 and T12 enforce:

```
net_revenue        = line_revenue_total - line_discount_total - unallocated_discount
unallocated_discount = discount_total - line_discount_total
gross_revenue      = net_revenue + tax_total
```

**`fct_daily_product_demand`** — one row per `business_date × branch × item` that sold.

| Column | Type | Null | Key | Note |
| --- | --- | --- | --- | --- |
| `business_date` | `date` | no | PK, FK → `dim_date` | |
| `branch_key` | `bigint` | no | PK, FK → `dim_branch` | |
| `item_key` | `bigint` | no | PK, FK → `dim_item` | |
| `line_count` | `integer` | no | | |
| `quantity_sold` | `integer` | no | | |
| `line_revenue` | `numeric(14,2)` | no | | Pre-discount, VAT-exclusive |
| `discount_total` | `numeric(14,2)` | no | | Line discounts only |
| `revenue` | `numeric(14,2)` | no | | `line_revenue - discount_total` |
| `cogs` | `numeric(14,2)` | no | | 0 when the cost is unknown — read `is_costed` before using it |
| `is_costed` | `boolean` | no | | True when `dim_item.unit_cost` is known for this product version |
| `demand_window_days` | `smallint` | no | | Days actually present in the window (B-13) |
| `avg_daily_demand` | `numeric(10,2)` | no | | |
| `forecast_demand_30d` | `numeric(10,2)` | no | | `30 × avg_daily_demand` |

**`fct_daily_stock_snapshot`** — one row per `business_date × branch × catalogue item`, target date
only.

| Column | Type | Null | Key | Note |
| --- | --- | --- | --- | --- |
| `business_date` | `date` | no | PK, FK → `dim_date` | The date the batch ran for (D10) |
| `branch_key` | `bigint` | no | PK, FK → `dim_branch` | |
| `item_key` | `bigint` | no | PK, FK → `dim_item` | Catalogue items only |
| `stock_on_hand` | `integer` | no | | Semi-additive (B-12) |
| `reorder_level` | `integer` | no | | |
| `stock_status` | `text` | no | | `healthy` / `warning` / `critical` (B-11) |
| `recommended_reorder` | `integer` | no | | `>= 0` (B-13) |

**`fct_daily_order_status`** — one row per `business_date × branch × status`.

| Column | Type | Null | Key | Note |
| --- | --- | --- | --- | --- |
| `business_date` | `date` | no | PK, FK → `dim_date` | |
| `branch_key` | `bigint` | no | PK, FK → `dim_branch` | |
| `status_key` | `smallint` | no | PK, FK → `dim_order_status` | |
| `order_count` | `integer` | no | | |
| `order_value` | `numeric(14,2)` | no | | |
| `custom_order_count` | `integer` | no | | |
| `avg_order_value` | `numeric(14,2)` | yes | | NULL when `order_count = 0` |

**`quarantine_rows`** — records that could not be safely transformed.

| Column | Type | Null | Key | Note |
| --- | --- | --- | --- | --- |
| `quarantine_id` | `bigserial` | no | PK | |
| `batch_id` | `text` | no | unique with the next three | `TRF_20261002_9f1c0b6e` |
| `run_id` | `uuid` | no | | The transformation run |
| `parent_run_id` | `uuid` | no | | The extraction run it came from |
| `business_date` | `date` | no | | |
| `source_table` | `text` | no | unique with `batch_id` | `sales_transaction_items` |
| `source_id` | `text` | no | unique with `batch_id` | Text, because keys are `uuid` in six tables and `integer` in `business_settings` |
| `rule_id` | `text` | no | unique with `batch_id` | `C-01`, `C-13`, … |
| `reason` | `text` | no | | `missing_product_name`, `invalid_line_value`, … |
| `detail` | `text` | yes | | Human-readable: the column and the offending value |
| `payload` | `jsonb` | no | | The offending row, this stage's columns only. No customer data — none is extracted. |
| `quarantined_at` | `timestamptz` | no | | |

**`transformation_runs`** — one row per output table per batch, plus one run-level row
(`table_name IS NULL`). Same grain as `pipeline_runs`, so the two read alike.

| Column | Type | Null | Note |
| --- | --- | --- | --- |
| `run_id` | `uuid` | no | This batch's run |
| `batch_id` | `text` | no | `TRF_<YYYYMMDD>_<parent_run_id[:8]>` |
| `parent_run_id` | `uuid` | no | The extraction run. A **logical** reference: `pipeline_runs` has no single-column key (Stage 1 §4), so no foreign key can be declared. |
| `pipeline_name` | `text` | no | `psync_nightly_analytics` |
| `business_date` | `date` | no | The target day |
| `batch_window_start` | `date` | no | `business_date - lookback_days` |
| `batch_window_end` | `date` | no | `business_date` |
| `table_name` | `text` | yes | NULL on the run-level row |
| `transformation_started_at` | `timestamptz` | no | |
| `transformation_ended_at` | `timestamptz` | yes | |
| `transformation_duration_seconds` | `integer` | yes | |
| `transformation_status` | `text` | no | `running` / `success` / `failed` / `skipped` |
| `records_read` | `integer` | no | Rows in staging for this `run_id` |
| `records_output` | `integer` | no | Rows written to this table |
| `records_rejected` | `integer` | no | Rows quarantined |
| `records_modified` | `integer` | no | Sum of the rule counts. **Not** part of the reconciliation (§7) |
| `validation_results` | `jsonb` | yes | `{"T1":"PASS", …}` |
| `decision` | `text` | yes | `APPROVED` / `APPROVED WITH WARNING` / `MANUAL REVIEW` / `REJECTED` / `SKIPPED` |
| `error_code` | `text` | yes | |
| `error_message` | `text` | yes | |
| `code_version` | `text` | no | `psync_transform 0.1.0 / rules 1.0` |

**`transformation_rule_counts`** — how many records each rule touched, as rows.

| Column | Type | Null | Note |
| --- | --- | --- | --- |
| `batch_id` | `text` | no | PK with the next two |
| `table_name` | `text` | no | PK |
| `rule_id` | `text` | no | PK |
| `business_date` | `date` | no | |
| `records_affected` | `integer` | no | |

### 6.2 Naming convention

| Rule | Detail |
| --- | --- |
| Case | `snake_case` throughout. |
| Table prefixes | `dim_` for dimensions, `fct_` for facts, `quarantine_` for the quarantine, `transformation_` for this stage's metadata. Stage 1 reserved `fct_` and `dim_` for this stage (Stage 1 §6.2), so they are used as reserved rather than replaced by the template's `fact_` (§5.7). |
| Surrogate keys | Suffix `_key`, and the type is a generated integer: `branch_key`, `item_key`, `status_key`. `date_key` is the date itself (§5.1). |
| Natural keys | Suffix `_id`, kept from the source: `branch_id`, `inventory_item_id`. `item_ref` is the one exception, because it is not an id from any system — it is this stage's product identity, and the `name:` prefix says so. |
| Facts | Named for what they measure, with the grain in the name: `fct_daily_sales`, `fct_daily_product_demand`, `fct_daily_stock_snapshot`, `fct_daily_order_status`. A query cannot be written at the wrong level by accident. |
| Measures | Named for the question they answer, not the formula: `gross_revenue` / `net_revenue` (before and after tax), `line_revenue` / `revenue` (before and after discount). A measure whose name hides its VAT or discount basis is a measure that gets compared to the wrong thing. |
| Money | Suffix nothing; type `numeric(14,2)`. Counts are `integer`, percentages end in `_pct` and are `numeric(6,2)`. |
| Timestamps | `_at` for an instant, `_date` for a calendar day, `_from` / `_to` for a version's validity. |
| Rule IDs | `C-` cleaning, `S-` standardisation, `B-` business, `M-` modelling, `J-` join, `X-` exclusion, `A-` aggregation, `T-` validation. A rule ID in a log line or a quarantine row points at exactly one row of this document. |

### 6.3 Source-to-target mapping

Every output column, its origin, and the rule that produced it. `stg_*` columns are the input
contract (Stage 1 §6.1); nothing here reads PRINTSYNC.

**Dimensions**

| Source column | Target column | Source type | Target type | Transformation applied |
| --- | --- | --- | --- | --- |
| — (generated) | `dim_date.date_key` | — | `date` | Generated from the batch window (M-01) |
| — (generated) | `dim_date.year` … `is_weekend` | — | `smallint` / `text` / `boolean` | Derived from the date (B-16) |
| `stg_branches.source_id` | `dim_branch.branch_id` | `uuid` | `uuid` | Rename only |
| `stg_branches.code` | `dim_branch.code` | `text` | `text` | Trim, collapse (C-10) |
| `stg_branches.name` | `dim_branch.name` | `text` | `text` | Trim, collapse (C-10) |
| `stg_branches.is_active` | `dim_branch.is_active` | `boolean` | `boolean` | Pass-through |
| `stg_business_settings.vat_rate` | `dim_branch.vat_rate` | `numeric(14,2)` | `numeric(5,2)` | Narrowed; read as a percentage (S-20) |
| `stg_business_settings.currency_symbol` | `dim_branch.currency_symbol` | `text` | `text` | Pass-through (S-19) |
| `stg_business_settings.time_zone` | `dim_branch.time_zone` | `text` | `text` | Pass-through |
| — (generated) | `dim_branch.branch_key` | — | `bigint` | Surrogate, assigned once (M-05) |
| — (batch date) | `dim_branch.valid_from`, `valid_to`, `is_current` | — | `date` / `boolean` | SCD Type 2 (M-02, M-06) |
| `stg_sales_transaction_items.name` | `dim_item.item_name` | `text` | `text` | Trim, collapse (C-10, C-11) |
| `stg_sales_transaction_items.name` | `dim_item.item_ref` | `text` | `text` | `'name:' \|\| normalise(name)` (C-02, S-12) |
| `stg_sales_transaction_items.inventory_item_id` | `dim_item.inventory_item_id` | `uuid` | `uuid` | NULL when absent (C-02) |
| `stg_inventory_items.sku` | `dim_item.sku` | `text` | `text` | Upper-case, trim (S-11) |
| `stg_inventory_items.name` | `dim_item.item_ref`, `item_name` | `text` | `text` | Same normalisation, so a catalogue item and a sold product with the same name are one product |
| `stg_inventory_items.category` | `dim_item.category` | `text` | `text` | Trim; `Uncategorised` when blank (C-04) |
| `stg_inventory_items.uom` | `dim_item.uom` | `text` | `text` | Lower-case, trim (S-18) |
| `stg_inventory_items.price` | `dim_item.unit_price` | `numeric(14,2)` | `numeric(14,2)` | Pass-through |
| `stg_inventory_items.cost_price` | `dim_item.unit_cost` | `numeric(14,2)` | `numeric(14,2)` | NULL when unknown, never 0 (C-05) |
| — (derived) | `dim_item.is_catalogue_item` | — | `boolean` | `inventory_item_id IS NOT NULL` |
| — (generated) | `dim_item.item_key` | — | `bigint` | Surrogate, assigned once (M-05) |
| — (batch date) | `dim_item.valid_from`, `valid_to`, `is_current` | — | `date` / `boolean` | SCD Type 2 (M-03, M-06) |
| — (migration 003) | `dim_order_status.*` | — | `smallint` / `text` / `boolean` | Seeded, never derived (M-04) |

**`fct_daily_sales`**

| Source column | Target column | Source type | Target type | Transformation applied |
| --- | --- | --- | --- | --- |
| `stg_sales_transactions.created_at` | `business_date` | `timestamptz` | `date` | Manila day (S-01) |
| `stg_sales_transactions.branch_id` | `branch_key` | `uuid` | `bigint` | Lookup on the valid version (J-02) |
| `stg_sales_transactions.source_id` | `transaction_count` | `uuid` | `integer` | `count(*)` where status is LIVE (X-01) |
| `stg_sales_transaction_items.source_id` | `line_count` | `uuid` | `integer` | `count(*)` over live lines (A-01) |
| `stg_sales_transaction_items.quantity` | `units_sold` | `integer` | `integer` | `Σ quantity` (B-08) |
| `stg_sales_transactions.total` | `gross_revenue` | `numeric(14,2)` | `numeric(14,2)` | `Σ total` (B-01) |
| `stg_sales_transactions.total`, `tax` | `net_revenue` | `numeric(14,2)` | `numeric(14,2)` | `Σ total - Σ tax` (B-02) |
| `stg_sales_transactions.tax` | `tax_total` | `numeric(14,2)` | `numeric(14,2)` | `Σ tax` |
| `quantity`, `unit_price` | `line_revenue_total` | `integer`, `numeric(14,2)` | `numeric(14,2)` | `Σ quantity × unit_price` (B-05) |
| `stg_sales_transactions.discount` | `discount_total` | `numeric(14,2)` | `numeric(14,2)` | `Σ discount` (B-06) |
| `stg_sales_transaction_items.line_discount` | `line_discount_total` | `numeric(14,2)` | `numeric(14,2)` | `Σ line_discount` |
| both of the above | `unallocated_discount` | — | `numeric(14,2)` | `discount_total - line_discount_total` (B-06) |
| `stg_inventory_items.cost_price` | `cogs` | `numeric(14,2)` | `numeric(14,2)` | `Σ quantity × unit_cost` where the cost is known (B-04) |
| `unit_price`, `line_discount` | `revenue_costed` | `numeric(14,2)` | `numeric(14,2)` | `Σ (quantity × unit_price - line_discount)` for costed lines |
| both of the above | `cogs_coverage_pct` | — | `numeric(6,2)` | `100 × revenue_costed / (line_revenue_total - line_discount_total)` (B-10) |
| — (derived) | `gross_profit` | — | `numeric(14,2)` | `net_revenue - cogs`, **NULL unless coverage = 100** (B-10) |
| — (derived) | `margin_pct` | — | `numeric(6,2)` | `100 × gross_profit / net_revenue`, same NULL rule |
| — (derived) | `gross_profit_costed` | — | `numeric(14,2)` | `revenue_costed - cogs` |
| — (derived) | `margin_pct_costed` | — | `numeric(6,2)` | `100 × gross_profit_costed / revenue_costed`, NULL when 0 |
| `total`, `transaction_count` | `avg_transaction_value` | — | `numeric(14,2)` | `gross_revenue / NULLIF(transaction_count, 0)` (B-09) |
| `stg_payments.amount` | `settled_total` | `numeric(14,2)` | `numeric(14,2)` | `Σ amount` where status is LIVE (B-07, X-02) |
| `stg_payments.amount`, `method` | `cash_total` | `numeric(14,2)` | `numeric(14,2)` | `Σ amount` where method is CASH (S-13) |
| `stg_payments.amount`, `method` | `card_total` | `numeric(14,2)` | `numeric(14,2)` | `Σ amount` where method is CARD |
| `stg_payments.amount`, `method` | `custom_order_total` | `numeric(14,2)` | `numeric(14,2)` | `Σ amount` where method is CUSTOM_ORDER |
| `stg_sales_transactions.status` | `voided_count` | `text` | `integer` | `count(*)` where status is VOID (X-01) |
| `stg_sales_transactions.total` | `voided_amount` | `numeric(14,2)` | `numeric(14,2)` | `Σ total` where status is VOID |

**`fct_daily_product_demand`**

| Source column | Target column | Source type | Target type | Transformation applied |
| --- | --- | --- | --- | --- |
| `stg_sales_transactions.created_at` | `business_date` | `timestamptz` | `date` | Manila day (S-01) |
| `stg_sales_transactions.branch_id` | `branch_key` | `uuid` | `bigint` | Lookup (J-02) |
| `name`, `inventory_item_id` | `item_key` | `text`, `uuid` | `bigint` | Resolve `item_ref`, then the valid version (B-03, J-01) |
| `stg_sales_transaction_items.source_id` | `line_count` | `uuid` | `integer` | `count(*)` |
| `stg_sales_transaction_items.quantity` | `quantity_sold` | `integer` | `integer` | `Σ quantity` (B-08) |
| `quantity`, `unit_price` | `line_revenue` | `integer`, `numeric(14,2)` | `numeric(14,2)` | `Σ quantity × unit_price` (B-04) |
| `line_discount` | `discount_total` | `numeric(14,2)` | `numeric(14,2)` | `Σ line_discount` |
| both of the above | `revenue` | — | `numeric(14,2)` | `line_revenue - discount_total` |
| `quantity`, `cost_price` | `cogs` | `numeric(14,2)` | `numeric(14,2)` | `Σ quantity × unit_cost` where known (B-04) |
| — (derived) | `is_costed` | — | `boolean` | `dim_item.unit_cost IS NOT NULL` |
| — (counted) | `demand_window_days` | — | `smallint` | Days present in the trailing window (B-13) |
| — (derived) | `avg_daily_demand` | — | `numeric(10,2)` | `Σ quantity_sold / demand_window_days` (B-13) |
| — (derived) | `forecast_demand_30d` | — | `numeric(10,2)` | `30 × avg_daily_demand` |

**`fct_daily_stock_snapshot`**

| Source column | Target column | Source type | Target type | Transformation applied |
| --- | --- | --- | --- | --- |
| — (batch target date) | `business_date` | — | `date` | The date the batch ran for (A-07) |
| `stg_inventory_items.branch_id` | `branch_key` | `uuid` | `bigint` | Lookup (J-02) |
| `stg_inventory_items.name`, `source_id` | `item_key` | `text`, `uuid` | `bigint` | Resolve `item_ref`, then the valid version (B-03, J-01) |
| `stg_inventory_items.stock` | `stock_on_hand` | `integer` | `integer` | Pass-through (B-12) |
| `stg_inventory_items.reorder_level` | `reorder_level` | `integer` | `integer` | Pass-through |
| `stock`, `reorder_level` | `stock_status` | — | `text` | Thresholds in B-11 |
| `forecast_demand_30d`, `stock` | `recommended_reorder` | — | `integer` | `greatest(0, ceil(forecast - stock_on_hand))`, 0 when the item never sold (B-13, J-07) |

**`fct_daily_order_status`**

| Source column | Target column | Source type | Target type | Transformation applied |
| --- | --- | --- | --- | --- |
| `stg_orders.created_at` | `business_date` | `timestamptz` | `date` | Manila day (S-01); the cohort filter (X-04) |
| `stg_orders.branch_id` | `branch_key` | `uuid` | `bigint` | Lookup (J-06) |
| `stg_orders.status` | `status_key` | `text` | `smallint` | Code map (S-17, J-05) |
| `stg_orders.source_id` | `order_count` | `uuid` | `integer` | `count(*)`, 0 for a status with no orders (A-05) |
| `stg_orders.amount` | `order_value` | `numeric(14,2)` | `numeric(14,2)` | `Σ amount` |
| `stg_orders.is_custom` | `custom_order_count` | `boolean` | `integer` | `Σ (is_custom)::int` (B-14) |
| — (derived) | `avg_order_value` | — | `numeric(14,2)` | `order_value / NULLIF(order_count, 0)` (B-15) |

**The metadata tables are not mapped, and that is correct.** `transformation_runs`,
`transformation_rule_counts` and `quarantine_rows` have no source column: their values are this
stage's own bookkeeping — the batch ID, the counts, the rule IDs, the verdict — and they are
defined in §8. Mapping them to the input would be a category error.

**What is deliberately not mapped.** `expense_total` (Lab 2 §5.2) has no source: Stage 1 does not
extract `operating_expenses` because PRINTSYNC has no Expenses screen, so every row in that table
was placed by a demo seeder. Profit here is gross profit, as Stage 1 already stated (L11). The
column does not exist in the output rather than existing and always reading zero.

### 6.4 Schema consistency

The rule is the same as Stage 1's, and it is deliberately the same: **fail loudly, never guess.**

| Situation | Handling |
| --- | --- |
| A required staging column is missing | T1 fails before anything is read. This is exactly how D1 surfaces: no `name` column, no batch. |
| A column's type changed in staging | T1 compares against the expected type family (uuid, text, numeric, integer, timestamptz, boolean) and fails on a mismatch. Widening a type is still a failure until this document says otherwise. |
| A new column appears in staging | Ignored. Every rule names its columns, so an additive change cannot alter the output. |
| A new source table is added | Ignored until §1.3, §6.1 and §6.3 say what it produces. |
| A new order status appears | T16 fails. The status dimension is seeded, not derived, so a seventh value cannot become a row by accident. |
| The catalogue starts returning duplicate normalised names | T17 fails. Two catalogue items with one name would silently collapse into one product under C-02. |
| We genuinely need to change the contract | Correct this document first, then the migration, then the code. |

---

## 7. Transformation Validation and Data Quality Checks

Seventeen checks. Scope is limited to the transformed output: is it complete, is it internally
consistent, does it reconcile to its input, and does it obey the business rules. Stage 1's checks
that only prove the source was reachable or the copy was complete are **not** repeated — the
handover is taken as given, and only its counts are used as reference values.

**Reconciliation, stated once.** For every source table:

```
records_read  =  records_retained  +  records_quarantined
```

`records_modified` is **not** a term. A record that was cleaned and kept is retained, not rejected:
a trimmed name or a resolved product is still the same record. For the aggregating facts the
equation is on measures, not rows, because the output has a different grain from the input:

```
Σ fct_daily_sales.gross_revenue              =  Σ total of live sales            (per business_date)
Σ fct_daily_product_demand.revenue
  =  Σ fct_daily_sales.net_revenue
     + Σ fct_daily_sales.unallocated_discount                                     (per business_date)
Σ fct_daily_product_demand.quantity_sold     =  Σ quantity of live sale lines      (per business_date)
Σ fct_daily_order_status.order_value         =  Σ amount of the day's order cohort
records_output (stock snapshot)              =  catalogue items in the branch snapshot
```

| # | Check | Target | Purpose | Validation criteria | Severity |
| --- | --- | --- | --- | --- | --- |
| T1 | Input contract present | All seven staging tables | Prove the handover is the shape this stage expects before any rule runs | Every required column exists with its expected type family; the manifest's `decision` is `APPROVED` or `APPROVED WITH WARNING` | Critical |
| T2 | Handover integrity | Staging row counts | Prove the staged data is still the data that was handed over | For each table, `count(*)` in staging for this `run_id` equals the manifest's `rows_extracted` | Critical |
| T3 | Record reconciliation | All seven source tables | Prove no record vanished during cleaning | `records_read = records_retained + records_quarantined` for every table | Critical |
| T4 | Internal money arithmetic | `fct_daily_sales` | Prove the money columns describe the same day consistently | `net_revenue = line_revenue_total - line_discount_total - unallocated_discount`; `unallocated_discount = discount_total - line_discount_total >= 0`; `gross_revenue = net_revenue + tax_total` | Critical |
| T5 | Line-to-header identity | Sales and lines | Prove the line-level rebuild is arithmetically the header | `Σ (quantity × unit_price)` over live lines equals `Σ subtotal` over live sales | Critical |
| T6 | VAT conformance | `sales_transactions.tax` | Catch tax that does not match the configured rate | Per sale, `tax = round2(vat_rate/100 × (subtotal - discount))`. Every exception is counted; the check fails when exceptions exceed 1 % of live sales in the batch, or when the rate is zero or above 100 | Non-critical |
| T7 | Key uniqueness | Every output table | Prevent duplicates | Zero duplicate primary keys; zero duplicate `(natural key, valid_from)` in `dim_branch` and `dim_item` | Critical |
| T8 | Referential integrity | Every fact | Prevent orphans and row multiplication | 100 % of fact rows resolve their dimension key; fact row count does not exceed the input row count at the same grain; `branch_key`, `item_key`, `status_key` are the versions valid on the fact's `business_date` | Critical |
| T9 | Required columns not null | Every `NOT NULL` column in §6.1 | Prove the contract's nullability is real, not aspirational | Zero nulls in every `NOT NULL` output column | Critical |
| T10 | Cost coverage | `fct_daily_sales.cogs_coverage_pct` | Make the profit gap visible rather than silent | Recorded every batch. Below 95 % → warning; below 50 % → warning, and `gross_profit`/`margin_pct` must be NULL | Non-critical |
| T11 | Type and format conformance | `item_ref`, `sku`, dates, money | Prove standardisation actually happened | `item_ref` matches `^(name\|inventory):`; `sku` is upper-case or null; every money column has at most 2 decimals; every `business_date` equals the Manila date of its source timestamp | Critical |
| T12 | Aggregate reconciliation | All four facts | Prove the aggregates add up to their input | The five equations above hold per business date, to the cent | Critical |
| T13 | Business-date boundary | Every fact | Prove no row landed outside the batch | Every `business_date` is within `[batch_window_start, batch_window_end]`; the set of output dates equals the set of dates present in the batch's input | Critical |
| T14 | Non-empty output | `fct_daily_sales`, `fct_daily_stock_snapshot` | A silent zero is usually a broken rule, not a quiet day | At least one row for the target `business_date` in both, **unless** the extraction flagged the day closed | Non-critical |
| T15 | Version continuity | `dim_branch`, `dim_item` | Prove the SCD logic did not leave a gap or an overlap | Exactly one `is_current` row per natural key; no two versions overlap; `valid_from < valid_to` where `valid_to` is set | Critical |
| T16 | Status domain | `orders.status`, `sales_transactions.status` | Catch a status the dimension does not know | Every distinct status is in `dim_order_status` (orders) or in `('LIVE','VOID')` | Critical |
| T17 | Catalogue name uniqueness | `dim_item` | Protect the name-based identity | No two `is_current` catalogue rows share a normalised name | Critical |

**How severity is used.** A critical failure stops the batch before handover: nothing is written
for the affected dates, the previous output stands, and the batch is recorded as `failed`. A
non-critical failure is a warning: the output is published and the run is flagged for review. The
full decision table is §10.

**On T6 and T10 being warnings rather than failures.** Both are statements about the source data,
not about this stage's correctness. Tax that does not match the rate is the shop's problem, and
refusing to publish the day's revenue over it would punish the wrong party. The same applies to
cost coverage: the catalogue is what it is. A warning that is recorded and visible is more useful
than a batch that never runs.

**On T6's threshold at this volume.** The batch for 2026-10-02 holds 6 live sales and 5 sales whose
tax does not match the rate. Five of eighteen is 28 %, so the 1 % rule fails it — and that is the
intended outcome. A percentage threshold on a shop that sells six times a night is a blunt
instrument, so the count is the figure that matters and the percentage only decides whether anyone
looks. Here, someone should.

---

## 8. Transformation Metadata and Log Specification

Every batch writes to `transformation_runs` (one row per output table, plus a run-level row),
`transformation_rule_counts` (one row per rule per table), and one JSON log file per batch on the
pipeline host. **Extraction metadata is referenced, never duplicated**: `parent_run_id` points at
the extraction run, and Stage 1's `pipeline_runs` row remains the record of what was read and
whether it was sound.

| Field | Purpose | Example |
| --- | --- | --- |
| `run_id` | Identifies this transformation run | `4c8e2f17-6b3a-4f2e-9d51-0a7c3e9b8f21` |
| `batch_id` | Identifies the batch. Stable for one handover, so a retry rewrites rather than appends. | `TRF_20261002_9f1c0b6e` |
| `parent_run_id` | The extraction run this batch transformed. Referenced, not copied. | `9f1c0b6e-2a4d-4f77-9c3e-1d5a8b7f0e42` |
| `pipeline_name` | Which pipeline produced the row | `psync_nightly_analytics` |
| `business_date` | The day being processed | `2026-10-02` |
| `batch_window_start` / `batch_window_end` | The date range rebuilt | `2026-09-29` / `2026-10-02` |
| `table_name` | Which output table the row refers to. NULL on the run-level row. | `fct_daily_product_demand` |
| `transformation_started_at` | When the batch (or this table's build) began | `2026-10-02T01:30:04+08:00` |
| `transformation_ended_at` | When it finished | `2026-10-02T01:30:31+08:00` |
| `transformation_duration_seconds` | How long it took | `27` |
| `transformation_status` | Outcome | `running`, `success`, `failed`, `skipped` |
| `records_read` | Rows received from the handover for this table | `28` |
| `records_output` | Rows written | `7` |
| `records_rejected` | Rows quarantined | `0` |
| `records_modified` | Records changed by any cleaning or business rule. Retained, **not** rejected. | `10` |
| `rules_applied` | Per-rule counts. **Not a jsonb blob**: it is `transformation_rule_counts`, one row per rule per table, because a blob cannot be indexed, summed, or charted. | `C-02: 8; S-11: 2; C-04: 0` |
| `validation_results` | Outcome of every check in §7 | `{"T1":"PASS","T2":"PASS",…,"T17":"PASS"}` |
| `decision` | The verdict from §10 | `APPROVED WITH WARNING` |
| `error_code` | Short code when something failed | `TRF_INPUT_COLUMN_MISSING` |
| `error_message` | Human-readable detail | `sales_transaction_items.name is required by rule C-02 and is not present in staging` |
| `code_version` | Which code and which revision of these rules produced the output | `psync_transform 0.1.0 / rules 1.0` |

**How the metadata is used**

- **Monitoring** — `transformation_duration_seconds` and `records_output` per table show whether
  last night behaved like the nights before it. A duration that triples is the first sign of a
  missing index; a `records_output` that halves is the first sign that a rule stopped matching.
  `cogs_coverage_pct` is monitored as a data-quality trend, not as a pipeline health metric.
- **Troubleshooting** — `error_code` plus `error_message` plus `table_name` name the failure. Because
  the grain is per table, a batch that failed while building `dim_item` is distinguishable from one
  that failed in validation.
- **Auditing** — `batch_id`, `parent_run_id`, `business_date`, `records_read`, `records_output`,
  `records_rejected`, `rules_applied` and `validation_results` together answer "what did this
  pipeline claim to publish for this day, from which extraction, changed by which rules, and on
  what evidence?".
- **Lineage** — `parent_run_id` → Stage 1's `pipeline_runs` row → the staged rows → the source
  window. In the other direction, every fact row carries `business_date` and a dimension key whose
  `valid_from` dates the version used, so a published number can be traced to the version of the
  product or branch that produced it.
- **Recovery** — `batch_id` makes a retry safe: the same handover reuses the same batch ID, the
  facts are replaced for the same dates, and the dimension versions are updated in place. A batch
  that failed mid-way leaves the previous output untouched, because each date's write is one
  transaction.

**The log file.** One JSON file per batch, written by writing a temporary file and renaming it into
place, so a crash never leaves a half-written log that looks complete. Named
`<safe batch_id>.json` — the batch ID contains no colon, unlike Stage 1's `run_key`, but the same
sanitiser is used so the two stages behave identically.

---

## 9. Log Retention, Rejected Data, and Access

| Item | Rule |
| --- | --- |
| **Operational retention** | **90 days.** Per-table rows in `transformation_runs` and the JSON logs. Useful while a problem is fresh, and no longer. |
| **Audit retention** | **24 months.** The run-level row, `transformation_rule_counts`, and `quarantine_rows`. These are the evidence that a published figure was produced correctly and that a given record was excluded for a stated reason. |
| **Why the quarantine is kept as long as the audit record** | A question about last year's revenue ("why is this day lower than the till?") is answered by the quarantine, not by the run row. Deleting it at 90 days would leave the audit trail saying a record was rejected while destroying the record. |
| **Storage location** | The `psync_analytics` database, which the pipeline owns. JSON logs on the pipeline host, one file per batch. Never in the PRINTSYNC database. |
| **Access** | Write: the pipeline's service login only. Read: the analytics and development team. Delete: the automated retention job only — no human has delete rights, so nothing can be removed early by hand. |
| **Sensitive data** | The quarantine stores the offending row as this stage's columns: identifiers, product names, quantities, amounts, timestamps. **No customer data** — Stage 1 does not extract `customers` or `sales_transactions.customer`, so there is none to store. Product names and amounts are commercial data, not personal data, and they are the minimum needed to explain a rejection. |
| **Archiving** | None. Detail is deleted at 90 days rather than compressed, for the same reason Stage 1 gives: an archive with no defined format, consumer, or replay procedure is a promise nobody keeps. If an archive is wanted, §6.1 defines the format first. |
| **Deletion** | Automated, and never before the retention period expires or while a batch is under investigation. The retention job runs nightly, reports what it deleted (`prune_*` return counts), and cannot delete a run-level row, a rule count, or a quarantine row younger than 24 months. |
| **Operational versus audit, kept apart** | Conflating them is how a team either hoards everything or deletes the evidence. Detail expires; the accounting of what happened does not. |

**Separate from Stage 1, deliberately.** Extraction logs record retrieval errors, extraction counts,
and source-to-staging reconciliation. These logs record cleaning actions, conversion failures,
validation failures, and rejected records. They share a database and a retention policy shape, and
nothing else — a reader looking for "why was this row rejected" must land in this stage's tables,
not in Stage 1's.

---

## 10. Transformation Acceptance and Handover Rules

### 10.1 Decision rules

The vocabulary is Stage 1's, on purpose: one pipeline, one set of words for "good", "good with
caveats", "look at this", and "stop".

| Overall condition | Decision | Pipeline action |
| --- | --- | --- |
| All critical checks pass; no warnings | **APPROVED** | Hand over to Load automatically |
| All critical checks pass; one or more warnings | **APPROVED WITH WARNING** | Hand over automatically; flag the run for review within one business day |
| One or more critical checks fail | **REJECTED** | Stop. Write nothing for the affected dates; the previous output stands. Retry up to 3 times with backoff, then alert. |
| The input contract is not met (T1) | **REJECTED** | Stop before reading. This is D1's failure mode and it must be loud. |
| Quarantined records exceed 1 % of `records_read` | **MANUAL REVIEW** | Hold the batch. At this volume, 1 % means a rule has broken, not that the data is dirty. |
| The same `batch_id` already succeeded and the handover is unchanged | **SKIPPED** | Stop without error. The day is already transformed. |
| The extraction's closed-day flag is set for the target date | **APPROVED WITH WARNING** | Hand over; `fct_daily_sales` may legitimately have no row for the day (T14) |

**The rejection-rate threshold is fixed in advance: 1 %.** At the measured volume — about 28 sale
lines a batch — 1 % is a fraction of a line, so in practice **any** quarantine holds the batch for
review. That is deliberate, and it is the honest reading of the threshold at this size: with fewer
than thirty lines a night, a single rejected line is a rule that stopped matching, and a human
should look before it becomes a number nobody questions. The same threshold as Stage 1's, for the
same reason, and it is stated here before any batch has been run so it cannot be chosen to fit a
result.

### 10.2 Who decides

| Decision | Automatic or manual | Responsible role |
| --- | --- | --- |
| APPROVED | Automatic | None — the batch proceeds |
| APPROVED WITH WARNING | Automatic, with a flag | Data team reviews within one business day |
| REJECTED | Automatic stop; manual restart | Data team investigates and re-runs |
| MANUAL REVIEW | Manual | Data team lead approves or rejects before anything proceeds |
| SKIPPED | Automatic | None |

### 10.3 Handover to the Load stage

| Item | Detail |
| --- | --- |
| Data | The four `fct_*` tables and three `dim_*` tables in `psync_analytics`, for every `business_date` in the batch window |
| Metadata | The `transformation_runs` run-level row: `batch_id`, `parent_run_id`, window, status, counts, decision, `code_version` |
| Rule counts | `transformation_rule_counts` for the batch — what each rule changed |
| Validation results | The outcome of every check in §7 |
| Rejects | `quarantine_rows` for the batch, with rule ID and reason — handed over for reporting, not for repair |
| Manifest | `<batch_id>.handover.json`, written beside the log, listing the above and the dates it covers |
| Explicitly **not** claimed | No loading, no indexing, no partitioning, no dashboard query. Stage 2's promise is that the transformed tables are correct, complete, and traceable — not that they are published. |

### 10.4 Worked example

A batch for **2026-10-02**, from the extraction run of that night. The batch window is
2026-09-29 … 2026-10-02, so four business dates are rebuilt.

| Item | Value |
| --- | --- |
| Records read | 18 sales (6 live, 12 voided), 28 sale lines (10 live), 18 payments, 23 orders, 15 catalogue items, 2 settings rows, 2 branch rows |
| Output dates | 2026-09-29, 2026-09-30, 2026-10-01, 2026-10-02 |
| `fct_daily_sales` | 4 rows. 09-29: 2 live, ₱442.40 gross. 09-30: 3 live, ₱7,384.00 gross, ₱310.00 discount. 10-01: 1 live, ₱728.00 gross. 10-02: **0 live, 4 voided** — a row with zero revenue and four voids, not an absent row (A-06). |
| `fct_daily_product_demand` | 7 rows — 2 products on 09-29, 4 on 09-30, 1 on 10-01, none on 10-02 |
| `fct_daily_stock_snapshot` | 15 rows, all for 2026-10-02 |
| `fct_daily_order_status` | **0 rows** — all 23 orders were raised between February and September, so none is in the window (X-04). The funnel is a monthly view, not a nightly one. |
| Quarantined | 0 |
| T5 line-to-header identity | PASS — every live line's `quantity × unit_price` sums to its header `subtotal` |
| T6 VAT conformance | FAIL (non-critical) — 5 of the 18 sales carry tax that does not match 12 %, including the ₱3,240.00 sale that under-collects ₱388.80 |
| T10 cost coverage | PASS — every live line in this window is a catalogue item, so coverage is 100 % here. It is 6.9 % across the full export (F-09), which is why the column exists. |
| T14 non-empty output | PASS — 10-02 has a sales row (all voided) and 15 stock rows |
| **Overall** | **APPROVED WITH WARNING** — handed to Load, flagged for review because of the VAT exceptions |

---

## 11. Common Transformation Problems and Mitigation

Each problem below is specific to this data and this batch design. Generic failure lists teach
nothing; these are the failures this pipeline will actually have.

### P1 — The look-back makes a batch cover four days, and a careless rule puts them all on one

- **What happens:** the batch for `D` contains sales created on `D-3 … D`. If a fact is grouped on
  the staging control column `business_date` — which is `D` on every row — four days of revenue land
  on `D`, and the three earlier days are then *emptied* by the delete step.
- **Cause:** Stage 1's look-back (§1.3 there) re-reads three days so that late voids are caught.
  The control column records the day the extraction ran, not the day the sale happened.
- **Impact:** revenue appears once, on the wrong day, and three days go to zero. The totals still
  reconcile, which is what makes it dangerous: the numbers look plausible.
- **Mitigation:** `business_date` is always derived from `created_at` in `Asia/Manila` (S-01), never
  read from the control column. T13 proves the set of output dates equals the set of dates present
  in the input, so a batch that collapses them fails instead of publishing.

### P2 — 93.4 % of sale lines have no catalogue link

- **What happens:** `inventory_item_id` is null on almost every line, because the shop sells print
  services that were never added to the inventory catalogue (F-01).
- **Cause:** the point-of-sale records a free-text product name and only links to the catalogue when
  the product happens to exist there. `ON DELETE SET NULL` also nulls the link when a product is
  deleted.
- **Impact:** a product dimension keyed on the catalogue would cover 6.6 % of lines. Demand,
  reorder recommendations, and product-level revenue would all be computed on a fourteenth of the
  business, and the other 93 % would either vanish or become one "unknown" bucket.
- **Mitigation:** the product is identified by its normalised line name (C-02, S-12), with the
  catalogue link kept as an attribute when it exists. A rename starts a new product history — a real
  limitation, recorded as D4. The permanent fix is for PRINTSYNC to require a catalogue selection at
  the point of sale, which we cannot make (§1.6 of Stage 1), so the name is the identity and the
  document says so rather than pretending otherwise.

### P3 — Profit is computable for 6.9 % of revenue, and a naive implementation reports it as if it were all

- **What happens:** `cost_price` exists only for catalogue items. A `gross_profit = net_revenue - cogs`
  that sums only known costs silently treats the other 93 % of goods as free.
- **Cause:** F-09, and the same catalogue gap as P2.
- **Impact:** a profit figure overstated by roughly the entire cost of the uncosted goods — the most
  dangerous kind of wrong number, because it is plausible and it is the number a manager acts on.
- **Mitigation:** `gross_profit` and `margin_pct` are NULL unless coverage is 100 % (B-10). The
  costed slice is published as `gross_profit_costed` and `margin_pct_costed`, always with
  `cogs_coverage_pct` beside it. T10 warns on low coverage. When the catalogue covers what the shop
  sells, the whole-day figures light up on their own with no code change.

### P4 — A header discount that no line knows about

- **What happens:** 75 sales (8.6 %) carry a discount on the header that is not present on any line
  (F-03). The day's discount total and the product-level discount totals then disagree.
- **Cause:** the point of sale can apply a discount at the sale level without distributing it across
  the items.
- **Impact:** if product-level revenue is built from lines and the day's revenue from the header,
  the two differ by the unallocated amount — and any attempt to reconcile them fails.
- **Mitigation:** the header stays authoritative for the day (`discount_total`), the lines stay
  authoritative for the product (`discount_total` in the demand fact), and the difference is
  published as `unallocated_discount`. T4 and T12 use exactly that term, so the reconciliation is
  exact rather than approximate. Nothing is redistributed: an invented allocation would make every
  product's margin slightly wrong to make a total look tidy.

### P5 — A bulk `updated_at` touch drags the whole orders table into the window

- **What happens:** all 23 orders share one `updated_at` (F-10), so every nightly extraction pulls
  the entire table, not the day's orders.
- **Cause:** a migration or a maintenance script wrote `updated_at` on every row. `orders` has an
  `updated_at` trigger, and a bulk update fires it.
- **Impact:** an order fact built from the window would count February's orders as today's demand,
  and the order-value series would jump on every migration.
- **Mitigation:** the order fact cohorts on `created_at` (X-04), and the orders that are in the batch
  only because their `updated_at` moved are counted by C-06. The window keeps doing its job for
  status changes — which is why it is `updated_at` and not `created_at` in Stage 1 — while the fact
  reports the day's orders. On 2026-10-02 that leaves zero rows, which is the correct answer and
  shows why the funnel is read monthly.

### P6 — Tax that does not match the configured rate

- **What happens:** five sales (0.6 %) carry no VAT where 12 % is expected, including one completed
  ₱3,240.00 sale that under-collects ₱388.80 (F-06).
- **Cause:** unknown — a manual override, a price entered tax-inclusive, or a defect in the checkout
  when the discount is applied. It is the shop's data problem, not the pipeline's.
- **Impact:** `tax_total` and `net_revenue` inherit the error, so a margin computed on `net_revenue`
  is slightly overstated for that day.
- **Mitigation:** the recorded tax is **never recomputed** — recomputing would invent a number the
  customer never paid and break the reconciliation to payments. T6 counts the exceptions and warns.
  The shop is told; the pipeline does not silently fix their till.

### P7 — A dimension that grows by one row per product per night

- **What happens:** if `stock` is treated as a dimension attribute, every night's stock change opens
  a new `dim_item` version. Fifteen products become 5,475 rows a year, and the dimension stops being
  a dimension.
- **Cause:** conflating an attribute (a price, a category) with a measure (stock on hand).
- **Impact:** joins slow down, history becomes meaningless, and the SCD logic looks like it is
  working while it destroys the table.
- **Mitigation:** `stock_on_hand` lives in `fct_daily_stock_snapshot` (B-12), where it is a
  semi-additive measure — a snapshot per day, never summed across days. `dim_item` versions only on
  a genuine attribute change (M-03).

### P8 — A rerun doubles the day

- **What happens:** a batch is retried, or someone re-runs a date by hand, and the day's revenue
  doubles.
- **Cause:** an insert-only publish, which is the natural way to write a transformation and the
  wrong one.
- **Impact:** inflated revenue that still reconciles internally, because both copies are consistent.
- **Mitigation:** the publish deletes the entire batch window before inserting, in one transaction
  per date (§1.2); dimensions upsert on `(natural key, valid_from)`; the batch record is unique on
  `(batch_id, table)`; the quarantine is unique on `(batch_id, source_table, source_id, rule_id)`.
  Running the same batch twice is harmless by design, not by convention.

### P9 — The second branch exists but has never traded

- **What happens:** `business_settings` has two rows (`IC Printing Services` and `… - Nasugbu`), and
  every transaction in the export belongs to the first branch (F-12).
- **Cause:** the branch was created before it opened.
- **Impact:** a fact densified over "every branch" would emit rows of zeros for a branch that has
  never had a sale, and a dashboard would show a flat line for a shop that does not exist yet.
- **Mitigation:** `fct_daily_sales`, `fct_daily_product_demand` and `fct_daily_order_status` only
  produce rows for `(date, branch)` pairs that have activity (A-04, A-05, A-06); `dim_branch` still
  holds the branch, so the first sale there will produce facts immediately.

### P10 — The input contract was missing the column this stage depends on

- **What happens:** `sales_transaction_items.name` was not extracted (F-02, D1). Without it, 93.4 %
  of lines cannot be attributed to a product.
- **Cause:** Stage 1 selected only the columns Lab 2's output tables appeared to need. Lab 2 assumed
  a catalogue-linked product dimension; the data does not support that assumption.
- **Impact:** the product demand fact cannot be built at all. There is no acceptable fallback: an
  "unknown product" bucket holding 93 % of revenue is not a demand report.
- **Mitigation:** **done, 26 October 2026.** Stage 1 revision 1.4 added the column: §2.2 and §6.3 of
  the extraction contract, migration `002_stg_item_name.sql` for the staging table (a new file, not
  an edit to the applied `001`), the `SOURCE_SCHEMA` registry, and the items extractor — 52 columns
  instead of 51. T1 stays in place, so a staging table that predates the migration fails the batch
  loudly instead of silently publishing a demand table without products.
- **Lesson worth keeping:** the gap was found by profiling Stage 2's *input* against Stage 2's
  *rules*, not by reading either document on its own. Two documents that are each internally
  consistent can still disagree at the boundary between them.

### P11 — Money summed in floating point

- **What happens:** ₱1,267,387.08 of revenue comes out as 1267387.0800000001, and two aggregates
  that should be equal differ in the twelfth decimal.
- **Cause:** binary floating point cannot represent 0.01 exactly, and Python's `float` is the default
  numeric type in most quick scripts.
- **Impact:** reconciliation checks that compare to the cent start failing intermittently, which is
  worse than failing always — it teaches the team to loosen the check.
- **Mitigation:** every money value is read as `Decimal`/`numeric`, never as `float` (S-02), and
  rounding happens once, at the published measure. The SQL side is `numeric` end to end, so the
  arithmetic never leaves exact decimal representation.

---

## 12. Revision history

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | 26 October 2026 | Initial transformation specification. Profiling basis: the PRINTSYNC export of 2 October 2026. Records the input gap in the extraction contract (D1, P10) and the cost-coverage limit (B-10). |
| 1.1 | 26 October 2026 | Closed the input gap by decision rather than by workaround. Stage 1 revision 1.4 adds `sales_transaction_items.name` (§2.2, §6.3), migration `002_stg_item_name.sql` adds the column to staging, and the schema registry and items extractor select it — 52 columns instead of 51. D1, F-02 and P10 now record the resolution and keep T1 as the guard for a staging table that predates the migration. This stage's own schema migration is renumbered to `003_transformation_schema.sql` to leave `002` to the extraction fix. No rule, check, grain or acceptance criterion changed. |
| 1.2 | 26 October 2026 | Corrected three cross-references found while writing the schema migration. F-06 and S-20 pointed at check T5 when VAT conformance is T6, and T6's rate condition read "outside 0–100" while S-20 fails a rate of 0 — both now say **zero or above 100**, which is also what `dim_branch.vat_rate` enforces. No rule, threshold or acceptance criterion changed. |

---

## 13. References

- Bulan, L. J. D., Rendal, R. C., & Vidal, M. E. Z. (2026, September 9). *Data Pipeline Technology Research for PRINTSYNC*. BAT-405 Laboratory Activity 1.
- Bulan, L. J. D., Rendal, R. C., & Vidal, M. E. Z. (2026, September 16). *Technical Metadata Documentation for PRINTSYNC*. BAT-405 Laboratory Activity 2.
- Bulan, L. J. D., Rendal, R. C., & Vidal, M. E. Z. (2026, October 5). *Data Extraction Documentation for PRINTSYNC* (rev. 1.3). BAT-405 Laboratory Activity 3. `docs/Extraction/Data-Extraction-Documentation-for-PRINTSYNC.md`.
- Kimball, R., & Ross, M. (2013). *The Data Warehouse Toolkit: The Definitive Guide to Dimensional Modeling* (3rd ed.). Wiley. — grain declaration, surrogate keys, SCD Type 2, semi-additive facts.
- PRINTSYNC source schema: `supabase/migrations/` and `0_never-push-this-dump-folder/postgre-supabase-data/0_supabase-schema.sql` (snapshot dated 3 October 2026).
- PRINTSYNC data export used for profiling: `0_never-push-this-dump-folder/backups/2026-10-02T11-34-59/` (2 October 2026).
- Psycopg 3 — https://www.psycopg.org/psycopg3/docs/
- Prefect 3 — https://docs.prefect.io/v3/get-started
- PostgreSQL 15 — https://www.postgresql.org/docs/
