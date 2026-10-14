# PRINTSYNC_ETL-Pipeline

Standalone ETL pipeline for the PRINTSYNC printing shop: the nightly analytics batch
pipeline `psync_nightly_analytics` (Extract → Transform → Load).

**Stage 1 (Extract) is under construction.** Its specification is the contract this code
implements — code follows the document, never the other way round:

- [Extraction specification](docs/Extraction/Data-Extraction-Documentation-for-PRINTSYNC.md)

## Deployment boundary

This project is developed and run separately from PRINTSYNC. It reads from the PRINTSYNC
database over a **read-only** connection and writes only to its own database,
`psync_analytics`. No PRINTSYNC code is imported, and no PRINTSYNC file, table, column or
trigger is created or changed. See §1.6 of the specification.

## Repository layout

```
docs/Extraction/    the extraction specification - the contract this code implements
pipeline/           the entire ETL pipeline: package and project configuration
```

## Getting started

All pipeline code lives in `pipeline/`, so work from there:

```bash
cd pipeline
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux / macOS

pip install -e .
cp .env.example .env            # then fill in real values; never commit .env
```

Check that the package imports:

```bash
python -c "import psync_extract; print(psync_extract.__version__)"
```

## How work is tracked

Every change addresses exactly one GitHub issue; every issue cites the document section it
implements. Branches are named `issue-<N>-<short-slug>` and pull requests close their issue
with `Closes #N`.
