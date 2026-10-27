# Data Extraction Documentation

**PRINTSYNC Nightly Analytics Batch Pipeline**
Pipeline ID · `psync_nightly_analytics` · Stage 1 of 3 (Extract → Transform → Load)
BAT-405 Analytics Application — Capstone Laboratory Activity 3
Lyell Jasmine D. Bulan · Roi C. Rendal · Ma. Erica Z. Vidal
5 October 2026

---

## Objective

Extract one business day of records from the PRINTSYNC operational database, check that the
extraction is complete and trustworthy, and package it for the Transformation stage.

The pipeline is a **standalone Python application built and run outside PRINTSYNC**. It reads
from PRINTSYNC over a read-only connection and writes everything it produces into its own
database. PRINTSYNC itself is not modified in any way — see Section 1.6.

This stage does **not** clean, standardise, or aggregate the data. It copies the day's records
out of the live system and proves that the copy is complete. Profit, daily totals, per-product
demand, and order-status counts are all produced later, in the Transformation stage.

---

## Scope decisions (read this first)

The professor asked us not to make the ETL more complex than it needs to be, and PRINTSYNC is
still under development — its database changes while we write this. Two decisions follow from
that, and they shape the whole document.

**1. We extract 7 tables, not 11.** Lab 2 listed eleven source tables. Four of them are not
consumed by any output table that Lab 2 defined, so carrying them through the pipeline adds
work and risk with no payoff:

| Table Lab 2 listed | Why it is dropped from Stage 1 |
| --- | --- |
| `order_items` | No output table uses it. `fct_daily_order_status` counts orders and sums `orders.amount`; it never reads line items. The orders module is also the most actively changing part of the app right now. |
| `order_payments` | Same reason. Order payments are not part of any summary Lab 2 defined. |
| `customers` | Not needed. The customer name is already stored on the sale itself, and no output table requires a customer dimension. |
| `inventory_movements` | Not needed. Stock on hand comes from `inventory_items.stock`. Movement history would only matter for a stock-audit report we are not building. |
| `operating_expenses` | The table and its API exist, but **there is no Expenses screen in PRINTSYNC** — the sidebar offers Dashboard, Orders, Inventory, Point of Sale, Analytics, Customers, Users, Audit Log, and Settings, and no expenses page has been built. Every row in the table today was placed there by the demo data seeder, not by staff. Extracting a list nobody can yet fill would produce a permanent zero. |

Every table we *do* extract maps to a named output table from Lab 2. If a table has no
downstream consumer, it is not in scope.

**One consequence to be aware of.** With `operating_expenses` out, `fct_daily_sales.expense_total`
cannot be produced, so the daily profit this pipeline reports is **gross profit** — revenue less
the cost of the goods sold — not profit after rent, electricity, and supplies. That is a real
limitation, and it is the honest one: we would rather report a number we can stand behind than
one that quietly reads zero. When an Expenses screen ships, adding this table back is a small,
contained change.

**2. We treat multi-branch data as raw, unresolved, and not yet aggregated.** Branch scoping
landed in the database on 2 October 2026 and is still settling. `branch_id` is now `NOT NULL`
on every transaction table, so we must carry it or the rows cannot be written. But we do
**not** try to produce per-branch business days, per-branch time zones, or per-branch
summaries yet. We carry `branch_id` as a plain attribute and extract `branches` only as a
small lookup so the value is meaningful. That keeps the complication out of Stage 1 while
leaving the data available if the branch design firms up later.

---

## 1. Data Source and Extraction Specification

### 1.1 Source system

| Item | Detail |
| --- | --- |
| Name | PRINTSYNC |
| Purpose | The printing shop's operational system: point-of-sale checkout, custom and production orders, and inventory control. |
| Role in this pipeline | System of record. It is the only source; nothing is merged in from outside. |
| Owner | The PRINTSYNC development team. |
| How the pipeline touches it | **It does not.** PRINTSYNC is left exactly as it is. The pipeline only reads from it. No code is added to the PRINTSYNC application, no table or column is created inside its database, and no existing object is modified. |

### 1.2 Source database

| Item | Detail |
| --- | --- |
| Database management system | PostgreSQL (Supabase-hosted) |
| Version | PostgreSQL 15 or newer |
| Schema | `public` — the application's operational schema |
| File formats | None. This is a direct database read, not a file drop. No CSV, JSON, or Excel is involved. |
| Connection | Encrypted (SSL) connection over TCP, using a dedicated read-only database login |
| Objects created in it by the pipeline | **None.** The pipeline holds no write permission and issues no DDL against this database. |
| Existing indexes used | `sales_transactions_status_created_idx` on `(status, created_at DESC)`; `sales_transaction_items_transaction_idx` on `(transaction_id)`; `inventory_items_stock_reorder_idx` on `(stock, reorder_level)` |

**Revision note (v1.1).** Earlier revisions named `sales_transaction_items_transaction_created_idx` in the row above. That index was dropped on 21 September 2026 as a duplicate of `sales_transaction_items_transaction_idx` (`supabase/migrations/20260921000600_drop_duplicate_transaction_items_index.sql`); both were single-column indexes on `transaction_id`, so query behaviour is unchanged and only the name was wrong.

### 1.3 Extraction method

**Type: incremental, by business day.** Each run extracts one business day. The run never
re-reads the whole history.

**Tool:** the `psync_extract` Python package (Python 3.12 or newer — the development host runs
3.13), using **Psycopg 3** with a server-side cursor and **Prefect 3** for orchestration and retries.
Prefect is an **optional extra** (`pip install -e ".[orchestration]"`), not a dependency of the
package: the project's constraints rule out an orchestration framework in the pipeline itself, and
the plain entry point below runs with nothing but Psycopg installed.
Two entry points call the same code: `python -m psync_extract --date YYYY-MM-DD` for a single day,
and the `extraction_flow` Prefect flow for a scheduled or repeatable run. Python and Psycopg were
chosen in Lab 1 and confirmed in Lab 2; nothing new is introduced here.

**Schedule:** every night at **01:00 Philippine time (Asia/Manila)**. The job can also be run
by hand for a specific date when a re-run is needed. 01:00 was chosen because the shop is
closed and the point-of-sale is not competing for the database.

**The extraction window.** The run is given a `business_date` — the calendar day being
processed. Two timestamps are derived from it in Asia/Manila:

```
window_start = business_date 00:00:00 +08:00
window_end   = (business_date + 1 day) 00:00:00 +08:00
```

A **look-back of 3 days** is then applied on top of that window. The look-back exists because
some records change after their day has closed — a sale gets voided, for instance. Rather than
try to detect those edits precisely, we simply re-read a trailing 3 days on
every run and let the Transformation stage overwrite that day's output. Three days is a
configuration value, not a hard rule.

**Window field per table.** This is the part that has to be right, and it differs per table
because the tables are not built the same way:

| Table | Field that drives the window | Logic |
| --- | --- | --- |
| `sales_transactions` | `created_at`, `voided_at` | `created_at` inside the window **OR** `voided_at` inside the window. The second condition catches a sale that was made on an earlier day but voided today. |
| `sales_transaction_items` | *(no timestamp column)* | Extracted by joining `transaction_id` to the sales already inside the window. This table has no `created_at` and no `updated_at`, so it cannot be windowed on its own. |
| `payments` | `created_at`, `voided_at` | Same pattern as sales: matched to a transaction in the window, or its own `created_at` / `voided_at` falls in the window. |
| `orders` | `updated_at` | `updated_at` inside the window. This table has an `updated_at` trigger, so a late status change moves the row into the window. |
| `inventory_items` | *(full extract)* | Full snapshot every run. The catalogue is small, and a snapshot is simpler and safer than trying to work out what changed. |
| `business_settings` | *(full extract)* | Full. A few rows only. |
| `branches` | *(full extract)* | Full. A few rows only. |

**A limitation worth stating plainly:** `sales_transactions` has **no `updated_at` column**.
There is no way to ask "which sales changed since yesterday?" The only late change we can
detect on a sale is a void, which `voided_at` gives us. That is why the look-back is a blunt
re-read rather than a precise change-detection query, and it is documented again as a risk in
Section 8.

### 1.4 Extraction scope

| Dimension | Scope |
| --- | --- |
| Tables | 7 tables, listed in Section 2 |
| Date range | One business day per run, plus a 3-day look-back re-read |
| Columns | Only the columns listed in Section 2. We do not copy whole tables. |
| Row filter | None beyond the window. Cancelled and voided records **are** extracted — they are filtered out later, in Transformation, so the extraction stays a faithful copy. |
| Volume (typical night) | A few hundred sales rows, a few thousand line-item rows, tens of orders, a full catalogue snapshot of a few hundred products |
| Out of scope | `designs`, `suppliers`, `purchase_orders`, `profiles`, `audit_logs`, `permissions` — none feeds an analytics output, and `purchase_orders` is still unbuilt in the application |

### 1.5 Source limitations and assumptions

| # | Limitation or assumption | Consequence |
| --- | --- | --- |
| L1 | **The schema is still moving.** Migrations are landing weekly; multi-branch scoping arrived on 2 October 2026. | A column we depend on could be renamed or removed. Handled by the schema-drift check in Section 3, which fails the run rather than silently producing wrong numbers. |
| L2 | **`sales_transactions` has no `updated_at`.** | Late edits to a sale cannot be detected precisely. Mitigated by the 3-day look-back, not solved. |
| L3 | **`sales_transaction_items` and `order_items` have no timestamp at all.** | Line items can only be windowed through their parent. Referential integrity is validated explicitly (check V5). |
| L4 | **Line-level discounts are new.** `line_discount` was added to sales and order items on 30 September 2026. | Older rows read as `0`. Net revenue will be slightly overstated for sales made before that date. Accepted; noted here rather than fixed in extraction. |
| L5 | **`business_settings` is now per-branch**, one row per branch (`branch_id` is `UNIQUE`). Lab 2 assumed a single shop settings row. | The pipeline reads the row for one configured reference branch to obtain `vat_rate`, `currency_symbol`, and `time_zone`. Documented as a temporary assumption until the branch model settles. |
| L6 | **Historical data predates the pipeline.** Sales recorded before the first run were never extracted. | Backfill is a deliberate one-off manual run for a chosen date range, not part of the nightly job. |
| L7 | **Database access is restricted to read-only.** The pipeline holds a read-only login. | Extraction can never alter operational data. It also cannot repair anything at source — bad source data must be fixed by the application team, not by us. |
| L8 | **Supabase enforces a connection limit.** | The job uses one connection with a server-side cursor and runs off-peak. Retries use backoff, not immediate reconnection. |
| L9 | **We cannot change the source to make our job easier.** PRINTSYNC is to remain untouched, so we cannot add the missing `updated_at` column, add indexes, or add a change-tracking trigger. | The pipeline must work with the schema exactly as it finds it. Every workaround in this document is on our side of the boundary, never theirs. |
| L10 | **The pipeline runs outside the shop's infrastructure.** It reaches PRINTSYNC over the public network, not from inside it. | Network failures are a real failure mode (see P7). The pipeline must tolerate a source that is simply unreachable and catch up afterwards. |
| L11 | **`operating_expenses` is out of scope.** The table exists but PRINTSYNC has no Expenses screen, so no staff member can enter an expense yet. | `fct_daily_sales.expense_total` cannot be produced. Daily profit is **gross profit** — revenue less cost of goods sold — not profit after rent, power, and supplies. Revisit when an Expenses screen ships. |

### 1.6 Deployment boundary — where the pipeline lives

The pipeline is a **standalone Python project, developed and run separately from PRINTSYNC**.
It is not a module inside the PRINTSYNC application, it is not in the PRINTSYNC repository, and
it does not import PRINTSYNC code.

| Boundary | PRINTSYNC (the source) | The pipeline (ours) |
| --- | --- | --- |
| Codebase | Untouched. No files added or changed. | Separate repository: Python 3.12+, Psycopg 3 (Prefect 3 optional, for scheduling only) |
| Database | Read-only. No tables, columns, indexes, or triggers added. | Its own PostgreSQL database, `psync_analytics` |
| Credentials | One read-only login, provisioned once as an access grant | Holds and manages its own connection settings |
| Scheduling | None. PRINTSYNC does not start or know about the job. | Prefect 3, when its optional extra is installed; the plain CLI needs no scheduler |
| Failure impact | None. If the pipeline breaks, the shop keeps trading. | Contained entirely within the pipeline |

**One consequence worth stating plainly:** because the pipeline cannot write into the PRINTSYNC
database, its output — the staging tables, the logs, and the archive — has to live somewhere
else. It lives in `psync_analytics`, a PostgreSQL database owned and managed by the pipeline.
This is a deliberate change from Lab 2, which described the reporting tables as "a separate
reporting area inside the same database". A separate database is what "PRINTSYNC stays
untouched" actually requires, since creating tables inside their database would be a change to
their system.

**The single exception:** a read-only login must exist on the PRINTSYNC database for the
pipeline to connect at all. Provisioning it is an access grant, not a schema change — no table,
column, or row is created or altered — but it is the one thing that has to be done on their
side, once.

---

## 2. Source Tables and Column Specification

Seven tables. For each: why it is in scope, and the columns we actually take.

### 2.1 `sales_transactions`

- **Purpose:** one row per completed sale at the counter. The spine of the whole pipeline.
- **Primary key:** `id` (uuid)
- **Relationships:** `id` → `sales_transaction_items.transaction_id` and `payments.transaction_id`; `branch_id` → `branches.id`; `customer_id` → `customers.id`
- **Reason for inclusion:** source of `fct_daily_sales` — revenue, discounts, tax, and the payment-method split.

| Column | Source type | Purpose |
| --- | --- | --- |
| `id` | uuid | Primary key. Identifies the sale. |
| `status` | text | `completed` or `voided`. |
| `subtotal` | numeric | Sales value before discount and tax. |
| `discount` | numeric | Discount applied to the sale. |
| `tax` | numeric | VAT collected. |
| `total` | numeric | Final amount charged. |
| `payment_method` | text | `Cash`, `Card`, or `Custom Order`. |
| `created_at` | timestamptz | When the sale happened. Drives the window. |
| `voided_at` | timestamptz | When it was voided, if it was. Null otherwise. |
| `customer_id` | uuid | Customer link. Nullable — walk-in sales have none. |
| `branch_id` | uuid | Branch. Carried as an attribute; not aggregated in Stage 1. |

### 2.2 `sales_transaction_items`

- **Purpose:** the individual items on each sale.
- **Primary key:** `id` (uuid)
- **Relationships:** `transaction_id` → `sales_transactions.id`; `inventory_item_id` → `inventory_items.id`
- **Reason for inclusion:** source of `fct_daily_product_demand` — units sold and revenue per product.

| Column | Source type | Purpose |
| --- | --- | --- |
| `id` | uuid | Primary key. |
| `transaction_id` | uuid | Links the item to its sale. Required for windowing. |
| `inventory_item_id` | uuid | Links to the catalogue. Nullable if the item was deleted from inventory. |
| `name` | text | The product name as it was sold. Added in revision 1.4 — see below. |
| `quantity` | integer | Units sold. Constrained at source to be greater than zero. |
| `unit_price` | numeric | Price per unit at the time of sale. |
| `line_discount` | numeric | Discount on this line. Added 30 September 2026 (see L4). |

**Why `name` is extracted (revision 1.4).** Stage 2 identifies a product by the name printed on
the sale line, because `inventory_item_id` is null on **93.4 % of sale lines** (1,241 of 1,329 in
the 2 October 2026 export). The shop sells print services — tarpaulin, lamination, business cards —
that were never added to the 15-row inventory catalogue, so the catalogue link cannot be the
product's identity. Without this column, 93 % of the shop's revenue has no product attached to it
and `fct_daily_product_demand` cannot be built. The column is copied unchanged, like every other
column: no cleaning happens in this stage (see §7.3).

### 2.3 `payments`

- **Purpose:** how each sale was paid.
- **Primary key:** `id` (uuid)
- **Relationships:** `transaction_id` → `sales_transactions.id`
- **Reason for inclusion:** gives the cash / card split in `fct_daily_sales`. `sales_transactions.payment_method` records one method per sale, but a sale can be settled by more than one payment.

| Column | Source type | Purpose |
| --- | --- | --- |
| `id` | uuid | Primary key. |
| `transaction_id` | uuid | Links the payment to its sale. |
| `amount` | numeric | Amount paid. Constrained at source to be greater than zero. |
| `method` | text | `Cash`, `Card`, or `Custom Order`. |
| `status` | text | `captured` or `voided`. |
| `created_at` | timestamptz | When the payment was received. |
| `voided_at` | timestamptz | When it was voided, if it was. |

### 2.4 `orders`

- **Purpose:** custom and production jobs.
- **Primary key:** `id` (uuid)
- **Relationships:** `branch_id` → `branches.id`; `customer_id` → `customers.id`
- **Reason for inclusion:** source of `fct_daily_order_status` — how many orders sit in each status and what they are worth.

| Column | Source type | Purpose |
| --- | --- | --- |
| `id` | uuid | Primary key. |
| `status` | text | `Pending`, `Designing`, `In Production`, `Ready for Pickup`, `Completed`, `Delivered`. Constrained at source. |
| `amount` | numeric | Value of the order. |
| `is_custom` | boolean | True when the order came in as a custom job rather than off the shelf. Added in revision 1.5 — see below. |
| `customer_id` | uuid | Customer link. Nullable. |
| `created_at` | timestamptz | When the order was raised. |
| `updated_at` | timestamptz | Last change. Drives the window — maintained by trigger. |
| `branch_id` | uuid | Branch. Carried as an attribute. |

**Why `is_custom` is extracted (revision 1.5).** `fct_daily_order_status.custom_order_count` needs it,
and the column exists at source — but §2.4 did not list it, so Stage 1 was reading the table without
it. Found while building the Transformation stage's order-status fact, in the same way as the missing
`sales_transaction_items.name` (revision 1.4): by checking the Transformation rules' inputs against
what this document extracts.

### 2.5 `inventory_items`

- **Purpose:** the product catalogue, with prices, costs, and stock levels.
- **Primary key:** `id` (uuid)
- **Relationships:** `id` → `sales_transaction_items.inventory_item_id`
- **Reason for inclusion:** two jobs. `cost_price` is needed to work out profit, and the catalogue feeds `dim_item` — the dated snapshot that keeps old reports accurate when a product is renamed or repriced.
- **Extracted as a full snapshot**, not incrementally.

| Column | Source type | Purpose |
| --- | --- | --- |
| `id` | uuid | Primary key. |
| `sku` | text | Product code. Unique. |
| `name` | text | Product name. |
| `category` | text | Product category. |
| `price` | numeric | Current selling price. |
| `cost_price` | numeric | Buy price. Needed for profit. |
| `stock` | integer | Units on hand. |
| `reorder_level` | integer | Level that triggers a reorder. |
| `uom` | text | Unit of measure. Added 30 September 2026. |
| `updated_at` | timestamptz | Last change to the catalogue row. |
| `branch_id` | uuid | Branch. |

### 2.6 `business_settings`

- **Purpose:** shop configuration.
- **Primary key:** `id` (integer)
- **Relationships:** `branch_id` → `branches.id` (one row per branch)
- **Reason for inclusion:** supplies the time zone that defines the business day, plus `vat_rate` and `currency_symbol` for reporting. A run cannot start without it.
- **Extracted in full** — a handful of rows.

| Column | Source type | Purpose |
| --- | --- | --- |
| `id` | integer | Primary key. |
| `branch_id` | uuid | Which branch these settings belong to. |
| `vat_rate` | numeric | VAT rate. |
| `currency_symbol` | text | Currency symbol, e.g. `₱`. |
| `time_zone` | text | Time zone, e.g. `Asia/Manila`. Defines the business-day boundary. |

### 2.7 `branches`

- **Purpose:** the shop's branches.
- **Primary key:** `id` (uuid)
- **Relationships:** referenced by `branch_id` on every table above
- **Reason for inclusion:** reference data only. `branch_id` is `NOT NULL` on every transaction table, so an extracted row carries a branch value whether we want it or not. Extracting four columns makes that value readable instead of an unexplained code.
- **Extracted in full** — a handful of rows.

| Column | Source type | Purpose |
| --- | --- | --- |
| `id` | uuid | Primary key. |
| `code` | text | Short branch code. Unique. |
| `name` | text | Branch name. |
| `is_active` | boolean | Whether the branch is still operating. |

---

## 3. Extraction Validation and Data Quality Checks

Eight checks. Scope is deliberately limited to **extraction-level** questions: did we reach the
source, did we get the right rows, and is the copy structurally sound? Whether a sale has a
sensible value is a Transformation question and is not tested here.

| # | Check | Target | Purpose | Criteria | Severity |
| --- | --- | --- | --- | --- | --- |
| V1 | Source connection | The database | Confirm the source is reachable and the credentials work before any data is read | Connection opens within the configured timeout and `SELECT 1` returns | Critical |
| V2 | Required objects exist | All 7 tables and every column in Section 2 | Catch schema drift early, before it silently produces a wrong result | Every table present, and every required column present with an expected type | Critical |
| V3 | Window resolved | `business_date`, `window_start`, `window_end` | Confirm the run knows which day it is processing and has not already processed it | `business_date` is a valid past date; no completed run exists for the same `run_key` | Critical |
| V4 | Settings available | `business_settings` | The run cannot compute a business-day boundary without a time zone | At least one row returned for the configured reference branch, with a non-null `time_zone` | Critical |
| V5 | Identifiers present | `id` on all 7 tables; `transaction_id` on `sales_transaction_items` and `payments` | A row without a key or a parent link cannot be joined downstream | Zero null primary keys; zero null `transaction_id` | Critical |
| V6 | Primary key uniqueness | `id` on all 7 tables | A duplicated row would double-count revenue | Count of distinct `id` equals count of rows | Critical |
| V7 | Count parity | Each table, read versus written | Prove nothing was lost between reading the source and writing the staging table | `rows_read` equals `rows_extracted` plus `rows_rejected` for every table | Critical |
| V8 | Non-empty result | `sales_transactions` | A zero-row sale day usually means a broken window, not a genuinely empty day | At least one sale row, **unless** the date is flagged as a closed day | Warning |

**How severity is used.** A critical failure stops the run before handover. A warning does not.
The full decision table is in Section 7.

**The closed-day flag.** Check V8 tolerates a zero-row day only when the operator has flagged
that date as a closed day. The flag is supplied as a run parameter for that date; it is never
inferred from the data. A zero-row day without the flag is a warning, so a broken window is
never mistaken for a quiet day.

**On rejects at this stage.** Rejected rows here are only structural failures — a null primary
key, a line item whose parent sale is missing. In a healthy run `rows_rejected` is `0`.
Business-rule rejects (a negative amount, an unknown status) belong to the Check stage of the
pipeline and are recorded separately. Keeping the two apart means a reader can tell "the
extraction broke" from "the shop data is bad".

---

## 4. Extraction Metadata and Log Specification

Every run writes to the `pipeline_runs` table in the pipeline's own `psync_analytics`
database, and one JSON log file on the pipeline host. The grain is **one row per source table
per run, plus one run-level summary row** that carries the run's overall status and validation
summary. The fields below are the contract.

| Field | Purpose | Example |
| --- | --- | --- |
| `run_id` | Identifies this run. Generated when the run starts. | `9f1c0b6e-2a4d-4f77-9c3e-1d5a8b7f0e42` |
| `run_key` | Makes re-running safe. One successful run per business date. | `psync_nightly_analytics:2026-10-04` |
| `pipeline_name` | Which pipeline produced the row. | `psync_nightly_analytics` |
| `business_date` | The day being processed. | `2026-10-04` |
| `table_name` | Which source table the log line refers to. | `sales_transactions` |
| `extraction_started_at` | When reading began, with time zone. | `2026-10-05T01:00:03+08:00` |
| `extraction_ended_at` | When reading finished. | `2026-10-05T01:02:41+08:00` |
| `extraction_duration_seconds` | How long it took. | `158` |
| `extraction_window_start` | Start of the window, with time zone. | `2026-10-04T00:00:00+08:00` |
| `extraction_window_end` | End of the window, exclusive. | `2026-10-05T00:00:00+08:00` |
| `lookback_days` | How far back the run also re-read. | `3` |
| `extraction_status` | Outcome of this table's extraction. | `running`, `success`, `failed`, `skipped` |
| `rows_read` | Rows returned by the source query. | `412` |
| `rows_extracted` | Rows written to staging. | `412` |
| `rows_rejected` | Rows dropped by a structural check. Normally `0`. | `0` |
| `validation_results` | Outcome of each check in Section 3. | `{"V1":"PASS","V2":"PASS",...,"V8":"PASS"}` |
| `error_code` | Short code when something failed. Null otherwise. | `SRC_CONN_TIMEOUT` |
| `error_message` | Human-readable detail. | `could not connect to server: Connection timed out` |
| `reject_reason` | Why a row was rejected, if any were. | `null_transaction_id` |

**How these are used**

- **Monitoring** — `extraction_status` and `extraction_duration_seconds` per table show whether
  last night's run behaved normally. A duration that suddenly triples is the first sign of a
  missing index or an oversized window.
- **Troubleshooting** — `error_code` plus `error_message` plus `table_name` point straight at
  the failure. Because the log records which table was being read, a partial failure is
  distinguishable from a total one.
- **Auditing** — `run_key`, `business_date`, `rows_read`, and `validation_results` together
  answer "what did this pipeline claim to extract on this date, and on what evidence?".
- **Recovery** — `run_key` makes a re-run safe and repeatable: re-running the same business date
  overwrites that day's output rather than adding to it. `rows_read` against `rows_extracted`
  tells us whether a completed run actually moved all the data it found.

---

## 5. Log Retention and Access

| Item | Rule |
| --- | --- |
| **Operational log retention** | **90 days**, kept hot in the `pipeline_runs` table and as JSON files. Ninety days covers roughly three months of nightly runs, which is more than enough to investigate a failure that someone notices and reports. |
| **Audit record retention** | **24 months.** The per-run summary — `run_key`, `business_date`, `status`, `rows_read`, `rows_extracted`, `rows_rejected`, and `validation_results` — is kept far longer than the detailed log, because it is the evidence that a published figure was produced correctly. |
| **Justification** | Operational detail is only useful while a problem is fresh. Audit evidence has to outlive it, because a question about last year's numbers arrives long after anyone would think to check. |
| **Storage location** | Run rows in the `psync_analytics` database, which the pipeline owns — never in the PRINTSYNC database. JSON log files sit on the pipeline host's filesystem, one file per run. |
| **Access permissions** | Write: the pipeline's service login only. Read: the analytics and development team. The pipeline's database login is read-only on `public` and cannot alter operational data. Logs contain no customer personal data — only identifiers, counts, and timestamps. |
| **Archiving** | At 90 days, detailed JSON logs are deleted and the per-table rows are pruned from `pipeline_runs`. The run-level audit row stays in the database for 24 months. No compressed archive is produced — see the note below. |
| **Deletion** | Logs are **never** deleted before the retention period expires, and never while a run is under investigation or a recovery is in progress. Deletion after the period is an automated job, not a manual one, so it cannot be forgotten or done early by hand. |
| **Operational versus audit** | Kept deliberately separate. Operational logs are disposable detail, deleted at 90 days. Audit records are the accountability trail, kept for 24 months. Conflating the two is how teams end up either hoarding everything or deleting evidence. |

**On the archive.** Earlier revisions mentioned "that night's Parquet archive" once, in the storage
row above, without defining its format, partitioning, contents or consumer. **No archive writer is
built.** The extraction stage's promise is the staging tables and the run record, and inventing an
archive format would be a specification this document never made. If an archive is wanted later,
this section defines the format first (§6.4) and then it is implemented — the same rule that governs
every other change to the contract.

---

## 6. Extraction Data Contract and Naming Convention

### 6.1 Required schema

Each source table lands in one staging table in `psync_analytics`, the pipeline's own database.
Every staging table carries three control columns that the source does not have:

| Control column | Type | Purpose |
| --- | --- | --- |
| `run_id` | uuid | Ties every row back to the run that produced it. |
| `business_date` | date | The business day the row was extracted for. |
| `extracted_at` | timestamptz | When the row was written. |

| Source table | Staging table | Grain | Staging key |
| --- | --- | --- | --- |
| `sales_transactions` | `stg_sales_transactions` | One row per sale | `source_id` |
| `sales_transaction_items` | `stg_sales_transaction_items` | One row per sale line | `source_id` |
| `payments` | `stg_payments` | One row per payment | `source_id` |
| `orders` | `stg_orders` | One row per order | `source_id` |
| `inventory_items` | `stg_inventory_items` | One row per product (snapshot) | `source_id` |
| `business_settings` | `stg_business_settings` | One row per branch | `source_id` |
| `branches` | `stg_branches` | One row per branch | `source_id` |

`source_id` holds the source table's `id` after the rename in Section 6.2, and is unique within a
run rather than across runs — the same sale appears once per run that re-reads it.

Constraints enforced on write: `run_id` not null; `business_date` not null; `source_id` not null and
unique within a run; money columns `numeric(14,2)`; timestamp columns `timestamptz`.

### 6.2 Naming convention

| Rule | Detail |
| --- | --- |
| Case | `snake_case` throughout. No camelCase, no spaces. |
| Table prefixes | `stg_` for extraction output (this stage). `fct_` and `dim_` are reserved for Transformation output. A prefix always tells you which stage produced the table. |
| Primary keys | Named `id` at source. Renamed to `source_id` in staging so it is unambiguous that it is the source system's key, not one we generated. |
| Foreign keys | Keep the source name exactly: `transaction_id`, `inventory_item_id`, `branch_id`, `customer_id`. Never rename a join key — the whole point is that it reads the same in both schemas. |
| Timestamps | Suffix `_at` for a moment in time (`created_at`, `voided_at`, `extracted_at`); suffix `_date` for a calendar day (`business_date`). |
| Control columns | `run_id`, `business_date`, `extracted_at` — identical on every staging table. |
| Abbreviations | Avoided. The one exception is `uom` (unit of measure), kept because it is already the source column name. |

### 6.3 Source-to-standardized field mappings

Most PRINTSYNC columns are already well named, so most mappings are pass-throughs. Only three
kinds of change happen: the key rename, a type tightening on money, and column drops of fields
no output needs.

| Source column | Standardized column | Source type | Target type | Mapping type |
| --- | --- | --- | --- | --- |
| `sales_transactions.id` | `source_id` | uuid | uuid | Rename |
| `sales_transactions.status` | `status` | text | text | Pass-through |
| `sales_transactions.subtotal` | `subtotal` | numeric | numeric(14,2) | Type mapping |
| `sales_transactions.discount` | `discount` | numeric | numeric(14,2) | Type mapping |
| `sales_transactions.tax` | `tax` | numeric | numeric(14,2) | Type mapping |
| `sales_transactions.total` | `total` | numeric | numeric(14,2) | Type mapping |
| `sales_transactions.payment_method` | `payment_method` | text | text | Pass-through |
| `sales_transactions.created_at` | `created_at` | timestamptz | timestamptz | Pass-through |
| `sales_transactions.voided_at` | `voided_at` | timestamptz | timestamptz | Pass-through |
| `sales_transactions.customer_id` | `customer_id` | uuid | uuid | Pass-through |
| `sales_transactions.branch_id` | `branch_id` | uuid | uuid | Pass-through |
| `sales_transaction_items.id` | `source_id` | uuid | uuid | Rename |
| `sales_transaction_items.transaction_id` | `transaction_id` | uuid | uuid | Pass-through |
| `sales_transaction_items.inventory_item_id` | `inventory_item_id` | uuid | uuid | Pass-through |
| `sales_transaction_items.name` | `name` | text | text | Pass-through (rev. 1.4) |
| `sales_transaction_items.quantity` | `quantity` | integer | integer | Pass-through |
| `sales_transaction_items.unit_price` | `unit_price` | numeric | numeric(14,2) | Type mapping |
| `sales_transaction_items.line_discount` | `line_discount` | numeric | numeric(14,2) | Type mapping |
| `payments.id` | `source_id` | uuid | uuid | Rename |
| `payments.transaction_id` | `transaction_id` | uuid | uuid | Pass-through |
| `payments.amount` | `amount` | numeric | numeric(14,2) | Type mapping |
| `payments.method` | `method` | text | text | Pass-through |
| `payments.status` | `status` | text | text | Pass-through |
| `payments.created_at` | `created_at` | timestamptz | timestamptz | Pass-through |
| `payments.voided_at` | `voided_at` | timestamptz | timestamptz | Pass-through |
| `orders.id` | `source_id` | uuid | uuid | Rename |
| `orders.status` | `status` | text | text | Pass-through |
| `orders.is_custom` | `is_custom` | boolean | boolean | Pass-through (rev. 1.5) |
| `orders.amount` | `amount` | numeric | numeric(14,2) | Type mapping |
| `orders.customer_id` | `customer_id` | uuid | uuid | Pass-through |
| `orders.created_at` | `created_at` | timestamptz | timestamptz | Pass-through |
| `orders.updated_at` | `updated_at` | timestamptz | timestamptz | Pass-through |
| `orders.branch_id` | `branch_id` | uuid | uuid | Pass-through |
| `inventory_items.id` | `source_id` | uuid | uuid | Rename |
| `inventory_items.sku` | `sku` | text | text | Pass-through |
| `inventory_items.name` | `name` | text | text | Pass-through |
| `inventory_items.category` | `category` | text | text | Pass-through |
| `inventory_items.price` | `price` | numeric | numeric(14,2) | Type mapping |
| `inventory_items.cost_price` | `cost_price` | numeric | numeric(14,2) | Type mapping |
| `inventory_items.stock` | `stock` | integer | integer | Pass-through |
| `inventory_items.reorder_level` | `reorder_level` | integer | integer | Pass-through |
| `inventory_items.uom` | `uom` | text | text | Pass-through |
| `inventory_items.updated_at` | `updated_at` | timestamptz | timestamptz | Pass-through |
| `inventory_items.branch_id` | `branch_id` | uuid | uuid | Pass-through |
| `business_settings.id` | `source_id` | integer | integer | Rename |
| `business_settings.branch_id` | `branch_id` | uuid | uuid | Pass-through |
| `business_settings.vat_rate` | `vat_rate` | numeric | numeric(14,2) | Type mapping |
| `business_settings.currency_symbol` | `currency_symbol` | text | text | Pass-through |
| `business_settings.time_zone` | `time_zone` | text | text | Pass-through |
| `branches.id` | `source_id` | uuid | uuid | Rename |
| `branches.code` | `code` | text | text | Pass-through |
| `branches.name` | `name` | text | text | Pass-through |
| `branches.is_active` | `is_active` | boolean | boolean | Pass-through |

### 6.4 Schema consistency

Unexpected changes are the main risk when extracting from a system that is still being built.
The rule is: **fail loudly, never guess.**

| Situation | Handling |
| --- | --- |
| A required column is missing or renamed | Check V2 fails. The run stops before writing anything. Nothing is substituted and no default is invented. |
| A column's data type changes | Check V2 compares against expected types. A mismatch fails the run. Widening a type is still a failure until the contract is updated on purpose. |
| A new column appears in a source table | Ignored. Extraction only selects named columns, so an additive change cannot break the run. |
| A required column becomes nullable at source | Check V5 catches resulting nulls. The run fails. |
| A table is dropped or renamed | Check V2 fails at connection time. The run stops. |
| We genuinely need to change the contract | Update Section 2 and Section 6 in this document first, then change the code. The document is the contract; code follows it, not the other way round. |

---

## 7. Extraction Acceptance and Handover Rules

### 7.1 Decision rules

| Overall condition | Decision | Pipeline action |
| --- | --- | --- |
| All critical checks pass; no warnings | **APPROVED** | Hand over to Transformation automatically |
| All critical checks pass; one or more warnings | **APPROVED WITH WARNING** | Hand over automatically; flag the run for review |
| One or more critical checks fail | **REJECTED** | Stop. Do not hand over. Retry up to 3 times with backoff, then quarantine and alert. |
| The source cannot be reached (V1) | **RETRY** | Retry 3 times at 5-minute intervals. Still failing after that: REJECTED, alert the team. |
| `run_key` already completed (V3) | **SKIPPED** | Stop without error. The day is already done; nothing to redo. |
| Rejected rows exceed 1% of `rows_read` | **MANUAL REVIEW** | Hold the pipeline. A rejection rate that high means the source changed, not that the data is merely messy. |

**Who retries.** The decision engine reports `RETRY`; it does not retry by itself. The policy —
`RETRY_COUNT` attempts, `RETRY_BACKOFF_SECONDS` apart — belongs to the orchestration layer, which
re-invokes the run. Keeping the two apart is what stops a slow source being mistaken for a broken
one: the pipeline says *why* it stopped, and the scheduler decides whether to try again.

### 7.2 Who decides

| Decision | Automatic or manual | Responsible role |
| --- | --- | --- |
| APPROVED | Automatic | None — the pipeline proceeds |
| APPROVED WITH WARNING | Automatic, with a flag | Data team reviews within one business day |
| REJECTED | Automatic stop; manual restart | Data team investigates, fixes, and re-runs |
| MANUAL REVIEW | Manual | Data team lead approves or rejects before anything proceeds |
| SKIPPED | Automatic | None |

### 7.3 Handover package

On approval, the following passes to the Transformation stage:

| Item | Detail |
| --- | --- |
| Data | The seven `stg_*` tables in `psync_analytics`, for this `run_id` and `business_date` |
| Metadata | The `pipeline_runs` row: `run_id`, `run_key`, `business_date`, window, status, timings |
| Counts | `rows_read`, `rows_extracted`, `rows_rejected` per table |
| Validation results | The outcome of every check in Section 3 |
| Rejects | Any structurally rejected rows, with `reject_reason` — handed over for logging, not for repair |
| Errors | `error_code` and `error_message`, if anything failed |

**What is explicitly *not* handed over as a claim:** no cleaning, no standardising beyond the
renames and type mappings in Section 6, no profit calculation, no daily totals, no per-product
demand, no order-status counts, and no filtering out of voided sales. Those are Transformation's
job. Extraction's only promise is that the day's records were copied completely and correctly.

### 7.4 Worked example

A normal night, 4 October 2026:

| Validation summary | Result |
| --- | --- |
| V1 source connection | PASS |
| V2 required objects exist | PASS |
| V3 window resolved | PASS |
| V4 settings available | PASS |
| V5 identifiers present | PASS |
| V6 primary key uniqueness | PASS |
| V7 count parity (all 7 tables) | PASS |
| **Overall** | **APPROVED** |

A night where the shop was closed:

| Validation summary | Result |
| --- | --- |
| V1 – V7 | PASS |
| V8 non-empty result | WARNING — 0 sales rows |
| **Overall** | **APPROVED WITH WARNING** — handed over, flagged for review |

---

## 8. Common Extraction Problems and Mitigation

Every problem below is specific to this source system, not a generic list.

### P1 — A sale is voided after its day was already processed

- **What happens:** a sale made on Monday is voided on Wednesday. Monday's numbers have already
  been published and are now wrong.
- **Cause:** `voided_at` falls outside the window that was extracted for the sale's own day.
- **Impact:** revenue for a closed day is overstated until someone notices. Silent and
  easy to miss.
- **Mitigation:** the window includes `voided_at` as well as `created_at`, so a void is picked
  up on the day it happens; the 3-day look-back re-reads recently closed days as a backstop;
  and because Transformation replaces a business date's output wholesale rather than adding to
  it, re-processing Monday simply produces the correct numbers with no double counting.

### P2 — Late corrections to a sale cannot be detected

- **What happens:** someone edits a sale after the fact — corrects a quantity, changes a price.
- **Cause:** `sales_transactions` has **no `updated_at` column**. There is no way to ask which
  sales changed since the last run.
- **Impact:** a corrected sale may never be re-extracted, so the published figure keeps the
  original, wrong value.
- **Mitigation:** the 3-day look-back re-reads recent days regardless, so corrections inside
  that window are picked up. Beyond three days, a manual re-run for the affected date is the
  remedy, and it is safe because `run_key` makes it idempotent.
- **Why it is not fixed properly:** adding an `updated_at` column with a trigger would be the
  real solution, but PRINTSYNC is to remain untouched, so we cannot add it. This gap is
  permanent for as long as that boundary holds, and the look-back is the whole answer. It is
  recorded here so nobody assumes the pipeline is catching every late edit.

### P3 — Sale line items have no timestamp

- **What happens:** `sales_transaction_items` has no `created_at` and no `updated_at`.
- **Cause:** the table was designed to be read through its parent sale.
- **Impact:** line items cannot be windowed directly. If windowed by joining to the wrong set
  of sales, items are silently missed and units sold come out low.
- **Mitigation:** items are always extracted by joining `transaction_id` to the sales already
  inside the window — never by a date filter on the item itself. Check V5 rejects any item with
  a null `transaction_id`, and check V7 compares item counts against the source, so a silent
  shortfall becomes a visible failure.

### P4 — The schema changes underneath the pipeline

- **What happens:** a developer ships a migration that renames a column we read.
- **Cause:** PRINTSYNC is under active development; multi-branch scoping landed on
  2 October 2026 and more changes are expected.
- **Impact:** without a guard, the query either errors mid-run or — worse — silently returns
  nothing for that column and produces plausible but wrong numbers.
- **Mitigation:** check V2 verifies every required table and column, with its type, before
  reading any data. A mismatch fails the run at once. The pipeline never guesses a substitute
  column and never falls back to a default value.
- **Why this matters more than usual here:** because the pipeline is external, we have no
  control over when a migration ships and no way to require notice. The PRINTSYNC team will
  change their schema on their own schedule. Our only defence is to detect the change and stop,
  which is exactly what V2 does.

### P5 — Multi-branch scoping is still settling

- **What happens:** `branch_id` is now `NOT NULL` on every transaction table, and
  `business_settings` became one row per branch. Lab 2 assumed a single shop settings row.
- **Cause:** branch support was added recently and is still being refined.
- **Impact:** if we tried to produce per-branch business days now, each branch's own time zone
  would define a different day boundary — a large complication for a feature that is not
  finished.
- **Mitigation:** Stage 1 sidesteps it. We carry `branch_id` as a plain, unresolved attribute
  and extract `branches` only as a four-column lookup. The time zone comes from one configured
  reference branch (assumption L5). Per-branch aggregation is deliberately deferred until the
  branch design is stable, and the data needed for it is already present when it is.

### P6 — The database is unreachable, or the connection pool is full

- **What happens:** the run cannot connect, or connects and is refused.
- **Cause:** Supabase limits concurrent connections; a network blip between our host and theirs;
  credentials rotated. Because the pipeline runs outside the shop's infrastructure, the network
  between the two is a dependency we do not control.
- **Impact:** the night's data is not extracted. Reports show yesterday's numbers.
- **Mitigation:** check V1 catches it before any read. Three retries at 5-minute intervals with
  backoff — not immediate reconnection, which makes a pool problem worse. One connection with
  a server-side cursor keeps the footprint small. The 01:00 schedule avoids competing with the
  point-of-sale. If all retries fail, the run is rejected and the team is alerted; the next
  scheduled run picks up the missed day because it is driven by `business_date`, not by the clock.

### P7 — Re-running duplicates the day's data

- **What happens:** a run is retried, or someone re-runs a date by hand.
- **Cause:** extraction, by itself, is additive — a second read writes a second set of rows.
- **Impact:** revenue and units sold double. The most dangerous failure in this list, because
  the numbers look plausible.
- **Mitigation:** every run is keyed by `run_key`. A completed `run_key` causes the next run to
  skip (V3). Staging rows are cleared for that `run_id` before being rewritten, and
  Transformation replaces a business date's output in one transaction. Running twice is
  therefore harmless by design, not by convention.

---

## 9. Revision history

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | 5 October 2026 | Initial extraction specification. |
| 1.1 | 14 October 2026 | Corrected the index name in Section 1.2 (`sales_transaction_items_transaction_idx`, after the duplicate index was dropped on 21 September 2026); stated the `pipeline_runs` grain in Section 4 (one row per source table per run, plus one run-level summary row); stated that the closed-day flag in Section 3 is an operator-supplied run parameter. Extraction scope, tables, columns, validation criteria and acceptance rules are unchanged. |
| 1.2 | 25 October 2026 | Removed the unspecified Parquet archive from Section 5 and stated that operational detail is deleted at 90 days rather than archived; added a note to Section 7.1 that `RETRY` is reported by the pipeline and performed by the orchestration layer. Both changes make the document describe what was built. Extraction scope, tables, columns, validation criteria and acceptance rules are unchanged. |
| 1.3 | 25 October 2026 | Corrected three inconsistencies found while checking the document against its own contract. Section 1.3 named a script `extract.py`, which does not exist — the pipeline is the `psync_extract` package, run as `python -m psync_extract --date YYYY-MM-DD` or through the `extraction_flow` Prefect flow — and the stated Python version is now "3.12 or newer", since the development host runs 3.13. Section 6.1 called the staging key `id` when Section 6.2 renames it to `source_id`. Section 6.3 was missing four mappings (`orders.branch_id`, `inventory_items.updated_at`, `inventory_items.branch_id`, `business_settings.branch_id`) and now covers all 51 columns. No change to scope, tables, columns, checks or acceptance rules. |
| 1.4 | 26 October 2026 | **Added `sales_transaction_items.name` to the extraction scope** (§2.2 and §6.3), at the request of the Transformation stage. Stage 2 identifies a product by the name printed on the sale line because `inventory_item_id` is null on 93.4 % of lines — the shop sells print services that were never catalogued — so without this column 93 % of revenue cannot be attributed to a product. The column is a pass-through, extracted unchanged; staging gained it through a new migration (`002_stg_item_name.sql`) rather than by editing the applied `001`. One column added, no column removed, no check or acceptance rule changed; the registry in `psync_extract.schema` and the items extractor now cover 52 columns instead of 51. |
| 1.5 | 26 October 2026 | **Added `orders.is_custom` to the extraction scope** (§2.4 and §6.3), for the same reason as revision 1.4: `fct_daily_order_status.custom_order_count` needs it, and §2.4 did not list the column. Found by checking the Transformation stage's inputs against what this document extracts — the second such gap, which is what makes the practice worth keeping. The column is a pass-through; staging gained it through `004_stg_order_custom.sql`; the registry and the orders extractor now cover 53 columns. No check or acceptance rule changed. |
| 1.6 | 27 October 2026 | **Prefect is now an optional extra, not a dependency.** §1.3 and §1.6 described Prefect 3 as part of the tool stack without saying it is optional, which read as a required framework — and the project's constraints rule out an orchestration framework in the pipeline itself. The package now declares `prefect` under `[project.optional-dependencies] orchestration`, so a base install contains no orchestrator and `python -m psync_extract --date YYYY-MM-DD` runs with nothing but Psycopg; `flow.py` raises a message naming the extra when it is absent. Both rows of §1.6 that mentioned Prefect now say it is optional. No table, column, check or acceptance rule changed, and this revision also joins a line in the 1.5 row that had wrapped inside a table cell. |

---

## 10. References

- Bulan, L. J. D., Rendal, R. C., & Vidal, M. E. Z. (2026, September 9). *Data Pipeline Technology Research for PRINTSYNC*. BAT-405 Laboratory Activity 1.
- Bulan, L. J. D., Rendal, R. C., & Vidal, M. E. Z. (2026, September 16). *Technical Metadata Documentation for PRINTSYNC*. BAT-405 Laboratory Activity 2.
- PRINTSYNC source schema: `supabase/migrations/` and `0_never-push-this-dump-folder/postgre-supabase-data/0_supabase-schema.sql` (snapshot dated 3 October 2026).
- Psycopg 3 — https://www.psycopg.org/psycopg3/docs/
- Prefect 3 — https://docs.prefect.io/v3/get-started
- PostgreSQL — https://www.postgresql.org/docs/
- Supabase — https://supabase.com/docs/guides/database/connecting-to-postgres
