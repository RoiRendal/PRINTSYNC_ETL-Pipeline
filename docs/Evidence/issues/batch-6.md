<!--
EVIDENCE — BATCH 6: one issue, ready to post.

Post the TITLE line as the title and everything below the --- as the description. It should land as
#114 (the last number used was issue #113).

One PR, code only. The README revision that documents this command goes up afterwards — Lyell
uploads it once this is merged, because a README describing a command the repository does not yet
contain is the same problem as the phantom handover manifest.
-->

---

TITLE: [Pipeline] Pack a business day's data and logs for inspection

---

## Why

The evidence folder carries the logs, but not the rows. A reader with no database can follow what
the pipeline did and cannot see what it acted on — no extracted rows, no published rows, no way to
connect a figure to the log line that produced it.

The professor asked for exactly that: the extracted and transformed data in a file, beside the log
of how it was extracted and transformed.

## Task

- Add `psync_extract/datapack.py` — `build_pack(conn, data_dir, business_date, *, as_of=None)`.
- Resolve the day's **successful extraction run** from `pipeline_runs` and its **transformation
  batch** from `transformation_runs`. If either is missing, fail with a message naming which one
  and the command that would produce it.
- `extracted/` — the seven staging tables for that run, filtered on `run_id`, one CSV each.
- `transformed/` — the eight output tables, whole: the dimensions are cumulative history and the
  facts are the days, and the pack is small enough that filtering would hide more than it saved.
- `logs/` — the two log files of each stage, copied as they are.
- `README.txt` — what each folder is, which run and batch produced it, the row count per table, and
  how to read a log line. Written for someone who has never seen the database.
- Every CSV through `COPY … TO STDOUT (FORMAT csv, HEADER true)`, UTF-8 with a BOM, so Excel opens
  them without an import dialog.
- Zip to `<data dir>/packs/psync_pack_<business date>.zip`, assembled in a staging folder and moved
  into place, so an interrupted build leaves no half-filled folder.
- CLI: `python -m psync_extract.datapack --date YYYY-MM-DD [--data-dir …] [--as-of …]`.
- Reads only. No ledger row, no log file, no writes of any kind — a pack is a copy, not a run.

## Done when

- [ ] `--date 2026-10-18` packs 16 extracted rows, 24 transformed rows and 4 log files.
- [ ] Every CSV opens with a header row, and the extracted ones carry `source_id`, so a row can be
      traced to PRINTSYNC.
- [ ] A day with no successful extraction, or no batch, fails naming which is missing.
- [ ] A failed build leaves no folder behind.

## Depends on

#102, #104 — merged. The README revision follows this merge.
