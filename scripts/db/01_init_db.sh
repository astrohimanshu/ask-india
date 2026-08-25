#!/usr/bin/env bash
# Runs once at first container start. The SQL lives in sql/ so the entrypoint does not also run
# it directly without the psql variables. Creates schemas, roles and
# base tables, then loads the seed fixture. Passwords come from the container environment.
set -euo pipefail
psql -v ON_ERROR_STOP=1 \
  -v app_pw="${ASKINDIA_APP_PASSWORD}" \
  -v ro_pw="${ASKINDIA_RO_PASSWORD}" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -f /docker-entrypoint-initdb.d/sql/init_db.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -f /docker-entrypoint-initdb.d/sql/seed.sql
