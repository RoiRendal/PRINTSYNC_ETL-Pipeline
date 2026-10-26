# Implementation Plan & Issue Breakdown — Transformation Phase (Stage 2)

**Pipeline:** `psync_nightly_analytics` · Stage 2 of 3 (Extract → Transform → Load)
**Source of truth:** [`Data-Transformation-Documentation-for-PRINTSYNC.md`](Data-Transformation-Documentation-for-PRINTSYNC.md)
**Repo:** https://github.com/RoiRendal/PRINTSYNC_ETL-Pipeline
**Team:** Issuer — Ma. Erica Z. Vidal · Documentator — Lyell Jasmine D. Bulan · Coder — Roi C. Rendal
**Plan date:** 26 October 2026
**Status:** transformation stage complete 26 October 2026 — **all 10 batches delivered, 24 issues
closed across 10 merged pull requests**

---

## 1. What this plan is

The transformation stage was built **batch by batch**. The specification is the contract; each batch
took the next slice of it, built it against the development database, demonstrated it with real
output, and shipped it as one pull request closing two or three issues.

This document records how the work was batched, what each batch delivered and what its evidence was,
so that the issue history reads as a plan rather than a sequence. It also records the three input
gaps the work uncovered — two of which required revisions to the extraction contract.

**The batches are in the order §1.4 of the specification prescribes**, and each batch depended on the
one before it: the foundation, then the input gate, then the dimensions, then the facts, then the
checks, then the recording, then the orchestration.

---

## 2. Ground rules

| # | Rule |
| --- | --- |
| G1 | **The documentation is the contract.** Code follows the document, never the reverse. When the contract had to change, the document was corrected first — three times during this stage (revisions 1.1–1.3 of the transformation document, and revisions 1.4–1.5 of the extraction document). |
| G2 | **PRINTSYNC stays untouched.** The pipeline reads over a read-only login and writes only to `psync_analytics`. |
| G3 | **One issue → one change.** A commit/PR references its issue (`Closes #N`). No issue, no code. |
| G4 | **Fail loudly, never guess** (§6.4). A missing column, a changed type, an unresolvable key → stop the batch; never substitute a default. |
| G5 | **Nothing is cleaned silently.** Every row is retained or quarantined, with the rule that caught it and the batch that rejected it (§3). |
| G6 | **Documentation references are mandatory.** Every issue cites the document sections it implements. |
| G7 | **No automated tests.** The professor asked for the tests to be skipped, so each batch is evidenced by real output — a query, a run log, or a command's result — pasted into the pull request. The pipeline's own checks (T1–T17) are its verification mechanism. |

---

## 3. Workflow

```
Issue opened (task instruction)
   └─ branch:  issue-<N>-<short-slug>
        └─ commits: feat(transform): ... (references #N)
             └─ PR into main, body = "Closes #N" + evidence (query / run log / command result)
                  └─ issue closed → next issue unblocked
```

- **Branch naming:** `issue-<N>-<short-slug>`, one branch per pull request (2–4 issues each).
- **PR evidence:** for check issues, the check's own output; for build issues, a query against the
  published rows. Every number quoted in a pull request came from the development database.
- **Issue format:** *Why → Task → Done when → Depends on*, kept short. Detail belongs in the code
  and the document.
- **Definition of done:** acceptance criteria checked, the change demonstrated with real output, the
  document section verified, PR merged.

**Where the issue texts live.** `docs/Transformation/issues/stage-2-batch-<N>.md` holds each batch's
issue texts in posting order. (The Stage 1 issue texts in `docs/Extraction/…` are a local working
set and are deliberately not published; the Stage 2 texts are.)

---

## 4. The batches

Ten batches, in §1.4's order. "Evidence" names the demonstration pasted into the pull request.

### Batch 1 — Foundation (issues #57–#59, PR #60)

The `psync_transform` package, its configuration, and the eleven-table schema of §6.1 (migration
`003_transformation_schema.sql`). Evidence: the migration applied, `dim_order_status` seeded with six
statuses, and the schema refusing a self-contradictory money row.

### Batch 2 — The input gate (issues #61–#63, PR #64)

`handover.py` (the manifest, selected by its own `business_date` rather than its filename),
`batch.py` (the window, with `lookback_days` read from the parent run rather than configured),
`db.py`, and checks **T1** and **T2**. Evidence: the batch resolved from the real 2026-10-17 handover
(`TRF_20261017_618f1325`), T1 and T2 passing, and both failing on tampered input.

### Batch 3 — The first dimensions (issues #65–#67, PR #68)

`dim_date` generated for the window plus the demand look-back, `dim_branch` as the first SCD Type 2
build, and **T15** to prove the versions hold. Evidence: a rename closing the old version and opening
a new one, T15 passing, and T15 failing on a forced overlap.

### Batch 4 — The item dimension (issues #69–#70, PR #71)

`dim_item` — the dimension that exists because 93.4 % of sale lines have no catalogue link. Products
are identified by `item_ref = 'name:' || normalised(name)`, fed by two sources that meet on one key,
with **T17** guarding the derived identity. Evidence: a sold name that later appears in the catalogue
closing its name-only version, a catalogue item that never sold still getting a row, and T17 failing
on a drifted key.

### Batch 5 — The daily sales fact (issues #72–#74, PR #75)

`quarantine.py` (the writer), `facts.py` (`build_fct_daily_sales`), and checks **T3** and **T5**.
Evidence: one published row for a day with two completed and two voided sales — coverage 0 %,
`gross_profit` NULL — and both checks failing when the data was made to disagree.

**This batch carried transformation-document revision 1.3**: C-01 now quarantines the sale, not just
the offending line, because rejecting only the line would leave its money in the daily fact and take
it out of the product fact.

### Batch 6 — The product demand fact (issues #76–#78, PR #79)

`_stage()` extracted so both facts share one cleaning pass, `build_fct_daily_product_demand`, and
**T12** — the cross-fact reconciliation that the whole two-fact design exists to make possible.
Evidence: the product fact reconciling to the daily fact's `net_revenue` plus its
`unallocated_discount`, and failing when a demand row claimed five pesos more.

### Batch 7 — The last two facts (issues #80–#82, PR #85)

`build_fct_daily_stock_snapshot` (the target date only, per rule D10) and
`build_fct_daily_order_status` (the cohort of orders *raised* that day, densified across all six
statuses), plus **T16**. Evidence: two stock rows (`warning` and `critical`), six densified funnel
rows for two orders, T16 passing and failing on an unknown status.

**This batch carried extraction-document revision 1.5** (PR #84, issue #83): `orders.is_custom` was
not in the extraction scope, so `custom_order_count` had no source — the second input gap found by
checking Stage 2's inputs against what the extraction takes.

### Batch 8 — The check set completed (issues #86–#88, PR #89)

The remaining checks of §7, in three modules grouped by concern: `t_money.py` (**T4**, **T10**,
**T11**), `t_integrity.py` (**T7**, **T8**, **T9**), `t_boundary.py` (**T6**, **T13**, **T14**).
Evidence: all nine run over a fully built batch — including the documented T6 failure (the VAT
under-collection) and the T10 warning (0 % coverage).

### Batch 9 — Recording, deciding, logging (issues #90–#92, PR #93)

`runs.py` (the ledger, replace-before-write), `decisions.py` (§10.1's table in precedence order),
`runlog.py` (the batch's JSON log, written atomically). Evidence: a recorded batch — run-level row
`read 28 / output 10 / rejected 0 / modified 0`, eight per-table rows, rule counts — and
`transformation_runs` cleaned afterwards so the orchestrator started from a clean ledger.

### Batch 10 — The orchestrator (issues #94–#96, PR #97)

`pipeline.py` (`run_transformation`), `__main__.py` (the CLI), `flow.py` (the Prefect flow). Evidence:
`python -m psync_transform --date 2026-10-17` running the whole stage — APPROVED WITH WARNING, all
seventeen checks, the published row, the eight-row ledger and the log.

**This batch caught two bugs no individual batch could see:**

1. **The run-level totals double-counted.** The daily fact and the product fact read the same source
   rows independently; summing their reads gave 20 instead of 12. Fixed: the run-level totals count
   each source table once.
2. **The quarantine was an accumulation, not a recomputation.** A batch re-run after a fix still
   carried the previous run's rejections. Fixed: `_stage` clears the batch's quarantine rows before
   re-deriving them.

---

## 5. The input gaps this stage uncovered

Three times, building a rule against the staged data revealed that the extraction contract did not
carry a column the rule needed. Each time, the document was corrected first, then the code, then the
database:

| # | Column | Rule that needed it | Extraction revision | Migration |
| --- | --- | --- | --- | --- |
| 1 | `sales_transaction_items.name` | C-02, B-02 — the product identity (93.4 % of lines have no catalogue link) | 1.4 | `002_stg_item_name.sql` |
| 2 | `orders.is_custom` | B-14 — `custom_order_count` | 1.5 | `004_stg_order_custom.sql` |

The third gap was not a missing column but an under-specified action: C-01 said "quarantine the
line", which would have left its money in the daily fact and removed it from the product fact.
Transformation revision 1.3 corrected the action to "quarantine the sale".

**The practice worth keeping:** profile Stage 2's *inputs* against Stage 2's *rules*, not either
document on its own. Two documents that are each internally consistent can still disagree at the
boundary between them.

---

## 6. What the stage delivered

| Object | Count | Notes |
| --- | --- | --- |
| Dimensions | 4 | `dim_date` (generated), `dim_branch` and `dim_item` (SCD Type 2), `dim_order_status` (seeded) |
| Facts | 4 | `fct_daily_sales`, `fct_daily_product_demand`, `fct_daily_stock_snapshot`, `fct_daily_order_status` |
| Cleaning rules | 21 | `C-01`–`C-21` |
| Standardisation rules | 20 | `S-01`–`S-20` |
| Business rules | 16 | `B-01`–`B-16` |
| Modelling / join / exclusion / aggregation rules | 21 | `M-01`–`M-07`, `J-01`–`J-08`, `X-01`–`X-05`, `A-01`–`A-07` |
| Validation checks | 17 | `T1`–`T17`, all implemented |
| Migrations | 3 | `002`, `003`, `004` (after Stage 1's `001`) |
| Merged pull requests | 10 | #60, #64, #68, #71, #75, #79, #85, #89, #93, #97 |
| Closed issues | 24 | #54–#55, #57–#59, #61–#63, #65–#67, #69–#70, #72–#74, #76–#78, #80–#82, #86–#88, #90–#92, #94–#96, #83 |

---

## 7. What comes next

**Stage 3 (Load)** — publishing the facts and dimensions into whatever the dashboard reads, with the
indexing and partitioning decisions §7 of the transformation document explicitly leaves to the Load
stage. Out of scope for the current laboratory.

Two smaller follow-ups, optional:

1. The extraction stage's README section still describes the pipeline as two packages without saying
   that both are runnable — one sentence.
2. The transformation document's §10.1 wording ("the previous output stands") describes Stage 1's
   rule carried over; Stage 2's actual behaviour on a rejected batch is that the affected dates are
   **cleared**, which is stronger and safer. One sentence in §10.1 would make the document match the
   code.
