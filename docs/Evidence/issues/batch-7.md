<!--
EVIDENCE — BATCH 7: one issue, ready to post.

Post the TITLE line as the title and everything below the --- as the description. It should land as
#116 (the last number used was PR #115).

Two specification revisions go up first — Extraction 1.9 and Transformation 1.11 — because the line
format is part of both contracts.
-->

---

TITLE: [Pipeline] Name the stage on every log line

---

## Why

The narrative's format is `time | level | step | message`. Both stages' logs share one folder —
`data/logs/extract/` and `data/logs/transform/`, and in the inspection pack they sit side by side in
`logs/` — so a line read on its own says nothing about which stage wrote it. The filename tells you
only if you already know that `psync_nightly_analytics_…` is extraction and `TRF_…` is
transformation, which is exactly the knowledge a log is supposed to replace.

## Task

- Both `RunTrace._write` put the stage between the level and the step:
  `… | INFO | [Extraction] | extract.payments | 9 rows in 0.1s`.
- Both `build_log` payloads carry `"stage"`, so the record is as explicit as the narrative.
- The stage is a property of the class, not a constructor argument: `RunTrace` lives in a
  stage-specific package, so hard-coding it cannot be wrong and no call site changes.
- `datapack`'s generated `README.txt` explains the new column.
- Extraction §4 and Transformation §8 carry the new sample line and say why the label is on every
  line rather than in a header.

## Done when

- [ ] An extraction line reads `… | INFO | [Extraction] | run | …`.
- [ ] A transformation line reads `… | INFO | [Transformation] | facts | …`.
- [ ] Both JSON records carry `stage`.
- [ ] A pack built after the change explains the format in its own README.

## Depends on

Extraction revision 1.9 and Transformation revision 1.11.
