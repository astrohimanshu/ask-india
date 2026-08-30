-- Roles exactly as the real database defines them. The read-only role's settings are the
-- product's security guarantee, so a demo that skipped them would misrepresent it.
\set ON_ERROR_STOP on
CREATE EXTENSION IF NOT EXISTS vector;

CREATE ROLE askindia_app LOGIN PASSWORD :'app_pw';
CREATE ROLE askindia_ro  LOGIN PASSWORD :'ro_pw';
GRANT CONNECT ON DATABASE askindia TO askindia_app, askindia_ro;

ALTER ROLE askindia_ro SET default_transaction_read_only = on;
ALTER ROLE askindia_ro SET statement_timeout = '10s';
ALTER ROLE askindia_ro SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE askindia_ro SET search_path = data, public;
ALTER ROLE askindia_app SET search_path = data, meta, rag, app, public;
