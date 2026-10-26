<!--
STAGE 2 — BATCH 10 (the last): three issues, ready to post.

Create them in this order; they should land as #93, #94 and #95 (the last issue was #78 and PR #93
was merged). Each block is one issue: post the TITLE line as the title, and everything below the ---
as the description.

One PR, and the stage is closed: `python -m psync_transform --date 2026-10-17` runs the whole
transformation end to end.
-->

---

TITLE: [Transformation] Orchestrate the batch

---

## Why

Every piece exists — the dimensions, the facts, the seventeen checks, the ledger, the decision, the
log — and nothing calls them in the right order. This is what makes Stage 2 a pipeline.

## Task

- Add `psync_transform/pipeline.py` — `run_transformation(settings, log_directory=...)`, returning a
  `RunResult` with the batch, the decision, the per-check statuses and the log path.
- The order is §1.4's: resolve the batch, **T1 and T2 before a single row is written** (a staging
  table built from an older revision must fail loudly rather than produce a demand table with 93 %
  of its revenue unattributed), dimensions, facts, the remaining checks, decide.
- On a REJECTED verdict, **clear the published fact rows for the window** — no wrong row stands, and
  a re-run after the fix republishes. The dimensions are left alone: they are cumulative history,
  and reverting SCD2 would be destructive.
- `_rule_counts` derives the cleaning rules' counts from `quarantine_rows`, which already carries the
  rule that caught every rejected row — deriving them from recorded data means the counts cannot
  disagree with the quarantine.
- The run-level totals count each source table **once**, not once per fact that read it: the daily
  fact and the product fact read the same sales rows independently, and summing their reads would
  double both.

## Done when

- [ ] `run_transformation` on the 2026-10-17 handover builds all seven output tables and records
      eight ledger rows.
- [ ] The decision is APPROVED WITH WARNING, citing T10 (0 % cost coverage) and T6 (the VAT
      under-collection).
- [ ] A fact row exists for 2026-10-17: 2 transactions, ₱20.00 gross, 2 voided, `gross_profit` NULL
      at 0 % coverage.

## Depends on

#90–#92 — merged.

---

TITLE: [Transformation] Make it runnable from the command line

---

## Why

The orchestrator is a function. This is what makes it a program an operator can run when a night
needs repeating — and the exit code is what a scheduler notices.

## Task

- Add `psync_transform/__main__.py` — `python -m psync_transform --date YYYY-MM-DD [--parent-run
  UUID] [--log-dir PATH]`, printing the batch id, the window, the decision, the reason, every check
  status and the log path.
- `--parent-run` transforms one specific extraction run; without it, the most recent handover for the
  date is used.
- Exit 0 when the decision is an approval, 1 when it is not, 2 when the configuration is missing or
  invalid — the same contract as Stage 1's CLI.

## Done when

- [ ] `python -m psync_transform --date 2026-10-17` runs the whole batch and prints the summary.
- [ ] The exit code is 0 on APPROVED and APPROVED WITH WARNING, 1 otherwise.

## Depends on

#93.

---

TITLE: [Transformation] Add the Prefect flow

---

## Why

The scheduler runs the same function the demo runs — a thin wrapper, so orchestration can move from
local to managed later without rewriting the workflow.

## Task

- Add `psync_transform/flow.py` — `@flow def transformation_flow(...)`, calling
  `run_transformation` and printing the decision. No logic of its own.

## Done when

- [ ] The flow imports and calls the same function the CLI calls.

## Depends on

#93.
