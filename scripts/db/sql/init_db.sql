-- Ask India database layout.
--
-- Schemas
--   data  ingested government datasets; the only schema the agent may query
--   meta  dataset registry and ingestion audit trail
--   rag   data-dictionary chunks and embeddings for schema retrieval
--   app   application state: conversation checkpoints, feedback, verdict log, result cache
--
-- Roles
--   askindia_app  owns every schema; used by ingestion and the API for application state
--   askindia_ro   SELECT-only on data and rag, read-only transactions, 10 s statement timeout;
--                 the ONLY role agent-generated SQL is ever executed as
--
-- Invoked with psql variables :app_pw and :ro_pw (see 01_init_db.sh).

\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS vector;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE askindia FROM PUBLIC;

CREATE ROLE askindia_app LOGIN PASSWORD :'app_pw';
CREATE ROLE askindia_ro  LOGIN PASSWORD :'ro_pw';

GRANT CONNECT ON DATABASE askindia TO askindia_app, askindia_ro;

CREATE SCHEMA data AUTHORIZATION askindia_app;
CREATE SCHEMA meta AUTHORIZATION askindia_app;
CREATE SCHEMA rag  AUTHORIZATION askindia_app;
CREATE SCHEMA app  AUTHORIZATION askindia_app;

-- Read-only role: usage on the queryable schemas, SELECT on present and future tables.
GRANT USAGE ON SCHEMA data, rag TO askindia_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE askindia_app IN SCHEMA data GRANT SELECT ON TABLES TO askindia_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE askindia_app IN SCHEMA rag  GRANT SELECT ON TABLES TO askindia_ro;
ALTER ROLE askindia_ro SET default_transaction_read_only = on;
ALTER ROLE askindia_ro SET statement_timeout = '10s';
ALTER ROLE askindia_ro SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE askindia_ro SET search_path = data, public;

ALTER ROLE askindia_app SET search_path = data, meta, rag, app, public;

-- Everything below is created as the application role so it owns the objects.
SET ROLE askindia_app;

-- One row per ingestion attempt. status: loaded | quarantined | failed.
CREATE TABLE meta.dataset_runs (
    id               bigserial PRIMARY KEY,
    dataset          text        NOT NULL,
    dataset_version  text        NOT NULL,
    source_url       text,
    fetched_at       timestamptz NOT NULL DEFAULT now(),
    raw_sha256       text,
    row_count        integer,
    status           text        NOT NULL CHECK (status IN ('loaded', 'quarantined', 'failed')),
    error            text,
    validation       jsonb,
    CONSTRAINT dataset_runs_unique_version UNIQUE (dataset, dataset_version, fetched_at)
);

-- Live catalogue: which version of each dataset is the one answers are computed from.
CREATE TABLE meta.datasets (
    dataset          text PRIMARY KEY,
    table_name       text        NOT NULL,
    title            text        NOT NULL,
    source_org       text        NOT NULL,
    source_url       text,
    cadence          text,
    coverage_from    date,
    coverage_to      date,
    current_version  text        NOT NULL,
    is_seed          boolean     NOT NULL DEFAULT false,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- DGCA monthly airline traffic and operating statistics (per airline, per month, per segment).
-- Same shape the ingestion loader writes; dataset_version 'seed-v0' marks fixture rows.
CREATE TABLE data.dgca_airline_traffic (
    id                          bigserial PRIMARY KEY,
    period                      date           NOT NULL,   -- first day of the month
    airline                     text           NOT NULL,
    segment                     text           NOT NULL,   -- scheduled_domestic, scheduled_international, ...
    departures                  integer,
    hours_flown                 numeric(12, 2),
    km_flown_thousand           numeric(14, 2),
    passengers_carried          bigint         CHECK (passengers_carried >= 0),
    passenger_km_thousand       numeric(16, 2),
    available_seat_km_thousand  numeric(16, 2),
    passenger_load_factor_pct   numeric(6, 2)  CHECK (passenger_load_factor_pct BETWEEN 0 AND 100),
    dataset_version             text           NOT NULL,
    UNIQUE (period, airline, segment, dataset_version)
);
CREATE INDEX ON data.dgca_airline_traffic (period);
CREATE INDEX ON data.dgca_airline_traffic (airline);

RESET ROLE;
