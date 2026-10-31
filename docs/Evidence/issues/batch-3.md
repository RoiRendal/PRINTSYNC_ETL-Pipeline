<!--
EVIDENCE — BATCH 3: one issue, ready to post.

Post the TITLE line as the title and everything below the --- as the description. It should land as
#109 (the last number used was PR #108).

One PR: the evidence folder becomes one dated zip a defense can open on a machine with no database.

The specification revision goes up first, and it is the substantial one: §5 said no archive was
built, and revision 1.8 reverses that by defining the format, contents, consumer and procedure.
-->

---

TITLE: [Pipeline] Build the dated submission archive

---

## Why

The evidence folder is now four subfolders and a dozen files. A submission needs one artifact — and
§5's "On the archive" note has just been rewritten to define it, after three revisions saying no
archive would be built. This builds the thing the note describes.

## Task

- Add `psync_extract/submission.py` — `build_submission_zip(data_dir, *, as_of=None,
  allow_incomplete=False)`.
- Write `<data dir>/submission/psync_evidence_<as_of>.zip`: `MANIFEST.txt` at the root, then every
  file under the data folder except `submission/` itself, with paths unchanged. Skip `.gitkeep` as
  git plumbing and `*.tmp` as a half-written file.
- `MANIFEST.txt`: the build time, the folder, one line per evidence folder with its file count, and
  every entry with its byte size and SHA-256 — so a reader can verify a file they extract without
  trusting the archive that carried it.
- **Fail** when any of `logs/extract`, `logs/transform`, `handover` or `exports` is empty.
  `--allow-incomplete` builds anyway and writes `INCOMPLETE` plus the missing folder names into the
  manifest: a bundle missing a stage must look incomplete on its own.
- Written to `*.zip.tmp` and renamed into place, so an interrupted build leaves no truncated zip that
  opens far enough to look complete.
- CLI: `python -m psync_extract.submission [--data-dir …] [--as-of YYYY-MM-DD] [--allow-incomplete]`.
  No database connection, no ledger row: it reads files only, which is what lets it work after the
  container is stopped. Never scheduled.

## Done when

- [ ] The real `data/` folder produces a zip whose first entry is `MANIFEST.txt` and which holds
      every evidence file.
- [ ] Each manifest entry's size and SHA-256 match the file inside the zip.
- [ ] An empty evidence folder is refused; `--allow-incomplete` writes `INCOMPLETE` into the
      manifest instead.
- [ ] A missing data folder is refused with a message naming it.
- [ ] The zip opens and reads with no database and no repository present.

## Depends on

#102, #104, #106 — merged.
