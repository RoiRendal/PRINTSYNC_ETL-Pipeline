"""Column constants shared by the loader and its checks.

They live here rather than in either module so that ``loader`` and ``validation`` can both use them
without importing each other.
"""

from __future__ import annotations

__all__ = ["LOAD_COLUMNS"]

# The three bookkeeping columns the warehouse adds to every reporting table (doc section 2.4).
# They are metadata about the load, not business data, and are excluded from the source comparison.
LOAD_COLUMNS = frozenset({"load_batch_id", "load_run_id", "loaded_at"})
