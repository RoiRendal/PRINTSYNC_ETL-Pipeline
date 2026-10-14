"""PRINTSYNC nightly analytics batch pipeline - Stage 1 (Extract).

This package is a standalone Python application. It is **not** part of the
PRINTSYNC application and never imports PRINTSYNC code. It reads from the
PRINTSYNC operational database over a read-only connection and writes only to
the pipeline's own database, ``psync_analytics`` (doc section 1.6).

Every section reference (``§x.y``) in this package's docstrings points at
``docs/Extraction/Data-Extraction-Documentation-for-PRINTSYNC.md``, which is the
contract this code implements.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
