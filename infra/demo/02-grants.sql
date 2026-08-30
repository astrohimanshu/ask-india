-- Re-applied after the restore: the dump is taken --no-owner --no-privileges, so it carries
-- data but not grants. These mirror the real database exactly, including the least-privilege
-- detail that the read-only role sees meta.datasets (the catalogue the UI lists) and nothing
-- else in meta -- not the ingestion audit trail, not the migration ledger.
\set ON_ERROR_STOP on

GRANT USAGE ON SCHEMA data, rag, meta TO askindia_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA data, rag TO askindia_ro;
GRANT SELECT ON meta.datasets TO askindia_ro;

GRANT USAGE ON SCHEMA data, meta, rag, app TO askindia_app;
GRANT ALL ON ALL TABLES IN SCHEMA data, meta, rag, app TO askindia_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA data, meta, rag, app TO askindia_app;
