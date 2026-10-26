<!--
STAGE 2 — BATCH 3: three issues, ready to post.

Create them in this order; they should land as #65, #66 and #67 (the last issue was #63 and PR #64
was merged). Each block is one issue: post the TITLE line as the title, and everything below the ---
as the description.

One PR, and the first one that writes rows: a generated calendar, the first SCD Type 2 build, and
the check that proves the versioning is sound.
-->

---

TITLE: [Transformation] Generate the date dimension

---

## Why

Every fact joins a date, and the demand average in rule B-13 looks back over a trailing window — so
the calendar has to cover the batch window **and** the days behind it, or the average has nothing to
join against.

## Task

- Add `psync_transform/dimensions.py` with `DimensionBuild` (what one build did, in the terms the run
  record uses) and `build_dim_date(conn, batch, demand_window_days)`.
- Generate `[window_start - demand_window_days, window_end]` with `generate_series`.
- Populate `year`, `quarter`, `month`, `month_name`, `day_of_month`, `iso_week`, `day_of_week`
  (1 = Monday, ISO-8601 — not `extract(dow)`, which starts on Sunday), `day_name`, `is_weekend`.
- `on conflict (date_key) do nothing`: a calendar does not change, and a second opinion about
  2026-10-17 would be a bug (rule M-01).

## Done when

- [ ] A build for 2026-10-17 writes 11 dates, 2026-10-07 → 2026-10-17 (a 3-day window plus the
      7-day demand window).
- [ ] Running it again writes 0 and reports 11 unchanged.
- [ ] `day_of_week` is 1 for a Monday and 7 for a Sunday; `iso_week` matches ISO-8601;
      `month_name` is not space-padded.

## Depends on

#61 — merged.

---

TITLE: [Transformation] Build the branch dimension (SCD Type 2)

---

## Why

This is the first SCD Type 2 build in the pipeline. A branch's name, VAT rate or currency changes
over time, and last month's revenue has to keep pointing at last month's VAT rate — otherwise every
historic margin silently re-computes itself at today's rate.

## Task

- `build_dim_branch(conn, batch)` in `dimensions.py`.
- Attributes: `code`, `name`, `is_active`, `vat_rate`, `currency_symbol`, `time_zone` — the branch
  row joined to its `business_settings` row.
- Normalise the text once into a temporary table (rule C-10: trim, then collapse internal runs of
  whitespace), so the "has it changed?" comparison and the write cannot disagree about the values.
- Compare **whole rows** (`is distinct from` on the tuple), close changed versions with
  `valid_to = business_date`, and open the new one.
- A version that started **today** is refreshed in place, not closed and reopened — closing it would
  set `valid_to = valid_from`, which the table refuses and which is right to refuse.
- A branch with no `business_settings` row raises `DimensionError` naming it. VAT rate, currency and
  time zone are `NOT NULL`, and inventing them would put a made-up VAT rate on real revenue.

## Done when

- [ ] A first build writes one version per branch, `valid_from` = the business date, `is_current`.
- [ ] A retry writes the same rows and closes nothing.
- [ ] Renaming a branch and building the **next** day closes the old version (`valid_to` = that day)
      and opens a new one; a branch that did not change is untouched.
- [ ] A branch with no settings row raises `DimensionError` naming the branch.

## Depends on

#65 (same module), #61.

---

TITLE: [Transformation] Check version continuity (T15)

---

## Why

A dimension with two versions in force for one day doubles every fact row that joins it, and no
total looks wrong afterwards — the revenue is simply too high, in a way that resembles a good day.

The schema already enforces two of the three conditions (one current row per natural key, and
`valid_to > valid_from`). It cannot enforce the third: **no two versions overlap**, because
`valid_to` is written by the build itself. A build that closes a version a day too late leaves two
versions in force while both constraints stay satisfied. That is what this check is for.

## Task

- Add `psync_transform/validation/t15.py` — `check_version_continuity(settings)`, covering
  `dim_branch` and `dim_item`:
  - no duplicate `is_current` rows per natural key;
  - no two versions whose half-open ranges intersect;
  - no version ending on or before it starts.
- Critical severity.
- The check reads **committed** state, like every check in this stage, so the batch commits its
  dimension writes before validating them.

## Done when

- [ ] PASS over a correct SCD2 build.
- [ ] A closed version that overlaps an open one fails with `TRF_VERSION_OVERLAP`, naming the
      natural key and both start dates.

## Depends on

#66.
