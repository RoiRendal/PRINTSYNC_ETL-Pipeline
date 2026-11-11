<!--
EVIDENCE — BATCH 10: one issue, ready to post.

Post the TITLE line as the title and everything below the --- as the description. It should land as
#141 (the last number used was PR #140).

Two documents go up first — Extraction revision 1.10, and this issue file — because the contract
says what the archive carries.
-->

---

TITLE: [Evidence] The submission archive must carry the load stage's logs

---

## Why

`EVIDENCE_FOLDERS` still lists the four folders that existed when there were two stages:

```python
EVIDENCE_FOLDERS = ("logs/extract", "logs/transform", "handover", "exports")
```

Stage 3 writes `logs/load/`, and it is not on the list. So `python -m psync_extract.submission`
builds a bundle that looks complete — the completeness guard passes, the manifest is written — and
silently omits a third of the pipeline. The archive built today would have carried the extraction
and transformation of 2026-10-24 and nothing about loading it.

Worse, the two documents disagreed about it already: Extraction §5 said four folders, and Load §7
said the archive "carries `logs/load/` with everything else". The code matched neither.

## Task

- Add `logs/load` to `EVIDENCE_FOLDERS`, so a bundle missing the load stage fails the completeness
  check like any other missing stage.
- Correct Extraction §5: the required list is five folders, and the Contents row names every folder
  the archive actually holds — `snapshots/` and `packs/` were never listed even though the rule was
  always "every file under the data dir".
- Rebuild `data/submission/psync_evidence_<date>.zip` so the archive in hand matches the rule.

## Done when

- [ ] The archive holds `logs/load/` alongside the other four.
- [ ] A bundle with an empty `logs/load/` fails the build, naming the folder.
- [ ] Extraction §5 lists five required folders and names the whole contents.

## Depends on

#138, #139 — merged. This is the first thing found after Stage 3 closed, and it was found by
rebuilding the archive rather than by reading the code.
