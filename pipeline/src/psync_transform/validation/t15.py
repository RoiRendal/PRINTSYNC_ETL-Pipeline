"""T15 — dimension version continuity (doc section 7).

An SCD Type 2 dimension is only useful if, for any date, there is **exactly one** version of a
natural key in force. Break that and the failure is quiet: a fact row joins two product versions and
the revenue is counted twice, with every total still looking plausible.

Three conditions, and it is worth being honest about which ones the schema already enforces:

* ``valid_to > valid_from`` — a CHECK constraint, so this is a run-time assertion that the
  constraint is still there (the same reason Stage 1 keeps V5 and V6).
* one current row per natural key — a partial unique index, likewise an assertion.
* **no two versions overlap** — nothing enforces this. ``valid_to`` is written by the build itself,
  and a bug that closed a version too late would leave two versions in force for a day while both
  constraints stayed satisfied. That is the check this module is really for.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from psync_transform.config import Settings
from psync_transform.db import connect_target
from psync_transform.validation.result import CheckResult

__all__ = ["check_version_continuity"]


@dataclass(frozen=True)
class _Versioned:
    """A dimension that carries versions, and the two keys that describe them."""

    table: str
    key: str
    natural: str


VERSIONED: tuple[_Versioned, ...] = (
    _Versioned("dim_branch", "branch_key", "branch_id"),
    _Versioned("dim_item", "item_key", "item_ref"),
)

_DUPLICATE_CURRENT_SQL = """
select {natural}, count(*)
from public.{table}
where is_current
group by {natural}
having count(*) > 1
limit 5
"""

_OVERLAPPING_SQL = """
select a.{natural}, a.valid_from, b.valid_from
from public.{table} as a
join public.{table} as b
  on a.{natural} = b.{natural}
 and a.{key} < b.{key}
where a.valid_from < coalesce(b.valid_to, 'infinity'::date)
  and b.valid_from < coalesce(a.valid_to, 'infinity'::date)
limit 5
"""

_INVALID_RANGE_SQL = """
select count(*)
from public.{table}
where valid_to is not null
  and valid_to <= valid_from
"""


def check_version_continuity(settings: Settings) -> CheckResult:
    """Exactly one version in force per natural key, with no gaps dressed as overlaps."""
    problems: list[str] = []

    try:
        with connect_target(settings) as conn:
            for spec in VERSIONED:
                duplicates = conn.execute(
                    _DUPLICATE_CURRENT_SQL.format(table=spec.table, natural=spec.natural)
                ).fetchall()
                for natural_key, count in duplicates:
                    problems.append(
                        f"{spec.table}: {count} current versions of {natural_key}"
                    )

                overlaps = conn.execute(
                    _OVERLAPPING_SQL.format(
                        table=spec.table, key=spec.key, natural=spec.natural
                    )
                ).fetchall()
                for natural_key, first_from, second_from in overlaps:
                    problems.append(
                        f"{spec.table}: {natural_key} has versions from "
                        f"{first_from} and {second_from} in force at the same time"
                    )

                invalid = conn.execute(
                    _INVALID_RANGE_SQL.format(table=spec.table)
                ).fetchone()[0]
                if invalid:
                    problems.append(
                        f"{spec.table}: {invalid} version(s) end on or before they start"
                    )
    except psycopg.Error as exc:
        return CheckResult(
            check_id="T15",
            status="FAIL",
            severity="critical",
            message=f"could not read the dimension versions: {exc}",
            error_code="TRF_VERSIONS_UNREADABLE",
        )

    if problems:
        return CheckResult(
            check_id="T15",
            status="FAIL",
            severity="critical",
            message="dimension versions are not continuous: " + "; ".join(problems[:6]),
            error_code="TRF_VERSION_OVERLAP",
        )

    return CheckResult(
        check_id="T15",
        status="PASS",
        severity="critical",
        message=(
            f"{len(VERSIONED)} versioned dimensions hold one version per natural key, "
            "with no overlap"
        ),
    )
