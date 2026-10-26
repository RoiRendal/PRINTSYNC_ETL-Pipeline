<!--
STAGE 2 — BATCH 6: two issues, ready to post.

Create them in this order; they should land as #76 and #77 (the last issue was #74 and PR #75 was
merged). Each block is one issue: post the TITLE line as the title, and everything below the --- as
the description.

One PR: the product demand fact — where 93.4 % of the shop's revenue is finally attributed to a
product — and the cross-fact reconciliation that proves the two facts describe the same money.
-->

---

TITLE: [Transformation] Build the product demand fact

---

## Why

`fct_daily_product_demand` is where 93.4 % of the shop's revenue is finally attributed to a product.
The daily sales fact says how much was taken; this fact says what it was, and it is built from the
same lines, cleaned by the same rules.

## Task

- **Refactor `facts.py` first**: pull the cleaning rules and the staging pass into a private
  `_stage(conn, batch, time_zone)`. Both facts call it. This is not tidiness — the daily fact is
  header-driven and the product fact is line-driven, and if they ran their own cleaning rules, one
  could exclude a row the other kept. That is exactly the disagreement T12 would catch a fact later.
- `build_fct_daily_product_demand(conn, batch, time_zone, demand_window_days)`.
- **Not densified** (rule A-04): one row per business date × branch × item that *sold*. A zero row
  would be indistinguishable from a day the batch never processed, and the unsold items a reorder
  decision needs live in the stock snapshot, which is where stock belongs.
- Measures (rule B-04): `line_revenue = Σ quantity × unit_price`; `revenue = line_revenue −
  discount_total`; `cogs = Σ quantity × unit_cost` when the cost is known; `is_costed` says which.
  The table refuses `revenue <> line_revenue − discount_total` by CHECK, so the two cannot drift.
- **Not densified means not reconcilable by rows** — this fact is reconciled by measures (T12).
- Only live lines (rule X-03): a voided sale's lines feed nothing here.
- Delete the window, then insert (rule C-09), like every other fact.

## Done when

- [ ] Two sale lines with two different products produce two demand rows whose `revenue` sums to the
      daily fact's `net_revenue` plus its `unallocated_discount`.
- [ ] `is_costed` is false on every product, because no cost is known in this data — and `cogs` is 0.
- [ ] The two facts see the same lines, even after one sale is quarantined under C-01.

## Depends on

#72 — merged.

---

TITLE: [Transformation] Add the trailing demand average

---

## Why

A demand average needs history that lives **outside** this batch's window: the rows written by
earlier nights. So it cannot be computed in the same statement that writes the batch's rows — the
window is deleted before it is written, and the average is taken after the fact stands.

It also has a denominator to decide, and getting it wrong is the difference between a forecast and a
shop that runs out of stock.

## Task

- Two steps inside one transaction: the insert writes the measures with placeholder averages; one
  `UPDATE` then fills `demand_window_days`, `avg_daily_demand` and `forecast_demand_30d` by reading
  the fact as it now stands — the new rows plus whatever earlier batches wrote. The placeholders are
  never visible outside the transaction.
- **The denominator is the branch's trading days in the window, counted from `fct_daily_sales`** —
  not the days this product sold. A product that moved ten units on one day of seven would otherwise
  average ten a day and run the shelf empty on a forecast built from it.
- `demand_window_days` records that denominator, so thin history is visible rather than folded into
  a number (rule B-13).
- `forecast_demand_30d = 30 × avg_daily_demand` — Lab 2's stated placeholder for a model that does
  not exist yet, and labelled as a straight-line projection, not a prediction.

## Done when

- [ ] Two products each selling one unit on the only trading day known produce
      `demand_window_days = 1`, `avg_daily_demand = 1.00`, `forecast_demand_30d = 30.00` — and the
      `1` is honest: the pipeline has seen one trading day.
- [ ] The denominator comes from `fct_daily_sales`, so a product that did not sell on a trading day
      still divides by it.
- [ ] A product whose attributes did not change gets the same values on a rebuild, not a new version.

## Depends on

#76 — same module.

---

TITLE: [Transformation] Reconcile the facts against each other (T12)

---

## Why

The product fact is built from lines and the sales fact from headers. If the two ever disagree about
the same revenue, one of them is describing money the shop did not make — and no single-fact check
can see it, because each is internally consistent.

## Task

- Add `psync_transform/validation/t12.py` — `check_fact_reconciliation(settings, batch)`, per
  business date:
  - `Σ fct_daily_product_demand.revenue` equals `Σ fct_daily_sales.net_revenue` plus
    `Σ fct_daily_sales.unallocated_discount`;
  - `Σ fct_daily_product_demand.quantity_sold` equals `Σ fct_daily_sales.units_sold`.
- The first is the one that carries the whole design. The product fact attributes revenue to products
  by the name on the line; the sales fact takes it from the header. They reconcile only because
  `Σ (quantity × unit_price)` equals `Σ subtotal` (check T5) and the discount difference is published
  as `unallocated_discount` rather than invented on the lines.
- Critical severity. The order and stock equations arrive with their facts; this check grows with
  them rather than being rewritten.

## Done when

- [ ] PASS on a clean build: "1 business date(s) reconcile".
- [ ] A demand row that claims five pesos more than the daily fact fails with
      `TRF_FACT_RECONCILIATION`, naming the date and both amounts.
- [ ] Both directions: a date present in one fact and missing from the other is a failure, not a
      silent zero.

## Depends on

#76 — same module.
