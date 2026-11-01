<!--
EVIDENCE — BATCH 8: one issue, ready to post.

Post the TITLE line as the title and everything below the --- as the description. It should land as
#118 (the last number used was PR #117).

Code only — the sentence lives in a generated file, not in either specification.
-->

---

TITLE: [Pipeline] Say which log format the inspection pack is describing

---

## Why

The pack's `README.txt` states that every log line carries `[stage]`. It also copies the log of the
day's **successful extraction run** — and on 2026-10-18 that run happened at 19:50 on 31 October,
hours before the label existed. So the pack ships one labelled file, one unlabelled one, and a README
that describes only the first.

A log cannot be retro-labelled: the newer extraction run that has the label is a `skipped` run, and
the pack is right to ignore it. The README has to say so instead.

## Task

- One sentence in `datapack._readme`: logs written before 1 November 2026 carry four columns and no
  stage, and where that is the case the stage is the one in the filename.
- Nothing else changes — same files, same counts, same layout.

## Done when

- [ ] A rebuilt 2026-10-18 pack explains the four-column case, and its README no longer contradicts
      the unlabelled file beside it.
- [ ] The pack still holds 16 extracted rows, 24 transformed rows and 4 log files.

## Depends on

#114, #116 — merged.
