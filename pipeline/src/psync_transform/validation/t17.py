"""T17 — the product identity is sound (doc section 7).

``dim_item`` identifies a product by ``'name:' || normalised(name)`` (rule S-12), because
``inventory_item_id`` is null on 93.4 % of sale lines. That makes the identity **derived**, and a
derived key can drift from the value it is derived from: one code path trims and another does not,
and the same product becomes two rows that no unique index can catch, because their ``item_ref``
values genuinely differ.

The unique index already guarantees one current row per ``item_ref``. That is exactly why this check
does not test it — it would pass forever. It tests the two things the index cannot:

* every current row's ``item_ref`` equals ``'name:' || normalised(item_name)`` — the identity is
  still what it claims to be;
* no two current rows share a normalised name — the case the index misses when two refs disagree
  about spacing or case.

Severity is critical. A split product halves its own demand history, and the reorder recommendation
built on it is wrong in the direction that runs a shelf empty.
"""

from __future__ import annotations

import psycopg

from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.validation.result import CheckResult

__all__ = ["check_item_identity"]

# The same normalisation as rule S-12, written in SQL once so the check and the build cannot
# disagree about what "normalised" means.
_NORMALISED_NAME = r"regexp_replace(btrim(lower(item_name)), '\s+', ' ', 'g')"

_DRIFTED_REF_SQL = f"""
select item_ref, item_name
from public.dim_item
where is_current
  and item_ref <> 'name:' || {_NORMALISED_NAME}
limit 5
"""

_SHARED_NAME_SQL = f"""
select {_NORMALISED_NAME} as normalised_name, count(*), string_agg(item_ref, ' | ' order by item_ref)
from public.dim_item
where is_current
group by 1
having count(*) > 1
limit 5
"""


def check_item_identity(settings: Settings) -> CheckResult:
    """Every current product's key is derived from its name, and no two share a name."""
    problems: list[str] = []

    try:
        with connect_target(settings) as conn:
            for item_ref, item_name in conn.execute(_DRIFTED_REF_SQL).fetchall():
                problems.append(
                    f"{item_ref} does not match its name {item_name!r}"
                )

            for normalised, count, refs in conn.execute(_SHARED_NAME_SQL).fetchall():
                problems.append(
                    f"{count} current products share the name {normalised!r} ({refs})"
                )
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T17",
            status="FAIL",
            severity="critical",
            message=f"could not read the item dimension: {exc}",
            error_code="TRF_ITEM_IDENTITY_UNREADABLE",
        )

    if problems:
        return CheckResult(
            check_id="T17",
            status="FAIL",
            severity="critical",
            message="the product identity has drifted: " + "; ".join(problems[:6]),
            error_code="TRF_ITEM_IDENTITY_SPLIT",
        )

    return CheckResult(
        check_id="T17",
        status="PASS",
        severity="critical",
        message="every current product's key matches its name, and no two share one",
    )
