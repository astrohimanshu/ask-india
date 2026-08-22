-- The read-only role may read the dataset catalogue (never the audit trail).
GRANT USAGE ON SCHEMA meta TO askindia_ro;
GRANT SELECT ON meta.datasets TO askindia_ro;
