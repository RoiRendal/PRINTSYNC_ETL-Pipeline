"""The submission archive (doc section 5).

One dated zip of the evidence folder: what a defense opens when there is no database, no repository
and no host to log into. The folder is already the evidence; the zip is how it travels.

Two properties make it worth having:

* **It reads files and nothing else.** An archive that needed the database would be unavailable
  exactly when it is wanted — after the container is stopped, on the panel's laptop.
* **It says what is inside.** A `MANIFEST.txt` at the root lists every entry with its size and
  SHA-256, and states which of the four evidence folders contributed. A bundle missing the
  transformation logs should look incomplete on its own, not to someone who remembers the layout.

The archive is a **snapshot, not a backup**: it does not replace retention, and re-running retention
does not touch it. It lives in ``<data dir>/submission/``, which it also excludes from itself.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from psync_extract.config import DEFAULT_DATA_DIR

__all__ = [
    "MANIFEST_NAME",
    "SubmissionArchive",
    "SubmissionError",
    "build_submission_zip",
    "main",
]

# A relative PSYNC_DATA_DIR is anchored here, the same rule the two Settings classes apply.
REPOSITORY_ROOT = DEFAULT_DATA_DIR.parent

MANIFEST_NAME = "MANIFEST.txt"
SUBMISSION_DIR = "submission"

# The four folders a complete bundle carries. Each stage's logs, the handover that links them, and
# the exports that make the quarantine readable without a database.
EVIDENCE_FOLDERS = ("logs/extract", "logs/transform", "handover", "exports")

# Git plumbing rather than evidence, and a half-written log is worse than an absent one.
_SKIP_NAMES = {".gitkeep"}
_SKIP_SUFFIXES = {".tmp"}


class SubmissionError(RuntimeError):
    """The archive cannot be built as asked."""


@dataclass(frozen=True)
class SubmissionArchive:
    """Where the archive went, and what went into it."""

    path: Path
    entries: int
    bytes: int
    missing: tuple[str, ...]


def _evidence_files(data_dir: Path) -> list[tuple[Path, Path]]:
    """Every evidence file, as (relative, absolute), sorted so two builds list the same way."""
    found: list[tuple[Path, Path]] = []
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(data_dir)
        if relative.parts and relative.parts[0] == SUBMISSION_DIR:
            continue
        if path.name in _SKIP_NAMES or path.suffix in _SKIP_SUFFIXES:
            continue
        found.append((relative, path))
    return found


def _folder_counts(data_dir: Path, files: list[tuple[Path, Path]]) -> dict[str, int]:
    """How many files each evidence folder contributed — zero is a fact worth printing."""
    counts = {folder: 0 for folder in EVIDENCE_FOLDERS}
    for relative, _ in files:
        parts = relative.parts
        for folder in EVIDENCE_FOLDERS:
            if "/".join(parts[: len(folder.split("/"))]) == folder:
                counts[folder] += 1
                break
    return counts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _human(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _manifest(
    data_dir: Path,
    files: list[tuple[Path, Path]],
    counts: dict[str, int],
    built_at: datetime,
) -> str:
    """The archive's own table of contents, written before anything else goes in."""
    total = sum(path.stat().st_size for _, path in files)

    lines = [
        "psync_analytics - submission archive",
        "====================================",
        "",
        f"built at       {built_at.isoformat()}",
        f"data folder    {data_dir}",
        f"entries        {len(files)} file(s), {_human(total)}",
        "",
        "Stages represented",
        "------------------",
    ]
    for folder in EVIDENCE_FOLDERS:
        lines.append(f"{folder:<16} {counts[folder]} file(s)")

    empty = [folder for folder in EVIDENCE_FOLDERS if not counts[folder]]
    if empty:
        lines += [
            "",
            "INCOMPLETE: no files from " + ", ".join(empty) + ".",
            "This bundle was built with --allow-incomplete; it is not the whole evidence folder.",
        ]

    lines += [
        "",
        "Contents",
        "--------",
        f"{'bytes':>10}  {'sha256':<64}  path",
    ]
    for relative, path in files:
        lines.append(
            f"{path.stat().st_size:>10}  {_sha256(path)}  {relative.as_posix()}"
        )

    lines += [
        "",
        "This archive is a snapshot of the evidence folder, taken on the date in its name.",
        "It does not replace retention: the log files inside it may since have aged out of",
        "<data dir>/logs, which is the point of taking a copy before a defense.",
    ]
    return "\n".join(lines) + "\n"


def build_submission_zip(
    data_dir: Path | str,
    *,
    as_of: date | None = None,
    allow_incomplete: bool = False,
    now: datetime | None = None,
) -> SubmissionArchive:
    """Write ``<data dir>/submission/psync_evidence_<as_of>.zip`` and return what went in."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise SubmissionError(
            f"the evidence folder does not exist: {data_dir}. Nothing to archive — check "
            "PSYNC_DATA_DIR rather than producing an empty bundle."
        )

    files = _evidence_files(data_dir)
    counts = _folder_counts(data_dir, files)
    missing = tuple(folder for folder in EVIDENCE_FOLDERS if not counts[folder])

    if missing and not allow_incomplete:
        raise SubmissionError(
            "the evidence folder is incomplete: no files from "
            + ", ".join(missing)
            + ". A submission that silently omits a stage is worse than no submission, so this "
            "fails rather than guessing. Re-run with --allow-incomplete to build it anyway, and "
            "the manifest will say so."
        )

    as_of = as_of or date.today()
    built_at = now or datetime.now(timezone.utc)
    submission_dir = data_dir / SUBMISSION_DIR
    submission_dir.mkdir(parents=True, exist_ok=True)
    target = submission_dir / f"psync_evidence_{as_of.isoformat()}.zip"

    # Written beside the target and renamed into place: an interrupted build must not leave a
    # truncated zip that opens far enough to look like a complete one.
    temporary = target.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST_NAME, _manifest(data_dir, files, counts, built_at))
            for relative, path in files:
                archive.write(path, arcname=relative.as_posix())
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    return SubmissionArchive(
        path=target,
        entries=len(files),
        bytes=target.stat().st_size,
        missing=missing,
    )


def main(argv: list[str] | None = None) -> int:
    """Build the archive from the command line."""
    parser = argparse.ArgumentParser(
        prog="psync_extract.submission",
        description="Zip the evidence folder for submission or a defense.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="the evidence folder; defaults to PSYNC_DATA_DIR, then <repo>/data",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="the date in the archive's name; defaults to today",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="build the archive even when an evidence folder is empty, and say so in the manifest",
    )
    args = parser.parse_args(argv)

    data_dir = args.data_dir or Path(os.getenv("PSYNC_DATA_DIR") or DEFAULT_DATA_DIR)
    if not data_dir.is_absolute():
        data_dir = REPOSITORY_ROOT / data_dir

    try:
        result = build_submission_zip(
            data_dir, as_of=args.as_of, allow_incomplete=args.allow_incomplete
        )
    except SubmissionError as exc:
        print(f"submission error: {exc}", file=sys.stderr)
        return 1

    print(f"archive    {result.path}")
    print(f"entries    {result.entries} file(s)")
    print(f"size       {_human(result.bytes)}")
    if result.missing:
        print(f"incomplete {', '.join(result.missing)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
