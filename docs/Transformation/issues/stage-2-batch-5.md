<!--
STAGE 2 — BATCH 5: three issues, ready to post.

Create them in this order; they should land as #72, #73 and #74 (the last issue was #70 and PR #71
was merged). Each block is one issue: post the TITLE line as the title, and everything below the ---
as the description.

One PR, and the first fact: the daily sales fact, the quarantine that feeds it, and the two checks
that prove its records and its money.

**This batch also carries a documentation revision** — C-01 now quarantines the sale, not just the
line. See the note at the end of this file.
-->

---

TITLE: [Transformation] Build the daily sales fact

---

## Why

`fct_daily_sales` is the number a reader checks against the till. It is also the first place where
three rules have to hold at once: the money identities, the voided exclusion, and the cost-coverage
limit.

## Task

- Add `psync_transform/quarantine.py` — `quarantine(conn, batch, source_table=…, rule_id=…,
  reason=…, detail=…, condition=…)`. It writes the offending row itself as `to_jsonb`, because the
  staging rows are pruned at 90 days while the quarantine is kept for 24: the payload is the only
  copy that survives. Idempotent on `(batch_id, source_table, source_id, rule_id)`.
- Add `psync_transform/facts.py` — `build_fct_daily_sales(conn, batch, time_zone)`, returning a
  `FactBuild` with the dates written and per-table `SourceCounts` for T3.
- **Clean first, then use what is left.** Quarantine C-15 (unknown status), C-14 (the sale's money
  does not add up), C-01 (a sale with an unnamed line — see the doc revision), C-21 (no branch
  version on the sale's own date), C-13 (an impossible line) and C-17/S-13 (a bad payment). Every
  later statement excludes what was quarantined, so the quarantine is the single record of what did
  not make it.
- **Aggregate each grain separately.** Sale measures, line measures and payment measures each get
  their own temp table and are joined afterwards. Summing a sale column in the same `group by` as a
  line column multiplies the sale by its line count — the totals would look like a very good night.
- Both statuses are kept in the staging pass: a voided sale feeds `voided_count` and `voided_amount`
  (rule X-01), which is a measure, not a filter.
- Delete the **whole window** before inserting, not just the dates that produced rows (rule C-09), so
  a day that has become empty is emptied rather than left stale.
- Rule B-10: `gross_profit` and `margin_pct` stay NULL unless coverage is 100 %. A day with no
  revenue is vacuously 100 % costed and its profit is zero — true, and better than NULL meaning
  "we did not check".

## Done when

- [ ] A batch with two completed and two voided sales writes one row: `transaction_count = 2`,
      `gross_revenue = 20.00`, `voided_count = 2`, `voided_amount = 20.00`, `settled_total = 20.00`.
- [ ] `cogs_coverage_pct = 0` (no cost is known) and `gross_profit` and `margin_pct` are **NULL**.
- [ ] Clearing one line's product name quarantines its whole sale under C-01, and the day's
      `transaction_count` drops by one.
- [ ] Rebuilding the same batch produces the same row, not a second one.

## Depends on

#65, #66, #69 — merged.

---

TITLE: [Transformation] Check the record reconciliation (T3)

---

## Why

The batch's own numbers — what it read, what it rejected — are what the run record carries and what
the reject-rate threshold in §10.1 is applied to. If the build skipped a table, or quarantined a row
without recording it, every decision downstream would rest on a figure that was never true.

## Task

- Add `psync_transform/validation/t3.py` — `check_record_reconciliation(settings, batch, counts)`.
- It does **not** trust the report: it recounts the staging rows and the quarantine rows itself and
  compares against what the build said.
- A table that carries quarantined rows but was never reported is a failure — that is a quarantine
  nobody accounted for.
- Critical severity.

## Done when

- [ ] PASS on a clean batch: "3 source table(s) reconcile".
- [ ] A quarantine row inserted against an unreported table fails with
      `TRF_RECORD_RECONCILIATION`, naming the table.

## Depends on

#72.

---

TITLE: [Transformation] Check the line-to-header identity (T5)

---

## Why

The header is authoritative for revenue, and the payments prove it. The **lines** are the
approximation — they are what the product fact is built from. If the two ever disagree, the daily
fact and the product fact are describing different money.

The profile measured this holding on **867 of 867 sales** (§2.3), which is what makes it worth
checking: a rule that always passes is only useful when it starts failing.

## Task

- Add `psync_transform/validation/t5.py` — `check_line_to_header_identity(settings, batch)`.
- Per business date: `Σ (quantity × unit_price)` over live lines equals `Σ subtotal` over live sales.
  Both sides exclude quarantined sales; the line side also excludes quarantined lines.
- Tolerance of half a cent: the columns are `numeric(14,2)`, so anything larger is a real
  disagreement rather than rounding.
- Critical severity.
- This is the check the schema cannot express — `fct_daily_sales` enforces its own internal
  arithmetic with CHECK constraints, but nothing in the database knows that a day's line revenue
  should equal its header subtotal.

## Done when

- [ ] PASS on a clean batch.
- [ ] Changing one line's `unit_price` so it no longer matches the header fails with
      `TRF_LINE_HEADER_IDENTITY`, naming the date and both amounts.

## Depends on

#72.

---

## Documentation revision in this batch

`C-01` now reads **"quarantine the sale that contains the line"**, not "quarantine the line"
(transformation document, revision 1.3). Found while building the fact: rejecting only the line
would leave its money in `fct_daily_sales` through the header and take it out of
`fct_daily_product_demand`, so the two facts would disagree about the same revenue — precisely the
failure T12 exists to catch. The rule's own justification already said the revenue should be
rejected; only the action was under-specified.

Lyell publishes revision 1.3 before the code lands.
