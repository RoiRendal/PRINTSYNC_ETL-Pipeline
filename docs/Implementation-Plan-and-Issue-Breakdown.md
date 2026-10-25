# Implementation Plan & Issue Breakdown — Extraction Phase (Lab 3)

**Pipeline:** `psync_nightly_analytics` · Stage 1 of 3 (Extract → Transform → Load)
**Source of truth:** [`Data-Extraction-Documentation-for-PRINTSYNC.md`](./Extraction/Data-Extraction-Documentation-for-PRINTSYNC.md)
**Repo:** https://github.com/RoiRendal/PRINTSYNC_ETL-Pipeline
**Team:** Issuer — Ma. Erica Z. Vidal · Documentator — Lyell Jasmine D. Bulan · Coder — Roi C. Rendal
**Plan date:** 14 October 2026
**Status:** extraction stage complete 25 October 2026 — **29 of 30 issues closed**, E-30 out of scope

---

## 1. What this plan is

The extraction stage is built **issue by issue**. Every GitHub issue is a task instruction, and every
commit addresses exactly one issue. This document breaks the whole of Stage 1 into small,
independently verifiable issues so that:

1. each issue can be closed by one focused change,
2. every line of code traces back to a documented requirement, and
3. the issue history itself is the evidence of work done (more issues = more visible work).

**No code has been written yet.** This is the plan for approval before any issue is created.

---

## 2. Ground rules

| # | Rule |
| --- | --- |
| G1 | **The documentation is the contract.** Code follows the document, never the reverse (§6.4). If the contract must change, the document is updated first — by the documentator — then the issue is opened. |
| G2 | **PRINTSYNC stays untouched** (§1.1, §1.6). The pipeline lives in this repo, reads over a read-only login, and writes only to its own database `psync_analytics`. No DDL, no tables, no indexes, no triggers on the source. |
| G3 | **One issue → one change.** A commit/PR references its issue (`Closes #N`). No issue, no code. |
| G4 | **Fail loudly, never guess** (§6.4). Missing column, changed type, absent settings → stop the run; never substitute a default. |
| G5 | **Nothing is cleaned in Stage 1** (§7.3). No filtering of voided rows, no totals, no profit, no aggregation. Extraction copies and proves the copy is complete. |
| G6 | **Documentation references are mandatory.** Every issue cites the document sections it implements, so a reviewer can check the code against the spec line by line. |
| G7 | **No automated tests.** The professor asked for the tests to be skipped, so the project ships no test files and no test folder. Each issue is evidenced by real output — a command's result, a query against the database, or a run log — not by a test report. The pipeline's own checks (V1–V8) are its verification mechanism. |

---

## 3. Workflow

```
Issue opened (task instruction)
   └─ branch:  issue-<N>-<short-slug>
        └─ commits: feat(extraction): ... (references #N)
             └─ PR into main, body = "Closes #N" + evidence (command result / query / run log)
                  └─ issue closed → next issue unblocked
```

- **Branch naming:** `issue-12-sales-transactions-extractor`
- **PR evidence:** for validation issues, attach the failing/passing check output; for extractors,
  the row-count parity output from the local development database.
- **Issue template (kept short — the reader should not have to wade through it):** *Why → Task →
  Done when (checkboxes) → Depends on.* Technical detail belongs in the code and the document, not
  in the issue.
- **Definition of done:** acceptance criteria all checked, the change demonstrated with real output (a command result, a query, or a run log), doc reference verified, PR merged.

**Repository layout.** All pipeline code lives under `pipeline/`. Only documentation, the
README and the root `.gitignore` sit at the repository root.

```
PRINTSYNC_ETL-Pipeline/
├── docs/Extraction/     specification, implementation plan, issue texts
├── pipeline/            the entire pipeline: pyproject.toml, src/, .env.example
├── .gitignore
└── README.md
```

---

## 4. Grouping

**Labels and milestones are not used on GitHub.** Each issue is posted with a **title and a
description only**, so every file in `docs/issues/` is written in that form: one
`TITLE:` line, then the description below the `---`.

**Issues are for code only.** Documentation work — the specification, this plan, the README —
is never an issue. An issue must be closable by a code change.

The milestones below are **internal sequencing only** — they group the work into six phases and
are recorded here for planning. They are not created in the repository.

| Milestone | Contents | Issues |
| --- | --- | --- |
| **M1 — Project Foundation** | Python project, config, `psync_analytics` schema, migration applier | E-01 – E-04 |
| **M2 — Connectivity & Pre-flight Validation** | Connection, V1–V4, window math, schema registry | E-05 – E-11 |
| **M3 — Extractors & Staging** | Seven table extractors, staging writer, parity bookkeeping | E-12 – E-19 |
| **M4 — Structural Validation** | V5, V6, V8, reject-rate tracking | E-20 – E-23 |
| **M5 — Metadata, Logging & Orchestration** | `pipeline_runs`, JSON logs, decision engine, Prefect flow, handover | E-24 – E-28 |
| **M6 — Retention** | 90-day operational / 24-month audit retention. The Parquet archive (E-30) is out of scope — see §8 Q6 | E-29 |

---

## 5. Issue list (summary)

30 issues were planned; **29 are in scope**. E-30 (the Parquet archive) is out of scope by decision
on 25 October 2026 — see §8 Q6. Dependencies are given by issue ID; they become GitHub issue numbers
once created.

| ID | Title | Milestone | Kind | Depends on | Doc ref |
| --- | --- | --- | --- | --- | --- |
| E-01 | Initialize Python 3.12 project scaffold and dependencies | M1 | infrastructure, P0 | — | §1.3, §1.6 |
| E-02 | Implement configuration module for source/target DB and run parameters | M1 | infrastructure, P0 | E-01 | §1.3, §1.5 (L5), §4 |
| E-03 | Add `psync_analytics` migrations: 7 staging tables + `pipeline_runs` | M1 | infrastructure, P0 | E-01 | §6.1, §4 |
| E-04 | Add idempotent migration applier with source/target boundary guard | M1 | infrastructure, P1 | E-03 | §1.6 |
| E-05 | Implement read-only source connection (Psycopg 3, SSL, server-side cursor) | M2 | extraction, P0 | E-01 | §1.2, §1.3 |
| E-06 | Implement V1 source-connection check | M2 | validation, P0 | E-05 | §3 V1, §7.1 |
| E-07 | Add expected-schema registry for the 7 source tables | M2 | validation, P0 | E-01 | §2, §6.3 |
| E-08 | Implement V2 schema-drift validation (fail loudly) | M2 | validation, P0 | E-07 | §3 V2, §6.4, P4 |
| E-09 | Implement business-day window computation with 3-day look-back | M2 | extraction, P0 | E-02 | §1.3 |
| E-10 | Implement V3 window/resolution check and `run_key` duplicate detection | M2 | validation, P0 | E-09, E-03 | §3 V3, §7.1, §4 |
| E-11 | Implement V4 reference-branch settings resolution | M2 | extraction, P0 | E-05, E-02 | §3 V4, §2.6, L5 |
| E-12 | Implement `sales_transactions` extractor (created_at OR voided_at) | M3 | extraction, P0 | E-05, E-09 | §1.3, §2.1, P1 |
| E-13 | Implement `sales_transaction_items` extractor via parent-sale join | M3 | extraction, P0 | E-12 | §1.3, §2.2, P3 |
| E-14 | Implement `payments` extractor (created_at OR voided_at) | M3 | extraction, P0 | E-05, E-09 | §1.3, §2.3 |
| E-15 | Implement `orders` extractor (updated_at window) | M3 | extraction, P0 | E-05, E-09 | §1.3, §2.4 |
| E-16 | Implement full-snapshot extractor for `inventory_items` | M3 | extraction, P0 | E-05 | §1.3, §2.5 |
| E-17 | Implement full-snapshot extractors for `business_settings` and `branches` | M3 | extraction, P1 | E-05 | §1.3, §2.6, §2.7 |
| E-18 | Implement staging writer with control columns and type mappings | M3 | extraction, P0 | E-03, E-12 | §6.1–§6.3 |
| E-19 | Implement run-scoped staging reset and V7 count parity | M3 | extraction, P0 | E-18 | §3 V7, §7.1, P7 |
| E-20 | Implement V5 identifier-presence checks and reject capture | M4 | validation, P0 | E-18 | §3 V5 |
| E-21 | Implement V6 primary-key uniqueness checks | M4 | validation, P0 | E-18 | §3 V6 |
| E-22 | Implement V8 non-empty-result warning with closed-day flag | M4 | validation, P1 | E-18 | §3 V8, §7.4 |
| E-23 | Implement structural reject-rate tracking (>1% → MANUAL REVIEW) | M4 | validation, P1 | E-20 | §7.1 |
| E-24 | Implement `pipeline_runs` metadata recorder (full field contract) | M5 | metadata, P0 | E-03 | §4 |
| E-25 | Implement per-run JSON log file writer | M5 | metadata, P1 | E-24 | §4, §5 |
| E-26 | Implement acceptance decision engine (§7.1 decision table) | M5 | orchestration, P0 | E-06, E-10, E-23 | §7.1 |
| E-27 | Orchestrate a run: plain entry point plus a Prefect 3 flow | M5 | orchestration, P0 | E-11, E-19, E-24, E-26 | §1.3, §7.1, P6 |
| E-28 | Implement handover finalization and run summary emission | M5 | orchestration, P1 | E-27 | §7.3 |
| E-29 | Implement 90-day log retention and 24-month audit retention job | M6 | infrastructure, P2 | E-24, E-25 | §5 |
| E-30 | ~~Nightly Parquet archive writer~~ — **out of scope** (§8 Q6) | — | — | — | §5 |

---

## 6. Detailed issue specifications

### M1 — Project Foundation

**E-01 · Initialize Python 3.12 project scaffold and dependencies**
- *Context:* Lab 1 chose Python + Psycopg 3 + Prefect 3; Lab 3 confirms them (§1.3). The pipeline is a standalone project outside PRINTSYNC (§1.6).
- *Task:* Create the project under `pipeline/`: `pyproject.toml` (Python ≥3.12; `psycopg[binary]>=3`, `prefect>=3`, `pydantic-settings`), the `src/psync_extract/` package layout, and `.env.example`; plus the root `.gitignore` and `README.md`.
- *Acceptance criteria:*
  - [ ] `pip install -e .` succeeds from `pipeline/` on a clean Python 3.12.
  - [ ] `python -c "import psync_extract"` works.
  - [ ] No PRINTSYNC code is imported anywhere.
  - [ ] `.env.example` lists every variable from E-02 (names only, no secrets).
  - [ ] All pipeline code sits under `pipeline/`; the repository root holds only `docs/`, `pipeline/`, `README.md` and `.gitignore`.
- *Out of scope:* any database logic.

**E-02 · Implement configuration module for source/target DB and run parameters**
- *Context:* the run needs a read-only source DSN, the `psync_analytics` DSN, and run parameters (§1.3, §4).
- *Task:* `Settings` via `pydantic-settings` with: `PSYNC_SOURCE_DSN` (read-only), `PSYNC_TARGET_DSN` (`psync_analytics`), `PIPELINE_NAME` (default `psync_nightly_analytics`), `BUSINESS_DATE` (default: yesterday in Asia/Manila), `LOOKBACK_DAYS` (default `3`), `REFERENCE_BRANCH` (the Balayan branch's `code` or UUID), `RUN_TIMEZONE` (default `Asia/Manila`), `CONNECT_TIMEOUT_SECONDS`, `RETRY_COUNT` (default `3`), `RETRY_BACKOFF_SECONDS` (default `300`).
- *Acceptance criteria:*
  - [ ] Missing required variable → single clear startup error naming the variable.
  - [ ] Defaults match §1.3 and §4 (`lookback_days = 3`).
  - [ ] Demonstrated: the loader run with a variable missing names it in one clear error, and the defaults match the specification.
- *Doc refs:* §1.3, §1.5 (L5), §4.

**E-03 · Add `psync_analytics` migrations: 7 staging tables + `pipeline_runs`**
- *Context:* staging tables and the run-metadata table live in the pipeline's own database, never in PRINTSYNC (§6.1, §1.6).
- *Task:* SQL migrations creating `stg_sales_transactions`, `stg_sales_transaction_items`, `stg_payments`, `stg_orders`, `stg_inventory_items`, `stg_business_settings`, `stg_branches` and `pipeline_runs`.
- *Acceptance criteria:*
  - [ ] Every staging table has `run_id uuid NOT NULL`, `business_date date NOT NULL`, `extracted_at timestamptz NOT NULL`.
  - [ ] Source primary key is named `source_id` (not `id`); join keys keep source names (`transaction_id`, `inventory_item_id`, `branch_id`, `customer_id`) — §6.2.
  - [ ] Money columns are `numeric(14,2)`; timestamps are `timestamptz` — §6.1.
  - [ ] `pipeline_runs` columns match §4 exactly (including `validation_results`, `error_code`, `error_message`, `reject_reason`).
  - [ ] Migrations replay cleanly against an empty **local Docker PostgreSQL** database (Q1).
- *Out of scope:* any `fct_*` / `dim_*` tables (Transformation stage).

**E-04 · Add idempotent migration applier with source/target boundary guard**
- *Context:* §1.6 makes the source/target boundary a hard rule.
- *Task:* `python -m psync_extract.db migrate` applies migrations to the target database only, idempotently.
- *Acceptance criteria:*
  - [ ] Second run is a no-op.
  - [ ] The command **refuses to run** if the target DSN resolves to the same host/database as the source DSN (boundary guard, G2).
  - [ ] Demonstrated: running the command twice is a no-op, and it refuses when the target and the source resolve to the same database.

---

### M2 — Connectivity & Pre-flight Validation

**E-05 · Implement read-only source connection**
- *Context:* encrypted TCP connection over SSL with a dedicated read-only login; one connection with a server-side cursor; Supabase connection limits apply (§1.2, L7, L8).
- *Task:* a connection module returning a context manager with `connect_timeout` and a factory for psycopg 3 server-side (named) cursors.
- *Acceptance criteria:*
  - [ ] A connection opens using the configured timeout; encryption is carried by the source DSN (`sslmode=require`) and the negotiated session is proven at V1.
  - [ ] The session is read-only **at the server**: a write fails with a PostgreSQL error.
  - [ ] The module exposes no write API — no DDL, no DML, no caller-supplied SQL.
  - [ ] Server-side cursor streaming is demonstrated on a large result: the cursor is named and visible in `pg_cursors`, and rows arrive in batches.
- *Doc refs:* §1.2, §1.3, L7, L8.

**E-06 · Implement V1 source-connection check**
- *Acceptance criteria:*
  - [ ] Opens the connection and runs `SELECT 1` within the configured timeout.
  - [ ] Failure raises a typed `SourceUnavailableError` carrying `error_code` (`SRC_CONN_TIMEOUT` / `SRC_CONN_REFUSED`).
  - [ ] Both outcomes demonstrated against the real source: a reachable database passes, an unreachable one raises the typed error carrying its code.
- *Doc refs:* §3 V1, §7.1 (RETRY), P6.

**E-07 · Add expected-schema registry for the 7 source tables**
- *Context:* V2 needs a machine-readable copy of §2.
- *Task:* a registry mapping each of the 7 tables to its ordered `(column, expected type)` list, exactly as §2 and §6.3 state.
- *Acceptance criteria:*
  - [ ] Registry contains exactly 7 tables and the column counts from §2 (11, 6, 7, 7, 11, 5, 4 — 51 in total).
  - [ ] Expected types use the normalized families (uuid, text, numeric, integer, timestamptz, boolean).
  - [ ] The registry is checked table by table against the document before it is committed.
- *Doc refs:* §2, §6.3.

**E-08 · Implement V2 schema-drift validation**
- *Task:* query `information_schema.columns` for `public`; verify every required table and column exists with a compatible type; report all diffs at once.
- *Acceptance criteria:*
  - [ ] Missing/renamed table or column → run stops **before any data is read**.
  - [ ] Type mismatch → fails; no widening, no substitution (G4).
  - [ ] New source columns are ignored (additive change cannot break the run).
  - [ ] Error message lists every missing/mismatched object.
  - [ ] All three failure shapes demonstrated on a scratch database: a dropped table, a renamed column and a changed type each stop the run before any read.
- *Doc refs:* §3 V2, §6.4, P4.

**E-09 · Implement business-day window computation with 3-day look-back**
- *Task:* pure functions: `window_start = business_date 00:00 +08:00`, `window_end = (business_date + 1) 00:00 +08:00`, and the effective read range `[window_start − lookback_days, window_end)`.
- *Acceptance criteria:*
  - [ ] Window boundaries are exclusive at the end and computed in `Asia/Manila` (no DST in PH; note it explicitly).
  - [ ] Month-end, year-end and leap-day boundaries checked against the computed window before the issue is closed.
  - [ ] `lookback_days` comes from config (default 3), not a literal.
  - [ ] A future date is **not** rejected here — this function is arithmetic only; V3 decides what is acceptable.
- *Doc refs:* §1.3.

**E-10 · Implement V3 window/resolution check and `run_key` duplicate detection**
- *Task:* validate `business_date` is a valid past date; build `run_key = psync_nightly_analytics:{business_date}`; query `pipeline_runs` for a completed run with the same `run_key`.
- *Acceptance criteria:*
  - [ ] Completed `run_key` → run resolves to **SKIPPED**, exits without error (§7.1).
  - [ ] Invalid/future date → critical failure.
  - [ ] Both paths demonstrated: a completed `run_key` skips, an invalid date fails.
- *Doc refs:* §3 V3, §7.1, §4, P7.

**E-11 · Implement V4 reference-branch settings resolution**
- *Task:* read the `business_settings` row for the configured reference branch; require a non-null `time_zone`; expose `time_zone`, `vat_rate`, `currency_symbol` for the run.
- *Acceptance criteria:*
  - [ ] No row for the reference branch, or null `time_zone` → `SettingsUnavailableError` (critical, run cannot start).
  - [ ] Values are recorded on the run so §4 metadata can carry them.
  - [ ] No silent fallback to the first active branch (G4); the reference branch is explicit config.
- *Doc refs:* §3 V4, §2.6, L5, P5.

---

### M3 — Extractors & Staging

> All windowed extractors read the range `[business_date − lookback_days, business_date + 1)` and stream through a server-side cursor. All extractors select **only** the columns in §2.

**E-12 · Implement `sales_transactions` extractor**
- *Task:* window predicate `(created_at >= start AND created_at < end) OR (voided_at >= start AND voided_at < end)`; 11 columns from §2.1.
- *Acceptance criteria:*
  - [ ] A sale made earlier but voided inside the range **is** returned (P1).
  - [ ] Voided and completed rows are both extracted — no filtering (G5, §1.4).
  - [ ] `rows_read` is counted.
- *Doc refs:* §1.3, §2.1, P1.

**E-13 · Implement `sales_transaction_items` extractor via parent-sale join**
- *Task:* select items by joining `transaction_id` to the sales already inside the window — never a date filter on the item (the table has no timestamp).
- *Acceptance criteria:*
  - [ ] The item query contains **no** timestamp predicate on the item table itself.
  - [ ] Item count equals the count of items whose parent sale is in the window (parity check).
  - [ ] 6 columns from §2.2.
- *Doc refs:* §1.3, §2.2, P3, L3.

**E-14 · Implement `payments` extractor**
- *Acceptance criteria:* window on `created_at` OR `voided_at`; 6 columns from §2.3; multi-payment sales return every payment row.

**E-15 · Implement `orders` extractor**
- *Acceptance criteria:* window on `updated_at` only; 7 columns from §2.4; a late status change moves the row into the window.

**E-16 · Implement full-snapshot extractor for `inventory_items`**
- *Acceptance criteria:* full extract every run, no window; 11 columns from §2.5; `cost_price` present (needed for profit later).

**E-17 · Implement full-snapshot extractors for `business_settings` and `branches`**
- *Acceptance criteria:* full extracts; 4 columns each (§2.6, §2.7); `business_settings` returns one row per branch.

**E-18 · Implement staging writer with control columns and type mappings**
- *Task:* parameterized inserts into `stg_*` applying §6.3: `id → source_id`, money → `numeric(14,2)`, plus `run_id`, `business_date`, `extracted_at`.
- *Acceptance criteria:*
  - [ ] Column order and names in each `stg_*` insert match §6.1/§6.3 exactly.
  - [ ] All inserts are parameterized (no string-built SQL).
  - [ ] Per-table counters `rows_extracted` / `rows_rejected` are returned to the caller.
  - [ ] Demonstrated on the development database: a seeded day is written and read back.
- *Doc refs:* §6.1–§6.3.

**E-19 · Implement run-scoped staging reset and V7 count parity**
- *Task:* before writing, delete staging rows for the current `run_id` (re-run safety, P7); after writing, assert `rows_read == rows_extracted + rows_rejected` per table.
- *Acceptance criteria:*
  - [ ] Re-running the same `run_id` produces no duplicate rows.
  - [ ] Any parity violation fails the run as a critical check.
  - [ ] Parity is computed per table, not only in total.
- *Doc refs:* §3 V7, §7.1, P7.

---

### M4 — Structural Validation

**E-20 · Implement V5 identifier-presence checks and reject capture**
- *Acceptance criteria:*
  - [ ] Zero null `source_id` on all 7 staging tables; zero null `transaction_id` on items and payments.
  - [ ] A violating row is **rejected**, not silently dropped, and recorded with `reject_reason` (`null_primary_key`, `null_transaction_id`).
  - [ ] In a healthy run, `rows_rejected = 0`.
- *Doc refs:* §3 V5, §3 "On rejects".

**E-21 · Implement V6 primary-key uniqueness checks**
- *Acceptance criteria:* per table, `count(distinct source_id) == count(*)`; a duplicate fails the run and the offending ids are reported (capped list).

**E-22 · Implement V8 non-empty-result warning with closed-day flag**
- *Acceptance criteria:* zero `sales_transactions` rows → WARNING, run continues; a run explicitly flagged as a closed day → no warning (§7.4). The flag is a run parameter, never inferred.

**E-23 · Implement structural reject-rate tracking**
- *Acceptance criteria:* per-table `rejected / read` computed; exceeding 1% sets the MANUAL REVIEW outcome (§7.1); the rate is recorded in the run metadata.

---

### M5 — Metadata, Logging & Orchestration

**E-24 · Implement `pipeline_runs` metadata recorder**
- *Task:* write every field in §4 for each run, with status transitions `running → success | failed | skipped`.
- *Acceptance criteria:*
  - [ ] All §4 fields written, including `run_key`, `extraction_window_start/end`, `lookback_days`, `rows_read/extracted/rejected`, `validation_results` (JSON of V1–V8), `error_code`, `error_message`, `reject_reason`.
  - [ ] A crashed run leaves a `failed` row, not a missing one.
  - [ ] Grain clarified and implemented consistently (see Open Question Q3).
- *Doc refs:* §4.

**E-25 · Implement per-run JSON log file writer**
- *Acceptance criteria:* one JSON file per run on the pipeline host; structured entries per table plus the validation summary; contains no customer personal data (identifiers, counts, timestamps only).
- *Doc refs:* §4, §5.

**E-26 · Implement acceptance decision engine**
- *Task:* implement the §7.1 decision table.
- *Acceptance criteria:*
  - [ ] All six outcomes implemented: APPROVED, APPROVED WITH WARNING, REJECTED, RETRY (V1 unreachable → 3 retries at 5-minute intervals), SKIPPED (completed `run_key`), MANUAL REVIEW (rejects > 1%).
  - [ ] Critical failure ⇒ stop, no handover; retries up to 3 with backoff, then quarantine + alert.
  - [ ] Every row of §7.1 and both worked examples in §7.4 walked through against a real run.
- *Doc refs:* §7.1, §7.4.

**E-27 · Orchestrate a run: plain entry point plus a Prefect 3 flow**
- *Task:* `run_extraction(settings, business_date)` wires config → V1 → V2 → V4 → V3 → extractors →
  staging → rejects → V5–V8 → decision → metadata → log → handover. Two entry points call it:
  `python -m psync_extract --date YYYY-MM-DD` and a thin `@flow`.
- *Acceptance criteria:*
  - [ ] `python -m psync_extract --date YYYY-MM-DD` runs a day end to end — exit 0 when the data may be handed over, 1 when it may not, 2 on a configuration error.
  - [ ] The Prefect flow calls the same function and reimplements nothing, so a demo and a schedule cannot drift apart.
  - [ ] A second run of the same `run_key` returns SKIPPED and exits 0.
  - [ ] One connection and server-side cursors throughout (L8).
  - [ ] An end-to-end run against the development database produces a complete `pipeline_runs` lifecycle.
- *Note on scheduling:* the 01:00 schedule is a deployment concern, not code. **Prefect 3.8.8 cannot
  run a flow on the development host** — the client posts to `/api/flows/` and receives 404, with both
  the ephemeral server and a dedicated one that answers `/api/health` with 200. The CLI entry point is
  what is demonstrated; the flow needs no change once that install is fixed.
- *Doc refs:* §1.3, §7.1, P6, L8, L10.

**E-28 · Implement handover finalization and run summary emission**
- *Acceptance criteria:* on APPROVED / APPROVED WITH WARNING, the run is finalized and the handover package recorded (§7.3): run metadata, per-table counts, validation results, rejects with reasons, errors. Warnings set a review flag for the data team.

---

### M6 — Retention & Archive

**E-29 · Implement 90-day log retention and 24-month audit retention job**
- *Acceptance criteria:* detailed JSON logs pruned/archived at 90 days (compressed archive); the per-run audit summary (`run_key`, `business_date`, status, counts, `validation_results`) retained 24 months; deletion is automated, never manual; a run under investigation is never deleted.
- *Doc refs:* §5.

**E-30 · Nightly Parquet archive writer — OUT OF SCOPE (Q6, 25 October 2026)**
- *Decision:* **not implemented.**
- *Why:* "Parquet" appears exactly once in the specification — §5's *Storage location* row, in
  passing. No schema, partitioning, naming convention or consumer is defined anywhere, and the
  archive is absent from §2 (tables), §3 (checks) and §7.3's handover list. Implementing it would mean
  inventing a format and presenting it as though the document asked for it.
- *Consequence:* the plan closes at **29 of 30 issues**. If the archive is wanted later, the
  documentator specifies format and partitioning first (G1), and it becomes a new issue.
- *Doc refs:* §5, §9.

---

## 7. Verification findings against the live source schema

Checked against `PRINTSYNC/0_never-push-this-dump-folder/postgre-supabase-data/supabase-schema.sql` and `PRINTSYNC/supabase/migrations/`.

| Finding | Detail | Action |
| --- | --- | --- |
| **F1 — Documentation §1.2 index list is stale** | `sales_transaction_items_transaction_created_idx` was **dropped** on 21 Sep 2026 (`20260921000600_drop_duplicate_transaction_items_index.sql`) as a duplicate of `sales_transaction_items_transaction_idx`. The doc still lists the dropped name as an index the pipeline uses. | Documentator updates §1.2; no code impact (extraction still joins on `transaction_id`, which stays indexed). |
| **F2 — Column lists confirmed** | All 7 tables exist and every column in §2 is present, with the documented types. `sales_transactions` genuinely has **no** `updated_at` (L2/P2 confirmed). | None. |
| **F3 — `business_settings` is per-branch** | `branch_id uuid NOT NULL UNIQUE`, defaults `vat_rate 12`, `currency_symbol ₱`, `time_zone Asia/Manila`. | Confirms L5; E-11 implements the reference-branch read. |
| **F4 — Extra source columns exist but are out of scope** | `sales_transactions.customer` (text), `orders.customer`/`notes`/`is_custom`/`due_date`/`reference`/`archived_at`, `inventory_items.image_url`/`created_at`/`is_low_stock`, `branches.address`/`time_zone`. §2 does not list them. | Confirms the additive-change rule (§6.4) — V2 must not fail on them. Q5 decided 25 October 2026: they are not carried into staging. |
| **F5 — Indexes live in migrations, not the dump** | The dump predates the index migrations; the three indexes §1.2 relies on (minus the dropped one) are created in `20260910001400_analytics_indexes.sql`. | None; note for the drift check that indexes are not validated. |

---

## 8. Open questions

**Answered — 14 October 2026.**

| # | Question | Answer |
| --- | --- | --- |
| Q1 | Where does `psync_analytics` run in development — a local Docker PostgreSQL, or a second Supabase project? | **A local Docker PostgreSQL**, for development. The production target is decided before the first real run. |
| Q2 | Which branch is the configured reference branch (§1.5 L5), and should the run fail when it is unset? | **Balayan.** The pipeline reads `REFERENCE_BRANCH` — the Balayan branch's `code` or UUID — from `.env`. It fails loudly when it is unset, and when that branch has no settings row or a blank time zone. The value is found with `SELECT id, code, name FROM public.branches ORDER BY code;`. |
| Q3 | `pipeline_runs` grain: one row per run, or one row per table per run? | **One row per source table per run, plus one run-level summary row.** Written into the document as part of revision 1.1. |
| Q4 | How is a "closed day" flagged for V8? | **An operator-supplied run parameter.** Never inferred from the data. Written into the document as part of revision 1.1. |

**Answered — 25 October 2026.**

| # | Question | Answer |
| --- | --- | --- |
| Q5 | `sales_transactions.customer` (the denormalised customer name) is not in §2.1. Carry it into staging or not? | **No.** The document is the contract; §2.1 does not list it, and a column added at source is ignored by design (§6.4). If it is ever wanted, §2.1 is amended first and the registry gains the column. |
| Q6 | Is the nightly Parquet archive in scope? §5 mentions it once, with no specification. | **No.** Mentioned once, never specified. E-30 is out of scope and the plan closes at 29 issues. |
| Q7 | Prefect 3 deployment target: local Prefect server, or Prefect Cloud? | **Neither, for now.** The flow is written against the same function the CLI calls. Running a server or Cloud is a deployment step, and is blocked in practice by a client/server mismatch in Prefect 3.8.8 on the development host. |
| Q8 | Do issues need due dates for grading? | **No** — issues carry a title and a description only. |

---

## 9. Current status

**Extraction stage complete — 25 October 2026. 29 of 30 issues closed; E-30 out of scope.**

| Item | State |
| --- | --- |
| Plan | Approved 14 October 2026 |
| Q1–Q4 | Answered 14 October 2026 |
| Q5–Q8 | Answered 25 October 2026: no `customer` column, no Parquet archive, no Prefect deployment target for now, no due dates |
| Issues E-01 – E-29 | All closed, each with a merged pull request and its evidence in the PR body |
| E-30 | Out of scope (Q6) |
| Entry point | `python -m psync_extract --date YYYY-MM-DD` |
| Last verified run | `--date 2026-10-17` → **APPROVED**, 7 tables, 16 rows, V1–V8 all PASS, log and handover written. A second run of the same day → **SKIPPED**, exit 0 |

**What the pipeline does now.** Reads all seven tables from PRINTSYNC over a read-only, encrypted
connection; validates the schema, the shop settings and the day before touching data; writes every
row into `psync_analytics` with `run_id`, `business_date` and `extracted_at`; rejects child rows that
cannot be attributed to a sale; runs V1–V8; decides APPROVED / APPROVED WITH WARNING / REJECTED /
RETRY / SKIPPED / MANUAL REVIEW; records the run in `pipeline_runs`; writes its JSON log; hands over a
manifest; and prunes operational detail at 90 days while keeping the audit row for 24 months.

**Known limitation.** Prefect 3.8.8 cannot run a flow on the development host — the client posts to
`/api/flows/` and receives 404, with both the ephemeral server and a dedicated one that answers
`/api/health` with 200. The flow is written and imports correctly; the CLI entry point is what is
demonstrated. Fixing that install is a deployment task, not an extraction one.

**On numbering:** issues and pull requests share one number sequence on GitHub. PR #2 consumed
number 2, which is why the issues list appears to skip it. Nothing is missing.

**On staging:** stage only the files that belong to the issue being addressed. Adding the whole
`pipeline/` directory sweeps in work that belongs to a later issue — which is how the
configuration module ended up inside the scaffold commit.
