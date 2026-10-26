<!--
STAGE 2 — BATCH 4: two issues, ready to post.

Create them in this order; they should land as #69 and #70 (the last issue was #67 and PR #68 was
merged). Each block is one issue: post the TITLE line as the title, and everything below the --- as
the description.

One PR. This is the dimension that exists because of what the data actually looks like: 93.4 % of
sale lines have no catalogue link, so a product's identity is its name.
-->

---

TITLE: [Transformation] Build the item dimension from names and the catalogue

---

## Why

`sales_transaction_items.inventory_item_id` is null on **93.4 % of sale lines** (finding F-01) — the
shop sells print services that were never added to the 15-row catalogue. A product dimension keyed on
the catalogue would cover a fourteenth of the revenue, so the identity is the name printed on the
line (rule S-12) and the catalogue link becomes an attribute.

Two sources feed one natural key, `item_ref = 'name:' || normalised(name)`:

- the **catalogue snapshot** — every item, sold or not, because `fct_daily_stock_snapshot` needs a
  row for the products that did *not* sell;
- the **distinct product names** on this batch's sale lines — 93.4 % of the revenue.

Where both exist they are one product, and the catalogue wins: its attributes are richer, and a
name-only product has nothing but a name.

## Task

- `build_dim_item(conn, batch)` in `psync_transform/dimensions.py`.
- Normalise once, in SQL: trim, collapse internal whitespace, lower-case for the key; keep the
  original case in `item_name`. When the same product is spelled with different casing on different
  lines, one identity results and the display name is the alphabetically first spelling —
  deterministic, which "whichever row arrived first" is not.
- Rule C-04: a blank or missing category becomes `Uncategorised`. Rule C-05: an unknown cost stays
  **NULL**, never 0. Rule S-11: `sku` upper-cased. Rule S-18: `uom` lower-cased, blank becomes NULL.
- SCD Type 2, mirroring `build_dim_branch`: whole-row comparison, same-day version refreshed in
  place, `valid_from` inclusive / `valid_to` exclusive. If you change one build, change the other —
  T15 checks both with the same rule.
- A sale line with a blank name is **excluded from the dimension** but not dropped: rule C-01
  quarantines it when the facts are built, so the revenue stays visible as rejected.
- Two catalogue rows that normalise to the same name raise `DimensionError` naming both. The item
  dimension has no branch column (doc §6.1), so it cannot hold two branches' versions of one product,
  and picking one would put another branch's cost price on this branch's demand.

## Done when

- [ ] Lines with a name but no catalogue row produce products with `category = 'Uncategorised'`,
      `unit_cost` NULL and `is_catalogue_item = false`.
- [ ] A sold name that later appears in the catalogue closes the name-only version and opens a
      catalogued one (`valid_to` on the old, `sku`/`price`/`cost` on the new).
- [ ] A catalogue item that never sold still gets a dimension row.
- [ ] `sku` is upper-cased and a blank `uom` becomes NULL.
- [ ] Two catalogue rows normalising to one name raise `DimensionError` naming both source ids.

## Depends on

#65, #66 — merged.

---

TITLE: [Transformation] Check the product identity (T17)

---

## Why

The product key is **derived** from the name, and a derived key can drift from the value it is
derived from: one code path trims and another does not, and the same product becomes two rows that
no unique index can catch — their `item_ref` values genuinely differ.

A split product halves its own demand history, and the reorder recommendation built on it is wrong in
the direction that runs a shelf empty.

## Task

- `psync_transform/validation/t17.py` — `check_item_identity(settings)`, two conditions the unique
  index cannot enforce:
  - every current row's `item_ref` equals `'name:' || normalised(item_name)` — the identity is still
    what it claims to be;
  - no two current rows share a normalised name — the case the index misses when two refs disagree
    about spacing or case.
- The normalisation is written once in SQL, so the check and the build cannot disagree about what
  "normalised" means.
- Critical severity.
- Note what this check deliberately does **not** test: the unique index already guarantees one
  current row per `item_ref`, so asserting that would pass forever.

## Done when

- [ ] PASS over a correct build.
- [ ] A current row whose `item_ref` does not match its name fails with `TRF_ITEM_IDENTITY_SPLIT`,
      reporting both symptoms (the mismatch and the shared name).

## Depends on

#69.
