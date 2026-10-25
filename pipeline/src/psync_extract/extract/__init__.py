"""The extractors: one module per source table (doc section 2).

Each extractor selects the columns the contract lists, restricted to the run's read range, and
streams the rows through a server-side cursor. None of them write anything, and none of them clean
anything — Stage 1 copies, it does not interpret (doc section 7.3).
"""
