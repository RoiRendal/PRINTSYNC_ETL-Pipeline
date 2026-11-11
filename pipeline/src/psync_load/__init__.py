"""Stage 3 — Load (doc: docs/Load/Data-Load-Documentation-for-PRINTSYNC.md).

The last stage of ``psync_nightly_analytics``. Its only input is what Stage 2 published: the eight
``dim_*`` / ``fct_*`` tables in ``psync_analytics`` and the ``transformation_runs`` ledger row for
one approved ``batch_id``. It never opens a connection to PRINTSYNC, never re-extracts a row and
never re-derives a number.

It writes to a separate reporting database, ``psync_warehouse``, and proves the copy agrees with the
handover. Sections referenced in comments are the sections of the load document.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
