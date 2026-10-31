<!--
EVIDENCE — BATCH 2: two issues, ready to post.

Create them in this order; they should land as #106 and #107 (the last number used was PR #105).
Each block is one issue: post the TITLE line as the title, and everything below the --- as the
description.

One PR: the quarantine leaves the database as two CSVs a panel can open, with the reconciliation and
a README beside them so the folder explains itself without a psql session.

The specification revision this batch needs is separate, and goes up first: Lyell uploads it to main
before Roi branches, so the contract changes before the code does.
-->

---

TITLE: [Transformation] Export the quarantine as CSV

---

## Why

§9 keeps the quarantine in `quarantine_rows`, which is the "SQL" half of what the professor asked
for — but reading it needs `psql` into a Docker container. A panel cannot open a table, and "trust me,
it's in there" is not evidence.

The CSV is the same rows in a form Excel opens. The table stays the source of truth; the export is a
rendering of it, produced on demand, never edited.

## Task

- Add `exports_directory` to `Settings`, derived from `PSYNC_DATA_DIR` like the others:
  `<data dir>/exports/<batch_id>/`.
- Add `psync_transform/export.py` — `export_batch(conn, batch_id, directory) -> ExportResult`.
- **Row-level** `quarantine.csv`, one row per quarantined record, ordered by
  `(source_table, source_id, rule_id)` so two exports of the same batch are byte-identical:
  `COPY (SELECT … FROM public.quarantine_rows WHERE batch_id = %s ORDER BY …)
  TO STDOUT (FORMAT csv, HEADER true)`.
- Columns: `source_table`, `source_id`, `rule_id`, `reason`, `detail`, `business_date`,
  `parent_run_id`, `quarantined_at`, then `payload_json` last — the payload is the row that was
  rejected, and a reader wants the explanation before the data.
- **Summary** `quarantine_summary.csv`, one row per `(source_table, rule_id)`: `source_table`,
  `rule_id`, `reason`, `count`, ordered by `count DESC, rule_id`. This is the first file a reader
  opens; the row-level CSV is the evidence underneath it.
- Write both UTF-8 **with a BOM**, so Excel opens them without an import dialog.
- CLI: `python -m psync_transform --export <batch_id>`. This runs no batch: no row in
  `transformation_runs`, no log file. An export is derived from a batch that already happened, and
  recording it as a run would put a row in the ledger for work the pipeline did not do.
- A batch with no quarantined rows still writes both files, headers only. An empty file is the
  evidence that nothing was rejected; its absence is indistinguishable from an export that never ran.
- An unknown `batch_id` fails with a message naming it and leaves no folder behind.

## Done when

- [ ] The 2026-10-17 batch exports its quarantined rows, and the summary's counts sum to the row
      count.
- [ ] Both files open in Excel without an import dialog.
- [ ] A batch with zero quarantined rows produces both files, headers only.
- [ ] `--export` writes no row to `transformation_runs` and no file to `data/logs/transform/`.
- [ ] An unknown batch id exits non-zero, names the id, and creates nothing.

## Depends on

#102 (the evidence folder). Merged.

---

TITLE: [Transformation] Write the reconciliation and a README beside the export

---

## Why

The CSVs say what was rejected; they do not say whether the batch balanced. §7's reconciliation is
the arithmetic that proves nothing went missing — read = output + rejected — and today it lives only
in the JSON log one directory away, so a reader opening `exports/` has to already know where else to
look.

The README is the same argument in one page: a folder handed to someone who was not there should not
need a conversation to be understood.

## Task

- Add `_reconciliation.json` beside the CSVs, per batch: for every source table, `records_read`,
  `records_output`, `records_rejected`, and `balances` — the check that read = output + rejected —
  plus `quarantine_rate` and `max_reject_rate_percent` from §10.1 with the verdict that follows.
- Add `README.txt`, plain text so it opens anywhere: batch id, parent run, business date, window,
  decision and reason, the rule ids present with their counts, and one line per file in the folder
  saying what it is and how to read it.
- Both derived from `transformation_runs` and `quarantine_rows`, so they cannot disagree with what
  was published. Nothing is recomputed from staging: the batch already decided, and re-deriving its
  numbers here would be a second opinion nobody asked for.
- Written into a temporary directory and moved into place, so an interrupted export never leaves a
  folder that looks complete.

## Done when

- [ ] `_reconciliation.json` shows `balances: true` for every table in the 2026-10-17 batch.
- [ ] The rate and the verdict match the batch's `transformation_runs` row and §10.1.
- [ ] `README.txt` names every file present in the folder.
- [ ] An interrupted export leaves no `<batch_id>` folder behind.

## Depends on

#106.
