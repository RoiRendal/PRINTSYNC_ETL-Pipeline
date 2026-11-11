<!--
STAGE 3 — BATCH 2: two issues, ready to post.

Create them in this order; they should land as #126 and #127 (PR #125 was merged, so numbering
continues from there). Each block below is one issue: post the TITLE line as the title, and
everything below the --- as the description.

One PR. The load specification revision 1.1 goes up first: it corrects the role table, the
`load_status` spelling, and what `records_output` means for a dimension — all three found while
verifying batch 1 and running the gate against the live batch.
-->

---

TITLE: [Load] Read the transformation handover as the load's input contract

---

## Why

Before a single row is loaded, the stage needs to know which batch it is loading, what window it
covers, whether that batch was approved, and how many rows each table produced. Stage 2 writes **no
manifest file** — Transformation §10.3 and revision 1.10 are explicit about that — so the handover
is the run-level `transformation_runs` ledger row keyed by `batch_id`, plus the per-table rows that
carry `records_output` (§1.1 of the load specification).

Stage 3 must not re-derive any of this from the mart tables by guessing a window.

## Task

- Add `psync_load/handover.py`: a frozen `Handover` dataclass, `HandoverError`, and
  `load_handover(settings)`.
- Fields: `batch_id`, `run_id`, `business_date`, `window_start`, `window_end`, `decision`, `status`,
  `code_version`, and `counts: dict[str, int]` keyed by the eight target table names.
- Query the run-level row (`table_name IS NULL`) for `settings.batch_id`, most recent first, then
  the per-table rows. Refuse a missing or malformed batch with a message naming the `batch_id`.
- **Do not** reject an unapproved batch here. Approval is L3's job (§4); the reader's job is to
  report exactly what the ledger says, so a failed check can name the decision it found.
- The source connection sets `default_transaction_read_only = on` and never issues DML.
- The CLI keeps `--batch`; it now resolves the handover and prints the window, decision, version
  and per-table counts. The loader itself arrives in batch 3.

## Done when

- [ ] `python -m psync_load --batch TRF_20261024_d031cb6c` prints window `2026-10-21 …
      2026-10-24`, decision `APPROVED`, and 150 rows across eight tables.
- [ ] An unknown `batch_id` fails with a message naming it, before any connection to the warehouse.
- [ ] No statement issued by this module writes to the Stage 2 database.

## Depends on

#123, #124 — merged.

---

TITLE: [Load] Add the L1–L6 pre-load validation checks

---

## Why

§4 of the specification requires six checks **before** the target transaction opens, each with a
name, a target, a purpose, a measurable criterion and a severity. All six are critical: a failure
stops the batch with no writes. Without them a load could publish an unapproved batch, a batch whose
counts have changed since the handover, or a batch that was already published.

## Task

- Add `psync_load/validation/result.py` with `CheckResult` (id, status, severity, message,
  error_code, `is_critical_failure`) — the same shape Stages 1 and 2 use, so the verdicts read alike.
- Add `psync_load/validation/preload.py` with
  `run_pre_load_checks(settings, handover) -> dict[str, CheckResult]`, L1–L6:
  - **L1** connection and write permission: `has_table_privilege` reports SELECT / INSERT /
    UPDATE / DELETE on the eight reporting and three bookkeeping tables for the current role.
  - **L2** schema match: compare `information_schema.columns` between the source and the warehouse
    for all eight tables — same column names, same `data_type` — and require the three `load_*`
    columns on the target. **No hardcoded registry**: one generated from the migration would be a
    second thing to keep in step.
  - **L3** handover status: `decision IN ('APPROVED', 'APPROVED WITH WARNING')` and
    `status = 'success'`.
  - **L4** input counts: for each of the four **fact** tables, count the rows in the window in the
    Stage 2 database and compare to `records_output`. Dimensions are deliberately not compared —
    their `records_output` counts the rows that run inserted, which is `0` for `dim_date` on a
    re-run and absent for the seeded `dim_order_status`, not the number of rows to load (§1.1) —
    and L8 reconciles them after the load. A mismatch is not repaired.
  - **L5** storage: free space on the evidence folder ≥ 100 MB and ≥ 3 × the source tables'
    `pg_total_relation_size`.
  - **L6** duplicate batch: no run-level `load_runs` row with this `batch_id` and
    `load_status = 'success'`. A prior `failed` row is allowed.
- Wire `__main__.py` to run them in id order and print `L1=PASS … L6=PASS`, then stop — the loader
  comes in batch 3. Return 1 if any critical check fails.
- Record the results in `load_validation_results` only once a run exists; batch 5 does that. For
  now the checks are pure reads.

## Done when

- [ ] The live batch passes all six.
- [ ] A doctored `records_output` makes L4 fail with a message naming the table and both counts.
- [ ] A `success` row for the same `batch_id` makes L6 fail (seed it inside a transaction that is
      rolled back).
- [ ] A dropped column on one warehouse table makes L2 fail.
- [ ] No check writes anything.

## Depends on

#126.
