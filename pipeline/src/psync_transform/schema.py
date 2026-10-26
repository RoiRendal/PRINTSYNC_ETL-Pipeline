"""The shape of the extraction handover (doc sections 1.1 and 6.4).

This is the input contract as data: the seven staging tables this stage reads, every column it
takes from each, and the type family each column must have. Check T1 compares the live database
against this registry **before** a single row is read, so a staging table built from an older
revision stops the batch instead of producing a demand table with 93 % of its revenue unattributed.

The three control columns come first in every table because Stage 1 writes them first
(extraction documentation, section 6.1). They are declared once and prepended, so a table cannot
quietly disagree with its neighbours about what ``business_date`` is.

Type families, not exact spellings: ``numeric`` and ``numeric(14,2)`` are both NUMERIC, because a
precision change does not change how a value is read. A column added to staging is ignored — every
rule names the columns it uses, so an additive change cannot alter the output (doc section 6.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "CONTROL_COLUMNS",
    "STAGING_SCHEMA",
    "STAGING_TABLES",
    "Column",
    "ColumnType",
    "StagingTable",
]

ColumnType = Literal[
    "uuid", "text", "numeric", "integer", "timestamptz", "date", "boolean", "jsonb"
]


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType


@dataclass(frozen=True)
class StagingTable:
    """One staging table, and the source table whose counts the handover reports it under."""

    source: str
    staging: str
    columns: tuple[Column, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


# Written by Stage 1 on every row of every staging table (extraction documentation, section 6.1).
CONTROL_COLUMNS: tuple[Column, ...] = (
    Column("run_id", "uuid"),
    Column("business_date", "date"),
    Column("extracted_at", "timestamptz"),
)

STAGING_SCHEMA: tuple[StagingTable, ...] = (
    StagingTable(
        "sales_transactions",
        "stg_sales_transactions",
        CONTROL_COLUMNS
        + (
            Column("source_id", "uuid"),
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
    StagingTable(
        "sales_transaction_items",
        "stg_sales_transaction_items",
        CONTROL_COLUMNS
        + (
            Column("source_id", "uuid"),
            Column("transaction_id", "uuid"),
            Column("inventory_item_id", "uuid"),
            # The product name. Revision 1.4 of the extraction contract; without it 93.4% of lines
            # have no product identity (doc finding F-02, requirement D1).
            Column("name", "text"),
            Column("quantity", "integer"),
            Column("unit_price", "numeric"),
            Column("line_discount", "numeric"),
        ),
    ),
    StagingTable(
        "payments",
        "stg_payments",
        CONTROL_COLUMNS
        + (
            Column("source_id", "uuid"),
            Column("transaction_id", "uuid"),
            Column("amount", "numeric"),
            Column("method", "text"),
            Column("status", "text"),
            Column("created_at", "timestamptz"),
            Column("voided_at", "timestamptz"),
        ),
    ),
    StagingTable(
        "orders",
        "stg_orders",
        CONTROL_COLUMNS
        + (
            Column("source_id", "uuid"),
            Column("status", "text"),
            Column("amount", "numeric"),
            Column("customer_id", "uuid"),
            Column("created_at", "timestamptz"),
            Column("updated_at", "timestamptz"),
            Column("branch_id", "uuid"),
        ),
    ),
    StagingTable(
        "inventory_items",
        "stg_inventory_items",
        CONTROL_COLUMNS
        + (
            Column("source_id", "uuid"),
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
    StagingTable(
        "business_settings",
        "stg_business_settings",
        CONTROL_COLUMNS
        + (
            # An integer, unlike every other staging key — the source's own key is an integer.
            Column("source_id", "integer"),
            Column("branch_id", "uuid"),
            Column("vat_rate", "numeric"),
            Column("currency_symbol", "text"),
            Column("time_zone", "text"),
        ),
    ),
    StagingTable(
        "branches",
        "stg_branches",
        CONTROL_COLUMNS
        + (
            Column("source_id", "uuid"),
            Column("code", "text"),
            Column("name", "text"),
            Column("is_active", "boolean"),
        ),
    ),
)

# Source table -> staging table. The handover reports its counts under the source name, so the two
# have to be joinable by name.
STAGING_TABLES: dict[str, str] = {
    spec.source: spec.staging for spec in STAGING_SCHEMA
}
