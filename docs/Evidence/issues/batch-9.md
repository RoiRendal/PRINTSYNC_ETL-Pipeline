<!--
EVIDENCE — BATCH 9: two issues, ready to post.

Create them in this order; they should land as #120 and #121 (the last number used was PR #119).
Each block is one issue: post the TITLE line as the title, and everything below the --- as the
description.

One PR: two checks that were measuring the wrong thing, both found by running the pipeline against
the live PRINTSYNC data. Transformation revision 1.12 goes up first.
-->

---

TITLE: [Transformation] Scope the date boundary check to the batch's own rows

---

## Why

T13 counted every fact row **outside** the batch window. But the fact tables hold every night the
pipeline has ever published, so those rows are mostly other batches' — and a batch run more than
`LOOKBACK_DAYS` after the previous one was rejected for rows it never wrote.

Found on the live data: processing 2026-10-24 in a database that already held 2026-10-17 gave

```
fct_daily_sales: 1 row(s) outside the window
```

and a critical failure, so the batch's own facts were cleared. Nightly runs hide it, because each
window overlaps the last.

The facts carry no batch column — their grain is `(business_date, branch_key)`, because a published
day is the day, not the run that built it — so "rows outside the window" cannot be attributed to a
batch at all.

## Task

- Replace the whole-table scan with a comparison against the batch's own account of itself: for each
  fact table, the rows the builder **reported writing** must equal the rows present in the window. A
  row written to the wrong date makes those two disagree.
- Keep the dropped-date half, and add its converse: an output date inside the window with no input
  behind it is a date the batch invented.
- `check_business_date_boundary` takes `written: Mapping[str, int]`; `run_transformation` passes the
  fact builders' `rows_written`.
- State in §7 why the outside-window comparison is not made, so the next reader does not add it back.

## Done when

- [ ] The live 2026-10-24 batch, in a database that also holds 2026-10-17, passes T13.
- [ ] Deleting a fact row inside the window makes T13 fail, naming both the count mismatch and the
      dropped date.
- [ ] No fact table is scanned for rows outside the window.

## Depends on

Transformation revision 1.12.

---

TITLE: [Transformation] Accept a zero-rated sale as conformant

---

## Why

T6 required every completed sale's tax to equal the rate in force. But the rate is a **setting the
shop can change, and 0 is a legal value** — the default is 12. Two of the ten live sales on
2026-10-24 were recorded with no tax on a ₱250 sale, which is a zero-rating, not an error, and the
check warned about them.

The source records the tax but not the rate it was charged at, so a sale made under a different rate
cannot be told apart from a mistake. That is an argument for warning, not for treating a legal value
as a defect.

## Task

- A sale recorded with **zero tax** is conformant and is not counted as an exception. Count them
  separately and mention the number, so a reader knows they were seen and accepted.
- The failure condition stays: exceptions above 1 % of live sales.
- S-20 says a rate of 0 *or above 100* fails T6. That is wrong twice — 0 is legal, and above 100 is
  refused by `dim_branch.vat_rate`'s check constraint, not by T6. Correct it.
- §7's T6 row states the limitation: the rate a sale was charged at is not recorded, so this check
  warns rather than stops.

## Done when

- [ ] The live 2026-10-24 batch passes T6, with the two zero-rated sales named in the message.
- [ ] A sale whose tax is neither zero nor the rate in force still counts as an exception.
- [ ] S-20 no longer claims a rate of 0 fails the check.

## Depends on

#120.
