<!--
STAGE 2 — BATCH 8: three issues, ready to post.

Create them in this order; they should land as #86, #87 and #88 (the last issue was #78 and PR #79
was merged). Each block is one issue: post the TITLE line as the title, and everything below the ---
as the description.

One PR: the remaining checks of §7. After this batch, every check in the transformation document's
table is implemented.
-->

---

TITLE: [Transformation] Check the money (T4, T10, T11)

---

## Why

`fct_daily_sales` is the number a reader checks against the till. Its internal arithmetic is enforced
by CHECK constraints, its business rules by more of them, and its cost coverage is the one measure
that must never be read without its qualifier — but a dropped constraint would let a broken row
through, and a thin coverage would be read as a whole-day profit unless something says otherwise.

## Task

- Add `psync_transform/validation/t_money.py`, three checks:
  - **T4** (critical): the four money identities of §6.1 hold on the stored rows —
    `gross_revenue = net_revenue + tax_total`, `net_revenue = line_revenue_total −
    line_discount_total − unallocated_discount`, `unallocated_discount = discount_total −
    line_discount_total`, `settled_total = cash_total + card_total + custom_order_total`.
  - **T10** (warning): `cogs_coverage_pct` recorded every batch; below 95 % warns, below 50 % warns
    harder. Never a stop — the catalogue is what it is, and refusing to publish the day's revenue
    over it would punish the wrong party.
  - **T11** (critical): the business rules per fact — no negative revenue or units, `margin_pct`
    within −1000…100, `settled_total` within 1 % of `gross_revenue`, no negative quantity or stock.

## Done when

- [ ] On a clean batch: T4, T10 and T11 all PASS.
- [ ] A batch with no cost known anywhere produces `cogs_coverage_pct = 0.00` and T10 warns with the
      coverage figure — and `gross_profit` stays NULL.
- [ ] Breaking a money identity and dropping its CHECK constraint makes T4 fail with
      `TRF_MONEY_IDENTITY`.

## Depends on

#72 — merged.

---

TITLE: [Transformation] Check the structure of the output (T7, T8, T9)

---

## Why

Three assertions about the structure of the published output — that rows are unique, that every
dimension key resolves, and that the columns the contract declares required hold values. The schema
enforces most of this with primary keys, foreign keys and NOT NULL columns; the checks are run-time
assertions that those constraints are still there, in the same spirit as Stage 1's V5 and V6. A table
rebuilt without its keys would accept duplicates silently, and an over-count never announces itself.

## Task

- Add `psync_transform/validation/t_integrity.py`, three checks:
  - **T7** (critical): no duplicate grain keys across the four facts and the two versioned dimensions.
  - **T8** (critical): every fact row resolves its dimension keys — no orphans.
  - **T9** (critical): no required column is empty, across all seven output tables. The window
    applies to the facts; `dim_date`, `dim_branch` and `dim_item` are checked in full, because every
    row they hold is this stage's output.

## Done when

- [ ] On a clean batch: T7, T8 and T9 all PASS.
- [ ] Nulling a fact's `item_key` (after dropping its foreign key) makes T9 fail, naming the table.

## Depends on

#72 — merged.

---

TITLE: [Transformation] Check the boundaries (T6, T13, T14)

---

## Why

Three questions from three directions: is this batch writing the dates it claims to be writing, is
what it wrote worth reading, and does the source's own arithmetic hold.

They differ in severity, and the difference is doing real work:

- **T6** (warning): VAT conformance is the shop's data problem, not the pipeline's. The recorded tax
  is never recomputed — that would invent a number the customer never paid and break the
  reconciliation to payments. The check counts and warns.
- **T13** (critical): a row landed outside the batch window, or an input date produced no output.
  Stop.
- **T14** (warning): a silent zero is usually a broken rule, not a quiet day.

## Task

- Add `psync_transform/validation/t_boundary.py`, three checks:
  - **T6**: per live sale, `tax = round2(vat_rate/100 × (subtotal − discount))`, the rate read from
    the branch version in force on the sale's own date. Above 1 % of live sales fails; any exception
    warns.
  - **T13**: no output row outside the window, and no input date without output — both directions,
    because a date the batch dropped is as wrong as a date it invented.
  - **T14**: the target date has rows in `fct_daily_sales` and `fct_daily_stock_snapshot`.

## Done when

- [ ] On a clean batch: T6, T13 and T14 all PASS.
- [ ] The batch's VAT under-collection (2 of 2 live sales, tax ₱0.00 on ₱10.00) fails T6 with
      `TRF_VAT_MISMATCH` — above the 1 % threshold, so the day needs a look.
- [ ] Moving a fact row outside the window fails T13, naming the count.

## Depends on

#72 — merged.
