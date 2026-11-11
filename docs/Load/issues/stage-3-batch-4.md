<!--
STAGE 3 — BATCH 4: two issues, ready to post.

Create them in this order; they should land as #132 and #133 (PR #131 was merged). Each block below
is one issue: post the TITLE line as the title, and everything below the --- as the description.

One PR. Load specification revision 1.3 goes up first: facts are staged so a rejected row can be
recorded instead of aborting the batch.
-->

---

TITLE: [Load] Record rows the load refuses instead of aborting the batch

---

## Why

A `COPY` straight into `fct_daily_sales` fails the whole statement on the first row whose foreign
key does not resolve. That is the wrong behaviour twice over: one orphan takes down a day that is
otherwise fine, and `load_rejects` can never hold anything — so L7 has nothing to reconcile and L13
has nothing to count, while §5 asks for exactly those.

## Task

- Facts stage into a temporary table first, shaped like the target, and are dropped at commit.
- Two statements follow, sharing one predicate so they cannot disagree about what "orphan" means:
  - the rows that **do not** resolve their foreign keys are written to `load_rejects` with
    `batch_id`, `table_name`, rule `L-10`, a reason, and `to_jsonb(s)` as the payload;
  - the rows that **do** resolve are inserted into the target after the window delete.
- The predicate is one string per fact table, written over the stage alias, covering `dim_date`,
  `dim_branch`, `dim_item` and `dim_order_status` as each table requires.
- Dimensions keep their existing stage-and-upsert path: `COPY` cannot upsert, and a dimension row
  cannot orphan a fact, so nothing is rejected there.
- `load_batch` returns a per-table record — `received`, `inserted`, `rejected` — rather than a bare
  count, so L7 has the three numbers it reconciles.

## Done when

- [ ] A clean load records 150 received, 150 inserted, 0 rejected, and `load_rejects` is empty.
- [ ] A fact row whose branch key is absent from the warehouse lands in `load_rejects` with rule
      `L-10` and does **not** stop the batch.
- [ ] The three numbers per table add up.

## Depends on

#129, #130 — merged.

---

TITLE: [Load] Add the L7–L13 post-load checks

---

## Why

§5 requires the warehouse to be verified after the rows are written and **before** they are
committed, so a critical failure rolls the batch back instead of reporting a problem that is already
published. Without these, a load can succeed while quietly losing rows or altering an amount.

## Task

- Add `psync_load/validation/postload.py` with `run_post_load_checks(source, target, handover,
  loads)`, run inside the open transaction:
  - **L7** reconciliation — `received = inserted + rejected` per table.
  - **L8** row count — each table holds what the handover expected: `records_output` for a fact, the
    staged count for a dimension (§1.1).
  - **L9** key uniqueness — `count(*) − count(distinct pk) = 0` on every table.
  - **L10** referential integrity — no orphan fact; the same predicate the reject path uses.
  - **L11** required columns — no null in a `NOT NULL` column, read from `information_schema`.
  - **L12** amounts — every reconciled money column sums to the same figure on both sides, to the
    cent.
  - **L13** rejects — none is a pass; within 1 % warns; above 1 % fails. Severity stays *warning*, so
    it drives `MANUAL REVIEW` rather than a rejection (§8.1).
- `load_batch` takes an optional validator and calls it before `COMMIT`; a critical failure rolls
  back and returns `committed=False`.
- The CLI prints `post-load L7=PASS … L13=PASS` and exits 1 when the batch was rolled back.
- Move `CheckResult` to `psync_load/checks.py`: the loader needs it, and importing it through
  `psync_load.validation` created a circular import.

## Done when

- [ ] The live batch passes all seven.
- [ ] A doctored handover count fails L8 naming the table and both numbers.
- [ ] An amount altered in the warehouse fails L12 naming the column and both sums.
- [ ] Rejects at 0.67 % warn and at 20 % fail, both without stopping the other checks.
- [ ] A critical failure leaves zero rows published.

## Depends on

#132.
