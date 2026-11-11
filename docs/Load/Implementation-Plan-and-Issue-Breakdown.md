# Implementation Plan & Issue Breakdown — Load Phase (Stage 3)

**PRINTSYNC Nightly Analytics Batch Pipeline** · Laboratory Activity 5
11 November 2026

The contract is [`Data-Load-Documentation-for-PRINTSYNC.md`](Data-Load-Documentation-for-PRINTSYNC.md)
(revision 1.0). This plan says how the code gets built against it, in what order, and what evidence
each pull request carries.

---

## 1. What this plan is

Stage 3 is the last stage. It takes the eight business-ready tables Stage 2 published in
`psync_analytics` and loads them into a separate reporting database, `psync_warehouse`, then proves
that the copy is complete, accurate and traceable.

The work is split into **six batches, two issues each**, starting at issue **#123**. Issue and PR numbers share one GitHub sequence, so each batch consumes three: two issues and the PR that closes them. Two or three
issues per PR keeps a pull request readable for the professor, who reads PRs rather than commits.
Each batch is one coherent piece of the specification: by the end of batch 6, every one of the nine
sections has code or evidence behind it.

This plan is a living document. It is edited in place as batches land; git is the version control.

---

## 2. Ground rules

1. **The document is the contract.** The specification goes up on `main` before any Stage 3 code.
   If a batch uncovers a gap in it, the document is corrected first, in its own commit, with a new
   revision row — then the code follows.
2. **One GitHub issue per plan item; 2–3 issues per PR.** Branches are `issue-<N>-<short-slug>`;
   the PR body ends with `Closes #N` per issue.
3. **No automated tests.** Evidence is real command output pasted into the PR body — a connection
   check, a row count, a reconciliation result, a log line.
4. **Concise issue and PR bodies.** Why → Task → Done when → Depends on. Detail belongs in code
   comments, not in the issue.
5. **Never create or close GitHub issues from the coder's account.** Erica is the issuer; the
   deliverable is `docs/Load/issues/stage-3-batch-N.md` for her to copy. Lyell edits the documents
   on the GitHub site, so her commits land on `main` and never inside a code PR.
6. **The order is A → B → C → D.** A: Lyell uploads. B: Roi clears local copies and pulls. C:
   Erica creates the issues. D: Roi branches from the updated `main`, commits, pushes.
7. **PRINTSYNC is never modified.** Stage 3 never connects to it. It reads `psync_analytics` and
   writes `psync_warehouse`.
8. **No new cleaning or business logic.** A wrong value here is a Stage 2 bug, reported through §8,
   not repaired in the load.

---

## 3. Workflow

| Phase | Who | What |
| --- | --- | --- |
| A | Lyell | Uploads the specification revision and the batch's issue file to `main` on the GitHub site, as separate commits |
| B | Roi | Clears his local copies of those two files — tracked ones with `git checkout --`, untracked ones moved to Temp, then removed — runs `git pull`, and confirms `git status` shows only the code files that are his to commit |
| C | Erica | Creates the two issues from `docs/Load/issues/stage-3-batch-N.md`, in order |
| D | Roi | `git checkout -b issue-<N>-<slug>`, commits one file per logical unit, pushes |
| E | — | PR opened with the real command output; merged after review |

The same order that carried Stages 1 and 2 through ten batches without a merge conflict.

---

## 4. The batches

### Batch 1 — Foundation (issues #123–#124, PR #125)

- **#123** Scaffold `psync_load`: package, `__version__`, `config.py`, CLI entry point.
- **#124** Create `psync_warehouse`: one-off `pipeline/warehouse_bootstrap.sql` for the database and
  the two roles, `pipeline/warehouse_migrations/005_warehouse_schema.sql` for the eight reporting
  tables and three bookkeeping tables, and `python -m psync_load.db migrate`. The warehouse
  migrations live in their own directory because Stage 1's applier globs `pipeline/migrations/`.

*Evidence:* the package imports, both stages still import, the migration applies twice with the
second run a no-op, and `psync_loader` can `INSERT` while `psync_pipeline` cannot write the
warehouse.

### Batch 2 — The input gate (issues #126–#127, PR #128)

- **#126** Input contract reader: resolve the run-level `transformation_runs` row for a `batch_id`,
  its window, decision and per-table `records_output`; refuse anything not `APPROVED`.
- **#127** L1–L6 pre-load checks with the shared `CheckResult` shape (id, status, severity,
  message, error code), run before the target transaction opens.

*Evidence:* an approved batch passes all six; an unapproved batch is refused before a connection to
the warehouse is opened; a doctored count fails L4.

### Batch 3 — The loader (issues #129–#130, PR #131)

- **#129** Bulk `COPY TO STDOUT` → `COPY FROM STDIN` for one table, with the three
  `load_batch_id` / `load_run_id` / `loaded_at` columns attached.
- **#130** Orchestrate all eight in the order of §1.4 — dimensions first, facts second, deletes in
  reverse — in one transaction with `lock_timeout` and `statement_timeout`, rolling back whole on
  any failure, and refusing to duplicate a `SUCCESS` batch.

*Evidence:* 150 rows land in the warehouse; a deliberately broken constraint rolls the whole batch
back leaving zero rows; running the same batch twice is refused.

### Batch 4 — Reconciliation (issues #132–#133, PR #134)

- **#132** L7–L12: record, row-count, key-uniqueness, referential-integrity, null and amount
  reconciliation, each with its severity.
- **#133** `load_rejects` and L13: a row the load cannot write is recorded with `batch_id`,
  `table_name`, `rule_id`, `reason`, `payload`; rejects within 1 % warn, above 1 % fail.

*Evidence:* `received = inserted + rejected`, ₱10,100.00 net revenue matches to the cent, and a
seeded orphan is rejected rather than given an Unknown member.

### Batch 5 — Recording and deciding (issues #135–#136, PR #137)

- **#135** `load_runs` and `load_validation_results`: the run-level row plus one row per table with
  all fields in §6.1.
- **#136** The decision engine and the two log files: `APPROVED`, `APPROVED WITH WARNING`,
  `MANUAL REVIEW`, `REJECTED`, three retries with 30 s backoff, and the `.log`/`.json` pair with
  `[Load]` on every line.

*Evidence:* a successful run writes both files and a `success` row; a failed run leaves the
narrative ending in `ERROR` with no JSON; the log's counts agree with the ledger.

### Batch 6 — Retention and submission (issues #138–#139, PR #140)

- **#138** Snapshots, `prune_load_logs`, and the retention split: 90 days for detail, 24 months for
  the ledger and rejects, scoped so the job cannot reach `handover/`, `exports/` or `submission/`.
- **#139** §9 common-problems review, README update for Stage 3, and the three deliverables in
  `Lab 5/` — Markdown, DOCX and PDF — using a copy of `Lab 4/md_to_docx.py`.

*Evidence:* the prune job reports what it deleted and leaves the handover alone; the submission zip
opens to a README, the specification and the run's logs.

---

## 5. The gaps this stage has to answer

| Gap | Why it matters | Where it is resolved |
| --- | --- | --- |
| Stage 2 writes no handover manifest file | The template asks for handover status and counts. The `transformation_runs` ledger row is the handover; a new file would reverse revision 1.10 | §1.1, and batch 2 |
| Two databases cannot be joined in SQL | Counts and amounts must be compared in Python; a cross-database `JOIN` is not available | §1.3, §5 |
| Stage 2 already publishes `dim_*` / `fct_*` tables | Without a separate target there is no load stage | §1.2, and batch 1 |
| "Rejected" means two different things in Stages 2 and 3 | Stage 2's quarantine must not be counted again | Scope decision 3, §5, §7 |
| A rerun means something different here | Stage 2 rebuilds; Stage 3 must refuse to publish twice | §3.5, L6 |

---

## 6. What the stage will deliver

- A `psync_load` package implementing all nine sections of the specification.
- A separate `psync_warehouse` reporting database with eight reporting tables and three bookkeeping
  tables.
- L1–L13 validation with a stated severity for each check.
- `load_runs` metadata, a `.log`/`.json` pair per run, and `load_rejects` for anything refused.
- Retention, snapshots and access rules that match the two earlier stages.
- A real, rerunnable end-to-end demonstration against the live PRINTSYNC data, with command output
  in the pull requests.
- The three submission files in `Lab 5/`.

This list is ticked down as batches 1–6 merge.

---

## 7. What comes next

After batch 6, the three stages are complete end to end: Extract → Transform → Load. The last
remaining work is a final consistency pass — diff each specification against its code one more
time, rebuild the dated submission zip, and confirm every documented claim has a real command
output behind it. That is the same check that found the phantom manifest, the `read = output +
rejected` identity and the `SKIPPED` row in the first two stages.
