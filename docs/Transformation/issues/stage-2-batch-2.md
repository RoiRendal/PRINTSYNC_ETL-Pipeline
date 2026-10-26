<!--
STAGE 2 — BATCH 2: three issues, ready to post.

Create them in this order; they should land as #61, #62 and #63 (the last issue was #59 and PR #60
was merged). Each block is one issue: post the TITLE line as the title, and everything below the ---
as the description.

One PR: #61 finds the handover and the window, #62 proves staging is the shape this code expects,
#63 proves staging still holds what the handover claims. Together they are the gate every later rule
runs behind.
-->

---

TITLE: [Transformation] Resolve the batch from the extraction handover

---

## Why

A batch is not a day. Stage 1 re-reads a three-day look-back on every run, so the staged rows for
`business_date = D` contain sales created on `D-3 … D` — and every one of those days has to be
rebuilt, because the whole reason a sale is re-read is that its day has changed.

Before a single rule can run, the stage has to know three things: which handover it is
transforming, which extraction run produced it, and how many days that run actually read.

## Task

- `psync_transform/handover.py` — `Handover`, `read_manifest`, `find_manifest`, `load_handover`,
  `HandoverError`.
  - Select by the manifest's own `business_date`, not by its filename: the name embeds the run key,
    and a filename is a label while the field is a fact.
  - No manifest for the date → error naming the directory and saying why Stage 1 writes none
    (only `APPROVED` / `APPROVED WITH WARNING` produce one).
  - Two manifests for the date → error listing both run ids and asking for `--parent-run`. Picking
    one automatically would publish a day from a batch nobody selected.
- `psync_transform/batch.py` — `Batch` (handover + `lookback_days`, with `window_start`,
  `window_end`, `batch_id`, `covers()`) and `resolve_batch(settings)`.
- `psync_transform/db.py` — `connect_target`, the one connection this stage opens.
- `config.py` — `HANDOVER_DIR`, with a relative path anchored to the **pipeline** directory rather
  than the working directory, so the batch's input does not depend on where a scheduler started it.
- `lookback_days` is **read** from the parent run's `pipeline_runs` row, not configured: two sources
  for one window is two chances to disagree about which days a batch covers.

## Done when

- [ ] `resolve_batch` on the 2026-10-17 handover yields `TRF_20261017_618f1325` and the window
      2026-10-14 → 2026-10-17 (three look-back days).
- [ ] No manifest for the date raises `HandoverError` naming the directory.
- [ ] Two manifests for one date raise `HandoverError` listing both run ids.
- [ ] A parent run with no run-level row, or no `lookback_days`, raises `HandoverError` instead of
      guessing a window.

## Depends on

#57, #58 — merged.

---

TITLE: [Transformation] Check the input contract (T1)

---

## Why

The staging table can be older than this code. Revision 1.4 of the extraction contract added
`stg_sales_transaction_items.name` through migration `002`, and a database that was never migrated
still holds seven staging tables — just not that column. Without this check the batch runs happily
and 93 % of the shop's revenue ends up with no product attached to it.

## Task

- `psync_transform/schema.py` — the input contract as data: seven staging tables, every column, and
  the type family each must have. The three control columns are declared once and prepended, so a
  table cannot quietly disagree with its neighbours about what `business_date` is.
- `psync_transform/validation/result.py` — `CheckResult`, the same shape as Stage 1's, so the two
  stages' verdicts read alike and section 10.1 can be applied without translating.
- `psync_transform/validation/t1.py` — `check_input_contract(settings, handover)`:
  - the handover's decision must be `APPROVED` or `APPROVED WITH WARNING`;
  - every column in the registry must exist, with its type family;
  - a column added to staging is **ignored** — every rule names the columns it uses, so an additive
    change cannot alter the output (doc §6.4).

## Done when

- [ ] On the 2026-10-17 handover, T1 passes: "7 staging tables match the input contract".
- [ ] A handover whose decision is `REJECTED` fails with `TRF_HANDOVER_NOT_APPROVED`.
- [ ] Dropping `stg_sales_transaction_items.name` makes T1 fail with `TRF_INPUT_COLUMN_MISSING`,
      naming that column — and re-adding it makes T1 pass again.
- [ ] A staging column with the wrong type family is reported with what it is and what was expected.

## Depends on

#61.

---

TITLE: [Transformation] Check the handover's counts (T2)

---

## Why

Every reconciliation in §7 balances against the handover's counts. If staging holds fewer rows than
the manifest claims — a truncated table, a manual `delete`, a run that died between writing its rows
and writing its record — the day is published short and every downstream check still passes,
because they all reconcile against a number that was never true.

## Task

- `psync_transform/validation/t2.py` — `check_handover_counts(settings, handover)`: for each source
  table, `count(*)` in its staging table for this `run_id` must equal the manifest's
  `rows_extracted`.
- A table the manifest does not mention is an **error, not a zero** — `Handover.rows_extracted`
  raises rather than defaulting, because "not reported" and "empty" are different facts.
- A table the manifest reports as empty must be empty here too: 0 = 0 passes, 0 = 4 does not.

## Done when

- [ ] On the 2026-10-17 handover, T2 passes: "all 7 staging tables hold the 16 rows the handover
      reports".
- [ ] A manifest claiming 99 payments against 4 staged rows fails with `TRF_STAGING_COUNT_MISMATCH`,
      naming the table and both numbers.
- [ ] A table reported as 0 rows passes when staging holds none.

## Depends on

#61, #62.
