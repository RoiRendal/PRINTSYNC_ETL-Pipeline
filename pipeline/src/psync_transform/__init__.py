"""PRINTSYNC nightly analytics batch pipeline - Stage 2 (Transform).

This package turns the extraction handover into the business-ready dimensional tables the Load
stage publishes. It reads nothing from PRINTSYNC: its input is the seven ``stg_*`` tables in the
pipeline's own database, selected by ``run_id`` and ``business_date`` (extraction documentation,
section 7.3). It writes only to ``psync_analytics``.

Every section reference (``§x.y``) in this package's docstrings points at
``docs/Transformation/Data-Transformation-Documentation-for-PRINTSYNC.md``, which is the contract
this code implements. Where a rule has an ID (``C-02``, ``S-01``, ``B-10``, ``T4``), the ID is the
one that document defines.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
