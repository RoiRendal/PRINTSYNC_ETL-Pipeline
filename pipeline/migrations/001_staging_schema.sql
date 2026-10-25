-- 001_staging_schema.sql
--
-- The pipeline's own database: psync_analytics.
--
-- Creates the seven staging tables and the pipeline_runs metadata table. Nothing in this file
-- touches the PRINTSYNC database: the pipeline reads PRINTSYNC over a read-only login and writes
-- only here (specification sections 1.6 and 6.1).
--
-- Apply against an empty psync_analytics database:
--   psql "$PSYNC_TARGET_DSN" -f pipeline/migrations/001_staging_schema.sql
--
-- Conventions (section 6.2):
--   * the source primary key is renamed to source_id;
--   * join keys keep their source names (transaction_id, inventory_item_id, branch_id,
--     customer_id), so a join reads the same on both sides;
--   * every table carries run_id, business_date and extracted_at.
--
-- Money is numeric(14,2) and every moment in time is timestamptz (section 6.1).

BEGIN;

-- =============================================================================================
-- sales_transactions -> stg_sales_transactions                        (section 2.1)
-- =============================================================================================
CREATE TABLE stg_sales_transactions (
    run_id          uuid          NOT NULL,
    business_date   date          NOT NULL,
    extracted_at    timestamptz   NOT NULL,
    source_id       uuid          NOT NULL,
    status          text          NOT NULL,
    subtotal        numeric(14,2) NOT NULL,
    discount        numeric(14,2) NOT NULL,
    tax             numeric(14,2) NOT NULL,
    total           numeric(14,2) NOT NULL,
    payment_method  text          NOT NULL,
    created_at      timestamptz   NOT NULL,
    voided_at       timestamptz,
    customer_id     uuid,
    branch_id       uuid          NOT NULL,
    CONSTRAINT stg_sales_transactions_pkey PRIMARY KEY (run_id, source_id)
);

-- =============================================================================================
-- sales_transaction_items -> stg_sales_transaction_items              (section 2.2)
-- No timestamp of its own: windowed through its parent sale (section 1.3, P3).
-- =============================================================================================
CREATE TABLE stg_sales_transaction_items (
    run_id            uuid          NOT NULL,
    business_date     date          NOT NULL,
    extracted_at      timestamptz   NOT NULL,
    source_id         uuid          NOT NULL,
    transaction_id    uuid          NOT NULL,
    inventory_item_id uuid,
    quantity          integer       NOT NULL,
    unit_price        numeric(14,2) NOT NULL,
    line_discount     numeric(14,2) NOT NULL,
    CONSTRAINT stg_sales_transaction_items_pkey PRIMARY KEY (run_id, source_id)
);

CREATE INDEX stg_sales_transaction_items_txn_idx
    ON stg_sales_transaction_items (run_id, transaction_id);

-- =============================================================================================
-- payments -> stg_payments                                            (section 2.3)
-- =============================================================================================
CREATE TABLE stg_payments (
    run_id         uuid          NOT NULL,
    business_date  date          NOT NULL,
    extracted_at   timestamptz   NOT NULL,
    source_id      uuid          NOT NULL,
    transaction_id uuid          NOT NULL,
    amount         numeric(14,2) NOT NULL,
    method         text          NOT NULL,
    status         text          NOT NULL,
    created_at     timestamptz   NOT NULL,
    voided_at      timestamptz,
    CONSTRAINT stg_payments_pkey PRIMARY KEY (run_id, source_id)
);

CREATE INDEX stg_payments_txn_idx
    ON stg_payments (run_id, transaction_id);

-- =============================================================================================
-- orders -> stg_orders                                                (section 2.4)
-- =============================================================================================
CREATE TABLE stg_orders (
    run_id         uuid          NOT NULL,
    business_date  date          NOT NULL,
    extracted_at   timestamptz   NOT NULL,
    source_id      uuid          NOT NULL,
    status         text          NOT NULL,
    amount         numeric(14,2) NOT NULL,
    customer_id    uuid,
    created_at     timestamptz   NOT NULL,
    updated_at     timestamptz   NOT NULL,
    branch_id      uuid          NOT NULL,
    CONSTRAINT stg_orders_pkey PRIMARY KEY (run_id, source_id)
);

-- =============================================================================================
-- inventory_items -> stg_inventory_items                              (section 2.5)
-- Full snapshot every run, not incremental (section 1.3).
-- =============================================================================================
CREATE TABLE stg_inventory_items (
    run_id         uuid          NOT NULL,
    business_date  date          NOT NULL,
    extracted_at   timestamptz   NOT NULL,
    source_id      uuid          NOT NULL,
    sku            text          NOT NULL,
    name           text          NOT NULL,
    category       text          NOT NULL,
    price          numeric(14,2) NOT NULL,
    cost_price     numeric(14,2) NOT NULL,
    stock          integer       NOT NULL,
    reorder_level  integer       NOT NULL,
    uom            text          NOT NULL,
    updated_at     timestamptz   NOT NULL,
    branch_id      uuid          NOT NULL,
    CONSTRAINT stg_inventory_items_pkey PRIMARY KEY (run_id, source_id)
);

-- =============================================================================================
-- business_settings -> stg_business_settings                          (section 2.6)
-- One row per branch; source_id is an integer here, unlike every other table.
-- =============================================================================================
CREATE TABLE stg_business_settings (
    run_id           uuid          NOT NULL,
    business_date    date          NOT NULL,
    extracted_at     timestamptz   NOT NULL,
    source_id        integer       NOT NULL,
    branch_id        uuid          NOT NULL,
    vat_rate         numeric(14,2) NOT NULL,
    currency_symbol  text          NOT NULL,
    time_zone        text          NOT NULL,
    CONSTRAINT stg_business_settings_pkey PRIMARY KEY (run_id, source_id)
);

-- =============================================================================================
-- branches -> stg_branches                                            (section 2.7)
-- =============================================================================================
CREATE TABLE stg_branches (
    run_id         uuid          NOT NULL,
    business_date  date          NOT NULL,
    extracted_at   timestamptz   NOT NULL,
    source_id      uuid          NOT NULL,
    code           text          NOT NULL,
    name           text          NOT NULL,
    is_active      boolean       NOT NULL,
    CONSTRAINT stg_branches_pkey PRIMARY KEY (run_id, source_id)
);

-- =============================================================================================
-- pipeline_runs                                                       (section 4)
--
-- One row per source table per run, plus one run-level summary row. The run-level row is the
-- one whose table_name is null; it carries the run's overall status and validation summary.
--
-- The natural key is (run_id, COALESCE(table_name, '__run__')), enforced by the unique index
-- below. A surrogate id column is deliberately not added: section 4 defines the fields, and an
-- id would be a column the contract does not describe.
-- =============================================================================================
CREATE TABLE pipeline_runs (
    run_id                       uuid          NOT NULL,
    run_key                      text          NOT NULL,
    pipeline_name                text          NOT NULL,
    business_date                date          NOT NULL,
    table_name                   text,
    extraction_started_at        timestamptz,
    extraction_ended_at          timestamptz,
    extraction_duration_seconds  integer,
    extraction_window_start      timestamptz,
    extraction_window_end        timestamptz,
    lookback_days                integer,
    extraction_status            text          NOT NULL,
    rows_read                    integer,
    rows_extracted               integer,
    rows_rejected                integer,
    validation_results           jsonb,
    error_code                   text,
    error_message                text,
    reject_reason                text,
    CONSTRAINT pipeline_runs_status_check
        CHECK (extraction_status IN ('running', 'success', 'failed', 'skipped'))
);

CREATE UNIQUE INDEX pipeline_runs_run_table_key
    ON pipeline_runs (run_id, COALESCE(table_name, '__run__'));

CREATE INDEX pipeline_runs_run_key_idx
    ON pipeline_runs (run_key);

CREATE INDEX pipeline_runs_business_date_idx
    ON pipeline_runs (business_date);

COMMIT;
