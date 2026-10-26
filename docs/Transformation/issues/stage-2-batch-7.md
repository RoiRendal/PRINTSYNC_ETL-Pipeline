<!--
STAGE 2 — BATCH 7: three issues, ready to post.

Create them in this order; they should land as #80, #81 and #82 (the last issue was #74 and PR #75
was merged). Each block is one issue: post the TITLE line as the title, and everything below the ---
as the description.

One PR: the last two facts, and the check that keeps their statuses honest.

**This batch also carries an extraction revision** — `orders.is_custom` is now extracted. See the
note at the end of this file.
-->

---

TITLE: [Transformation] Build the stock snapshot

---

## Why

The stock snapshot is deliberately its own fact, not a column of the demand fact (rule D10): demand
is rebuilt for the whole look-back because voids change it, but stock is a snapshot of the night the
batch ran — rebuilding an old date's stock with tonight's catalogue would destroy the record of what
was on the shelf then.

And the **catalogue drives the grain, not the sales**: an item that did not move is the one most
likely to need a reorder decision, so it cannot be missing from the table.

## Task

- `build_fct_daily_stock_snapshot(conn, batch, time_zone)` in `facts.py`.
- Grain: `business_date × branch × catalogue item` — every item in the branch's snapshot, for the
  **target date only** (rule A-07). The delete is for the target date, not the window.
- `stock_on_hand` and `reorder_level` come from the snapshot; `stock_status` from rule B-11
  (`critical` at zero, `warning` at or below the reorder level, `healthy` otherwise).
- `recommended_reorder` reads the 30-day projection from the demand fact — the most recent one this
  batch produced. An item that never sold has none, so the forecast is 0 and the recommendation is
  simply the shelf.
- The table's CHECK constraint states rule B-11's thresholds, so the word and the numbers cannot
  disagree.

## Done when

- [ ] A catalogue with two items, one at stock 3 against a reorder level of 10 and one at stock 0,
      writes two rows: `warning` and `critical`.
- [ ] The snapshot is written for the target date only; a look-back date is not touched.
- [ ] An item that never sold still gets a row.

## Depends on

#65–#70 — merged.

---

TITLE: [Transformation] Build the order-status fact

---

## Why

The order funnel is a monthly view, not a nightly one: on 2026-10-17 the order-status fact is
**empty**, because none of the 23 orders was raised that day (finding F-10 — the orders window
returns the whole table, and the cohort filter excludes all of them). That is the correct answer, and
the fact has to be able to produce it.

## Task

- `build_fct_daily_order_status(conn, batch, time_zone)` in `facts.py`.
- The cohort is orders **raised** on a business date (rule X-04), not orders touched on a day. Stage 1
  re-reads the whole orders table when `updated_at` moves, so the window without this filter would
  count February's orders as today's demand.
- Grain: `business_date × branch × status`, **densified** across all six statuses for every
  (date, branch) that has at least one order (rule A-05) — a funnel with a missing step reads as a
  broken funnel. A branch with no orders gets no rows, so "no orders" is never confused with
  "no data".
- `custom_order_count` counts `orders.is_custom` — which the extraction now provides (see the note
  at the end of this file).
- `avg_order_value` is NULL on a zero-order status, per rule S-03.
- Delete the window, then insert (rule C-09).
- A status the dimension does not know is quarantined (rule C-16) — the build cannot even resolve
  its key, which is the point of seeding the dimension rather than deriving it.

## Done when

- [ ] Two orders raised on the target date — one `Pending` at ₱3,200.00 and one `In Production` at
      ₱1,450.00 — produce **six** rows: the two statuses populated and the other four at zero.
- [ ] `custom_order_count` is 1 on the custom order and 0 on the other.
- [ ] `avg_order_value` is the order's value on a populated status and NULL on a zero one.
- [ ] A batch with no orders produces **zero** rows without error.

## Depends on

#65–#70 — merged.

---

TITLE: [Transformation] Check the status domain (T16)

---

## Why

A status the code map does not know cannot be classified as revenue or not. Guessing "probably
completed" is how a refund becomes income; inventing a seventh order status is how a funnel grows a
step nobody asked for.

## Task

- `psync_transform/validation/t16.py` — `check_status_domain(settings, batch)`, two domains kept
  apart:
  - every distinct `stg_orders.status` is a `status_name` in `dim_order_status` — the dimension is
    seeded, never derived, so a seventh value fails here instead of quietly becoming a row
    (rule M-04);
  - every distinct sale and payment status is in its documented two-value domain — the same
    run-time assertion Stage 1 keeps for V5 and V6, because the constraint is on the other side of
    the boundary and a migration could drop it without anyone being told.
- Critical severity.

## Done when

- [ ] PASS on a clean batch: "every order, sale and payment status is in its documented domain".
- [ ] An order status of `Cancelled` fails with `TRF_UNKNOWN_STATUS`, naming the status.
- [ ] The build refuses to resolve an unknown status, because it cannot map it to a key.

## Depends on

#81.
