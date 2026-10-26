"""The expected shape of the PRINTSYNC source (doc section 2).

This is the contract as data: the seven tables the extraction reads, the columns it takes from
each, and the type family each column must have. Check V2 compares the live database against this
registry **before** any row is read, so a migration that renames or retypes a column stops the run
instead of silently producing wrong numbers (doc section 6.4).

Only the columns the extraction selects are listed. A column added at source is ignored: the
extractors name their columns explicitly, so an additive migration cannot break a run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["Column", "ColumnType", "SOURCE_SCHEMA", "TableSpec", "TABLES"]

# Type families, not exact source spellings: `numeric` and `numeric(12,2)` are both NUMERIC,
# because a precision change does not change how a value is read. Anything outside these six
# families is drift (doc section 6.4).
ColumnType = Literal["uuid", "text", "numeric", "integer", "timestamptz", "boolean"]


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[Column, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


SOURCE_SCHEMA: tuple[TableSpec, ...] = (
    # 2.1 - one row per completed sale. The spine of the pipeline.
    TableSpec(
        "sales_transactions",
        (
            Column("id", "uuid"),
            Column("status", "text"),
            Column("subtotal", "numeric"),
            Column("discount", "numeric"),
            Column("tax", "numeric"),
            Column("total", "numeric"),
            Column("payment_method", "text"),
            Column("created_at", "timestamptz"),
            Column("voided_at", "timestamptz"),
            Column("customer_id", "uuid"),
            Column("branch_id", "uuid"),
        ),
    ),
    # 2.2 - the items on each sale. No timestamp of its own (P3). `name` is the product identity
    # Transformation uses: the catalogue link is null on 93.4% of lines (doc section 2.2, rev. 1.4).
    TableSpec(
        "sales_transaction_items",
        (
            Column("id", "uuid"),
            Column("transaction_id", "uuid"),
            Column("inventory_item_id", "uuid"),
            Column("name", "text"),
            Column("quantity", "integer"),
            Column("unit_price", "numeric"),
            Column("line_discount", "numeric"),
        ),
    ),
    # 2.3 - how each sale was paid; a sale may have more than one payment.
    TableSpec(
        "payments",
        (
            Column("id", "uuid"),
            Column("transaction_id", "uuid"),
            Column("amount", "numeric"),
            Column("method", "text"),
            Column("status", "text"),
            Column("created_at", "timestamptz"),
            Column("voided_at", "timestamptz"),
        ),
    ),
    # 2.4 - custom and production jobs. Windowed on updated_at. `is_custom` distinguishes the
    # custom jobs from the shelf (doc section 2.4, revision 1.5).
    TableSpec(
        "orders",
        (
            Column("id", "uuid"),
            Column("status", "text"),
            Column("amount", "numeric"),
            Column("is_custom", "boolean"),
            Column("customer_id", "uuid"),
            Column("created_at", "timestamptz"),
            Column("updated_at", "timestamptz"),
            Column("branch_id", "uuid"),
        ),
    ),
    # 2.5 - the product catalogue, extracted in full every run.
    TableSpec(
        "inventory_items",
        (
            Column("id", "uuid"),
            Column("sku", "text"),
            Column("name", "text"),
            Column("category", "text"),
            Column("price", "numeric"),
            Column("cost_price", "numeric"),
            Column("stock", "integer"),
            Column("reorder_level", "integer"),
            Column("uom", "text"),
            Column("updated_at", "timestamptz"),
            Column("branch_id", "uuid"),
        ),
    ),
    # 2.6 - shop configuration, one row per branch (L5). Source key is an integer.
    TableSpec(
        "business_settings",
        (
            Column("id", "integer"),
            Column("branch_id", "uuid"),
            Column("vat_rate", "numeric"),
            Column("currency_symbol", "text"),
            Column("time_zone", "text"),
        ),
    ),
    # 2.7 - a four-column lookup so branch_id means something.
    TableSpec(
        "branches",
        (
            Column("id", "uuid"),
            Column("code", "text"),
            Column("name", "text"),
            Column("is_active", "boolean"),
        ),
    ),
)

TABLES: tuple[str, ...] = tuple(spec.name for spec in SOURCE_SCHEMA)
