<!--
STAGE 2 — BATCH 9: three issues, ready to post.

Create them in this order; they should land as #90, #91 and #92 (the last issue was #78 and PR #79
was merged). Each block is one issue: post the TITLE line as the title, and everything below the ---
as the description.

One PR: the batch is recorded, decided and logged. The orchestration that calls all of it — the CLI
and the Prefect flow — is the next (and last) batch.
-->

---

TITLE: [Transformation] Record the batch and its rule counts

---

## Why

§8's ledger is what the Load stage reads to decide whether to take the output, and what an auditor
reads a month later to answer "what did this pipeline claim to publish for this day, from which
extraction, changed by which rules?".

## Task

- Add `psync_transform/runs.py` — `TableRecord`, `RuleCount`, `record_batch(conn, batch, tables,
  checks, decision, started_at, ended_at, rule_counts)`.
- One row per output table (four facts, four dimensions — eight rows), plus one run-level row whose
  `table_name` is null. The same grain as `pipeline_runs`, so the two stages' ledgers read alike.
- **Replace, do not accumulate**: the batch's rows in `transformation_runs` and
  `transformation_rule_counts` are deleted before they are written, so a retry rewrites its own
  record instead of appending a second one.
- `records_modified` is recorded per table but is **not part of any reconciliation** (§7). A record
  that was cleaned and kept is retained, not rejected.
- `rules_applied` is **rows, not a jsonb blob** — `transformation_rule_counts`, one row per rule per
  table, because a blob cannot be indexed, summed or charted.
- `transformation_status` maps the decision: APPROVED and APPROVED WITH WARNING are `success`;
  REJECTED, MANUAL REVIEW are `failed`.
- The caller owns the transaction.

## Done when

- [ ] A recorded batch produces one run-level row (`records_read 28, records_output 10,
      records_modified 0, code_version 'psync_transform 0.1.0 / rules 1.0'`) and one row per output
      table.
- [ ] `transformation_rule_counts` holds one row per rule recorded.
- [ ] Recording the same batch twice produces one record, not two.

## Depends on

#65–#74 — merged.

---

TITLE: [Transformation] Decide the batch outcome

---

## Why

§10.1's table is the whole point of the check set: eight results arrive separately, and the decision
turns them into one verdict that says whether the Load stage may take the output.

The order of the rules matters as much as the rules — a rejected batch and a manual review look
similar in a log; they are different days in an operator's morning.

## Task

- Add `psync_transform/decisions.py` — `Decision` and `decide(results, records_read,
  records_quarantined)`, in precedence order:
  1. a critical check failed → **REJECTED**
  2. the quarantine exceeds 1 % of what was read → **MANUAL REVIEW** — at ~28 sale lines a batch, 1 %
     is a fraction of a line, so in practice any quarantine holds the batch for review. That is the
     honest reading at this size, and it is fixed in advance so it cannot be chosen to fit a result.
  3. warnings → **APPROVED WITH WARNING**
  4. otherwise → **APPROVED**
- A non-critical check that FAILs is treated as a warning, exactly as Stage 1's decision engine
  treats it: the day is published and the shop is told.

## Done when

- [ ] A clean batch with no warnings decides APPROVED.
- [ ] The VAT under-collection (a non-critical FAIL) decides APPROVED WITH WARNING.
- [ ] A critical failure decides REJECTED, naming the checks.
- [ ] A quarantine above the 1 % limit decides MANUAL REVIEW.

## Depends on

#86–#88 — merged.

---

TITLE: [Transformation] Write the batch log

---

## Why

§8's log is the batch's evidence: the identity and window, the counts per output table, the outcome
of every check, the rule counts and any error. It contains identifiers, counts and timestamps only —
no customer data (§9).

## Task

- Add `psync_transform/runlog.py` — `build_log(**)` and `write_log(directory, payload)`.
- One file per batch, named for the batch ID, written by writing a temporary file and renaming it
  into place, so a crash never leaves a half-written log that looks like a complete one.
- The same filename sanitiser as Stage 1, so the two stages behave identically — even though the
  batch ID contains no colon, unlike Stage 1's `run_key`.

## Done when

- [ ] `write_log` writes `<batch_id>.json` with the identity, window, decision, counts, rule counts,
      validation results and code version.
- [ ] A crash mid-write cannot leave a partial log behind.

## Depends on

#90.
