<!--
EVIDENCE — BATCH 5: one issue, ready to post.

Post the TITLE line as the title and everything below the --- as the description. It should land as
#113 (the last number used was PR #112).

This batch is documentation only. There is no code and no pull request: Lyell uploads the
Transformation document with the issue, and the issue closes when that upload lands. Roi has nothing
to build.
-->

---

TITLE: [Docs] Withdraw the SKIPPED decision the pipeline never returns

---

## Why

§10.1 listed a `SKIPPED` decision — "the same `batch_id` already succeeded and the handover is
unchanged" — by analogy with Stage 1's V3. `SKIPPED` appears nowhere in `psync_transform`: a re-run
rebuilds the batch and publishes the same rows. A decision table that lists a verdict the code
cannot produce is a reader's trap, and it is the second such claim found this week.

## Task

- §10.1: the "already succeeded" row no longer names a decision. It says **rebuild**, and why the
  rebuild is idempotent — facts replaced by `business_date`, versions upserted on their natural key.
- §10.2: drop the `SKIPPED` role; no decision, no role.
- Add a note recording why the shortcut stays refused: this stage's output depends on rules that
  live in this repository, so "already ran" is not evidence that "would produce the same answer",
  and `code_version` is too coarse to tell a rule change from a re-run. Stage 1 can skip because
  re-extracting the same window returns the same rows.
- §8's column table: the check constraint still accepts `SKIPPED`; the pipeline never writes it. Say
  so, rather than claiming the column is narrower than it is.

## Done when

- [ ] §10.1 and §10.2 list only decisions the pipeline can actually return.
- [ ] The note explains why this stage rebuilds where Stage 1 skips.
- [ ] §8 does not claim a narrower domain than the constraint enforces.
- [ ] `grep -r SKIPPED pipeline/src/psync_transform` still returns nothing — the document now agrees
      with it rather than the other way round.

## Depends on

Nothing. Documentation only.
