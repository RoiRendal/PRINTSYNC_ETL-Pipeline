"""Database access for the pipeline.

Everything that talks to a database lives here. Two databases are involved and they are never
confused: the **source** (PRINTSYNC's operational database, reached read-only) and the
**target** (the pipeline's own database, ``psync_analytics``), which is the only one the
pipeline ever writes to (doc section 1.6).
"""
