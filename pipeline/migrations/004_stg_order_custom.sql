-- 004_stg_order_custom.sql
--
-- Adds the custom-order flag to the order staging table (specification section 2.4, revision 1.5).
--
-- Why a new file rather than an edit to an applied one: applied migrations are immutable — the
-- applier records a checksum and refuses to run a file that changed after it was applied. A
-- correction is always a new file.
--
-- Why the column is nullable: the source column is NOT NULL with a default of false, but this
-- table already holds rows from earlier runs. Every row written from now on carries the flag.
--
-- Apply with the pipeline's own migrator, which records the version and checksum:
--   python -m psync_extract.db migrate

BEGIN;

ALTER TABLE stg_orders
    ADD COLUMN IF NOT EXISTS is_custom boolean;

COMMENT ON COLUMN stg_orders.is_custom IS
    'True when the order came in as a custom job rather than off the shelf (source: '
    'orders.is_custom). Transformation reports it as custom_order_count. Added in specification '
    'revision 1.5.';

COMMIT;
