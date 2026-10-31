<!--
EVIDENCE — BATCH 4: one issue, ready to post.

Post the TITLE line as the title and everything below the --- as the description. It should land as
#111 (the last number used was PR #110).

One PR: a fix for the defect the end-to-end run found. The specification revision goes up first —
revision 1.9 of the Transformation document, which changes M-02 and M-03.
-->

---

TITLE: [Transformation] Date dimension versions by the day the thing was sold

---

## Why

M-02 and M-03 said `valid_from = business_date`. J-01 looks a version up on the line's own date,
and the look-back window can put that up to `LOOKBACK_DAYS` earlier — so a product first sold on a
look-back day had no version on the day it was sold, and the fact build stopped:

```
FactError: 4 sale line(s) have no product version.
```

Found by the end-to-end run for 2026-10-18, whose window reached back to 2026-10-15. The 2026-10-17
batch hid it because its sales were dated the same day as its batch, and the worked example in §10.4
would have failed the same way.

## Task

- `incoming_branch` and `incoming_item` gain an `effective_date`: the earliest
  `(created_at at time zone <run time zone>)::date` in the batch for that branch or product,
  falling back to the business date when it did not sell.
- The close, upsert and unchanged statements use `i.effective_date` instead of one batch-wide date.
- A **back-date** statement moves a current version whose `valid_from` is later than the effective
  date, so a retry repairs the dimension instead of colliding with the version a failed attempt left
  behind. A conflict there means real history already occupies that day, and failing loudly beats
  guessing which version is true.
- `build_dim_branch` and `build_dim_item` take `time_zone`, passed from `run_transformation` — the
  date is the sale's date in the shop's zone, not the host's.

## Done when

- [ ] The 2026-10-18 batch, which failed with four uncovered lines, builds: 16 PASS, T14 WARN,
      APPROVED WITH WARNING.
- [ ] The versions it opens are dated 2026-10-17 — the day the sales happened — not 2026-10-18.
- [ ] Running it twice leaves three `dim_item` rows, no product with two current versions, and T15
      passing.
- [ ] A version left at the wrong date by an earlier failed attempt is moved back, not duplicated.

## Depends on

Transformation document revision 1.9; #106–#107 — merged.
