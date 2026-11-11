<!--
STAGE 3 — BATCH 5: two issues, ready to post.

Create them in this order; they should land as #135 and #136 (PR #134 was merged). Each block below
is one issue: post the TITLE line as the title, and everything below the --- as the description.

One PR. Load specification revision 1.4 goes up first: the log stem carries the run id, and a
refusal is recorded as a result.
-->

---

TITLE: [Load] Record every table and every check in the ledger

---

## Why

§6.1 asks for a row per target table and a row per check, so a reader can see which table carried
how many rows and which check said what. Without them the ledger only says a batch succeeded, which
is not enough to audit a day or to explain a refusal.

## Task

- `record_tables` writes one `load_runs` row per table: `load_type` `FULL` for a dimension and
  `INCREMENTAL` for a fact, the window, the timestamps, `records_received`, `records_inserted` and
  `records_rejected`, and the status.
- `record_checks` writes one `load_validation_results` row per check: status, severity, message and
  error code.
- Both are written on the autocommit connection, like the run-level row, so a rolled-back batch still
  records what it attempted and why it was refused.
- `record_finish` updates the **run-level row only** — `where run_id = … and table_name is null`. It
  previously updated every row sharing the run id, which made all nine rows report the batch total
  instead of their own.
- L13 is recorded with severity `warning`, as §5 states; it was being written as `critical`.

## Done when

- [ ] The ledger holds nine rows: one run-level and one per table, each with its own counts —
      11, 2, 60, 6, 3, 2, 60, 6 and 150 at run level.
- [ ] `load_validation_results` holds seven rows, `L13` among them with severity `warning`.
- [ ] A rolled-back batch still leaves both sets of rows.

## Depends on

#132, #133 — merged.

---

TITLE: [Load] Decide the batch and write its two log files

---

## Why

§8.1 turns the check results into one of four verdicts, and §6.2 requires the two log files Stages 1
and 2 already write. Without a verdict the warehouse publishes rows with nothing recorded about
whether they were acceptable; without the logs a run cannot be reconstructed.

## Task

- `psync_load/decisions.py`: `decide(checks) -> Decision`, derived from severity, never chosen —
  any critical failure is `REJECTED`; a warning-severity failure is `MANUAL REVIEW`; a warning is
  `APPROVED WITH WARNING`; otherwise `APPROVED`. Only the two approved verdicts publish.
- `load_batch` calls `decide` and rolls back when the verdict does not publish, so `MANUAL REVIEW`
  holds the batch rather than committing it.
- `psync_load/runlog.py`: `RunTrace` writing `<stem>.log` line by line and `<stem>.json` once, with
  `[Load]` on every line and `"stage": "load"` in the record. The stem is `<batch_id>_<run_id[:8]>`,
  so a retry does not overwrite the attempt that failed.
- The CLI: gate, load, verify, decide, record, log — and exit 1 when the verdict does not publish.
  A crash is retried up to `MAX_RETRIES` with `RETRY_BACKOFF_SECONDS`; a verdict is not retried.

## Done when

- [ ] The live batch reaches `APPROVED` and leaves a `.log` and a `.json` in `data/logs/load/`.
- [ ] The narrative reads `time | level | [Load] | step | message`, one line per step.
- [ ] A forced failure — an exclusive lock with `LOCK_TIMEOUT_SECONDS=2`, `MAX_RETRIES=0` — exits 1,
      records `failed` / `LOAD_FAILED`, and leaves **no** JSON.
- [ ] `decide()` returns all four verdicts for the four combinations, and only two of them publish.

## Depends on

#135.
