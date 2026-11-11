<!--
STAGE 3 — BATCH 3: two issues, ready to post.

Create them in this order; they should land as #129 and #130 (PR #128 was merged). Each block below
is one issue: post the TITLE line as the title, and everything below the --- as the description.

One PR. Load specification revision 1.2 goes up first: it changes how dimensions are written and
how a retried batch is recorded, both found while building this batch.
-->

---

TITLE: [Load] Bulk-copy a table from Stage 2 into the warehouse

---

## Why

The two databases cannot be joined in one SQL statement, so rows have to travel through the client.
Row-by-row inserts would be slow and would hide a type problem until the thousandth row. `COPY` moves
each table as one stream, and it is the mechanism §3.1 names.

## Task

- Add `psync_load/loader.py` with `_columns`, `_select_sql` and `_stream`.
- Source side: `COPY (SELECT …) TO STDOUT`. The select lists the source's own columns plus the three
  bookkeeping values — `%s::text` for `load_batch_id`, `%s::uuid` for `load_run_id`, `now()` for
  `loaded_at` — bound as parameters, never interpolated.
- Target side: `COPY public.<table> (<columns>) FROM STDIN`.
- The column list comes from `information_schema.columns` on the **target**, ordered by position,
  minus the three load columns. No second hardcoded list that can drift from migration `005`.
- Both ends use PostgreSQL's default text format, so the stream round-trips unchanged.
- One statement per table. No `executemany`, no per-row insert.

## Done when

- [ ] One table copies with the expected row count and all three bookkeeping columns populated.
- [ ] The copied rows equal the source rows column for column.
- [ ] The copy is a single `COPY` per table, not a loop of inserts.

## Depends on

#126, #127 — merged.

---

TITLE: [Load] Load a batch in one transaction and refuse to publish it twice

---

## Why

A published day must be all-or-nothing. If the load dies halfway, the warehouse must not show one
table from the new batch and three from the old. And a batch already published must not be published
again — the reporting database is the product, so a duplicate load is a duplicate publication, not a
harmless rebuild.

## Task

- Add `load_batch(settings, handover, run_id)` in `loader.py`: one transaction on the warehouse,
  `SET LOCAL lock_timeout` and `statement_timeout` from configuration, dimensions first, then each
  fact's window.
- **Dimensions are upserted, not replaced** (§3.1, revision 1.2): stage the whole dimension in a
  temporary table by `COPY`, then `INSERT … ON CONFLICT (<primary key>) DO UPDATE`. A delete would
  raise a foreign-key violation as soon as the warehouse holds a second day, and an upsert writes
  every column anyway, so a version Stage 2 closed is closed here too.
- **Facts delete their window and bulk-insert** — unchanged.
- Add `psync_load/runs.py`: `record_start` and `record_finish`, on their **own autocommit
  connection** so a rolled-back load still leaves a `failed` row. `record_start` reuses the batch's
  existing run-level row rather than inserting a second — `load_runs` allows one per batch, and the
  earlier attempt is kept in its log narrative instead (§3.5, revision 1.2).
- Wire the CLI: gate, then load, then report per-table counts. A failure records `failed` with the
  message and returns 1.

## Done when

- [ ] The live batch loads 150 rows and the warehouse matches the source to the cent — ₱10,100.00
      net, ₱1,152.00 tax, 12 voids at ₱812.00.
- [ ] An exclusive lock held on `fct_daily_sales` with `LOCK_TIMEOUT_SECONDS=2` fails the load and
      leaves **zero** rows, dimensions included — the whole batch rolled back.
- [ ] A retry after that failure succeeds, reusing the ledger row rather than colliding with it.
- [ ] Running the same batch a second time is refused by L6.

## Depends on

#129.
