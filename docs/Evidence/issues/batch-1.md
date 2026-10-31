<!--
EVIDENCE — BATCH 1: three issues, ready to post.

Create them in this order; they should land as #102, #103 and #104 (the last issue was #100 and PR
#101 was merged). Each block is one issue: post the TITLE line as the title, and everything below
the --- as the description.

One PR: the pipeline gets one evidence folder, a streamed text log beside each JSON log, and a
retention job that deletes the two together. The quarantine export and the submission zip are the
next two batches.
-->

---

TITLE: [Pipeline] Give the pipeline one evidence folder

---

## Why

The run's evidence is scattered across `pipeline/logs/` (both stages) and `pipeline/handover/` (the
manifest), each relative to whatever directory the process happened to be started in. Nothing
distinguishes Stage 1's log from Stage 2's except the filename, and there is no single folder to zip
for a defense.

§5 and §9 both say the logs live "on the pipeline host's filesystem". That stays true — but *which*
path is now a decision, and one folder with a stated layout is what makes the evidence findable.

## Task

- Add `PSYNC_DATA_DIR` to both `Settings`, defaulting to the repository's `data/` so it does not
  move with the working directory. One knob, not three that can disagree.
- Derive the rest from it: `log_directory` is `data/logs/extract` in Stage 1 and
  `data/logs/transform` in Stage 2; `handover_directory` is `data/handover`.
- Replace the `--log-dir` / `--handover-dir` flags and the `log_directory` / `handover_directory`
  flow parameters with the derived paths, so the two stages cannot be aimed at different folders by
  accident.
- The error message in `psync_transform.handover` tells an operator to "check HANDOVER_DIR". It now
  names `PSYNC_DATA_DIR`.
- Track the layout, not the artifacts: a `.gitkeep` in each subfolder, and `.gitignore` rules that
  keep the folders and ignore everything inside them.

## Done when

- [ ] Both stages write under `<repo>/data/` regardless of the working directory.
- [ ] A clone shows `data/logs/extract/`, `data/logs/transform/` and `data/handover/`, and tracks
      nothing inside them.
- [ ] One `PSYNC_DATA_DIR` moves all of it.

## Depends on

Nothing.

---

TITLE: [Pipeline] Stream a timestamped run log

---

## Why

The JSON log says what happened; it cannot say *when*, in what order, or how long anything took.
Those timings exist only in `pipeline_runs` and `transformation_runs` — a database, not something a
panel can read and not something that survives beside the artifacts.

The JSON is also written once, at the end, so a run that crashes leaves no record of how far it got.

## Task

- Add `RunTrace` to both `runlog` modules, the same shape in each, as `write_log` already is. It is
  opened with a directory and the run's stem, streams one line per step to `<stem>.log`, and
  accumulates the same steps as `{"step", "ms"}` for the JSON.
- Line format: `2026-10-31 13:41:33 | INFO | extract | orders: 412 rows in 1.8s`. Flushed per line,
  so a crash leaves what actually happened rather than nothing.
- Steps, Stage 1: pre-flight, one per extracted table (the timings already exist in the extractor
  loop), rejects, validation, decision, record, log, handover. Stage 2 mirrors it: input gate,
  dimensions, facts, validation, decision, record, log.
- `build_log` gains `steps`. The text file and the JSON are two renderings of one list, so they
  cannot disagree.
- A raised exception writes a closing `FAILED` line naming the exception before it propagates.
- Identifiers, counts and timings only — no row contents (§9).

## Done when

- [ ] One run leaves `<stem>.log` and `<stem>.json` sharing a stem.
- [ ] The text log shows every step in order with its duration; the JSON carries the same list.
- [ ] A run that raises leaves a text log ending in `FAILED`, and no JSON.

## Depends on

#102.

---

TITLE: [Pipeline] Prune both log files, as a pair

---

## Why

`prune_json_logs` globs `*.json` and accepts whatever directory it is handed. Adding a `.log` per run
makes both halves of that wrong: the text logs would never be deleted, so §5's "deleted at 90 days"
quietly stops being true; and a caller could point the job at `data/`, deleting the handover
manifests — Stage 2's only input — along with the exports.

## Task

- Replace `prune_json_logs(directory, ...)` with `prune_logs(data_dir, ...)`, which computes
  `data/logs/` itself so it cannot be aimed at the wrong place.
- Glob `*.log` and `*.json` in both stage subfolders, group by stem, and delete the pair together: a
  text log without the record it belongs to is worse than neither.
- Raise `FileNotFoundError` when `data/logs/` is absent rather than returning 0. A retention job
  that silently deletes nothing still reports success.
- `handover/` and `exports/` are never pruned, and the docstring says why.

## Done when

- [ ] A pair older than 90 days is removed by one call; a pair inside 90 days is untouched.
- [ ] A `.log` whose `.json` has already gone is removed with the pair.
- [ ] A `data/` with no `logs/` raises instead of returning 0.
- [ ] `data/handover/` survives a prune of the same tree.

## Depends on

#102, #103.
