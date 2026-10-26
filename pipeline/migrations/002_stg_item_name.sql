-- 002_stg_item_name.sql
--
-- Adds the product name to the sale-line staging table (specification section 2.2, revision 1.4).
--
-- Why a new file rather than an edit to 001: an applied migration is immutable — the applier
-- records a checksum and refuses to run a file that changed after it was applied (section 6.1).
-- A correction is always a new file.
--
-- Why the column is nullable: the source column is NOT NULL, but this table already holds rows
-- from earlier runs, and adding a NOT NULL column to a populated table would need either a default
-- (a value the pipeline invented) or a backfill (a value the source never held). Every row written
-- from now on carries the name; a row that somehow does not is quarantined by Transformation
-- (rule C-01) instead of being given a made-up one.
--
-- Apply with the pipeline's own migrator, which records the version and checksum:
--   python -m psync_extract.db migrate
--
-- Or by hand:
--   psql "$PSYNC_TARGET_DSN" -f pipeline/migrations/002_stg_item_name.sql

BEGIN;

ALTER TABLE stg_sales_transaction_items
    ADD COLUMN IF NOT EXISTS name text;

COMMENT ON COLUMN stg_sales_transaction_items.name IS
    'The product name as sold (source: sales_transaction_items.name). Transformation identifies '
    'a product by this name, because inventory_item_id is null on 93.4% of lines. Added in '
    'specification revision 1.4.';

COMMIT;
