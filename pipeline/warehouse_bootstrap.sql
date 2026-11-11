-- One-off warehouse bootstrap (doc sections 1.2, 1.5 and 2).
--
-- Run ONCE, as the instance owner, BEFORE `python -m psync_load.db migrate`.
-- This file is deliberately outside pipeline/warehouse_migrations/: CREATE DATABASE cannot run
-- inside a transaction block, and the migration applier wraps every file in one.
--
-- No password appears here. Set it out of band, e.g. `\password psync_loader` in psql, or an
-- ALTER ROLE issued from the operator's own session. The DSN in pipeline/.env (git-ignored) is the
-- only place the credential is written.
--
-- CONNECT as the instance owner, then:
--   CREATE DATABASE ...          (statement 1, outside any transaction)
--   CREATE ROLE ...              (statement 2)
--   \connect psync_warehouse     (then statements 3-5 in that database)

CREATE DATABASE psync_warehouse OWNER psync_pipeline;

CREATE ROLE psync_loader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;

GRANT CONNECT ON DATABASE psync_warehouse TO psync_loader;

-- Everything below runs while connected to psync_warehouse.
GRANT USAGE ON SCHEMA public TO psync_loader;

-- The reporting tables do not exist yet at bootstrap time. Default privileges grant access to the
-- tables the migration will create, without granting any DDL.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO psync_loader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO psync_loader;

-- psync_pipeline is the owner: it created this database, it applies the migrations, and it is the
-- role Stages 1 and 2 use to write their own output. Stage 3 uses it only to read that output, in a
-- session that sets default_transaction_read_only = on, and to apply migrations under a one-off
-- DSN override. The nightly load never sees this connection string — it uses psync_loader above.
