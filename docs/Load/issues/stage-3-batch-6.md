<!--
STAGE 3 — BATCH 6: two issues, ready to post.

Create them in this order; they should land as #138 and #139 (PR #137 was merged). Each block below
is one issue: post the TITLE line as the title, and everything below the --- as the description.

One PR, and the last one of the stage. Load specification revision 1.5 goes up first.
-->

---

TITLE: [Load] Snapshot before the load and prune on a schedule

---

## Why

The transaction rollback covers a load that fails. It does not cover a load that commits and is
found to be wrong an hour later. §7 asks for a snapshot of the reporting tables before the first
write, and for retention that runs on a schedule rather than by hand — with two lifetimes, because
operational detail and the evidence of what was published are not the same thing.

## Task

- `psync_load/snapshot.py`: `write_snapshot(target, settings, handover)` streams the eight reporting
  tables to `<data dir>/snapshots/<batch_id>/<table>.csv` by `COPY … TO STDOUT WITH (FORMAT csv,
  HEADER true)`. Each file is written to a `.part` name and renamed when complete, so an interrupted
  snapshot cannot be mistaken for a whole one.
- Call it in `load_batch` **before the first write**, so the snapshot is the state a mistake would be
  undone to.
- `psync_load/retention.py`: `prune_load_logs` (90 days) and `prune_snapshots` (7 days). A run's two
  log files age out together. The directory is always derived from the data dir, never accepted as
  an argument — that is what stops the job reaching `handover/`, `exports/` or `submission/`.
- `python -m psync_load.retention [--dry-run]` runs it.

## Done when

- [ ] A run leaves eight CSVs under `data/snapshots/<batch_id>/`, each with a header row.
- [ ] An aged log pair is deleted; a fresh one beside it is not.
- [ ] An aged snapshot directory is deleted.
- [ ] `data/handover/`, `data/exports/` and `data/submission/` are unchanged afterwards.

## Depends on

#135, #136 — merged.

---

TITLE: [Load] Record the problems that happened, and build the Lab 5 submission

---

## Why

§9 listed eleven plausible load problems and none of the three this stage actually hit. A section
written from imagination is worth less than one written from a failure, and the reader planning a
similar pipeline will meet those three in that order. The README still describes two stages, and the
Lab 5 folder holds only the template.

## Task

- Add three rows to §9, each with cause, impact and the mitigation that was implemented: a
  wholesale dimension replace breaking the second day's foreign keys; a retried batch refused by the
  ledger's one-row-per-batch index; a single unresolvable row aborting an entire `COPY`.
- Update `README.md`: the third command in *Running the stages*, the new `data/logs/load/` and
  `data/snapshots/` entries, and the retention lifetimes.
- Build the three deliverables in `Lab 5/` from the specification — Markdown, DOCX and PDF — with a
  copy of `Lab 4/md_to_docx.py` for the conversion.

## Done when

- [ ] §9 has fourteen rows, three of them the problems found while building this stage.
- [ ] `README.md` lists all three stages and all three evidence folders.
- [ ] `Lab 5/` holds the `.md`, `.docx` and `.pdf`, and the PDF renders every section including the
      revision history.

## Depends on

#138.
