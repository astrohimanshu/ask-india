#!/usr/bin/env bash
# Initialise the managed database exactly like the local one: schemas, roles, migrations, then
# ingest the datasets and index the dictionaries from this machine. Idempotent where possible.
set -euo pipefail
cd "$(dirname "$0")"; . ./00_vars.sh
: "${PG_ADMIN_PASSWORD:?}" "${ASKINDIA_APP_PASSWORD:?}" "${ASKINDIA_RO_PASSWORD:?}"
PG_HOST="$AZ_PG.postgres.database.azure.com"
MYIP=$(curl -s https://api.ipify.org)
az postgres flexible-server firewall-rule create -g "$AZ_RG" -n "$AZ_PG" -r laptop --start-ip-address "$MYIP" --end-ip-address "$MYIP" -o none
export PGPASSWORD="$PG_ADMIN_PASSWORD"
ADMIN="postgresql://${AZ_PG_ADMIN}@${PG_HOST}:5432/askindia?sslmode=require"
if ! psql "$ADMIN" -Atc "select 1 from pg_roles where rolname='askindia_app'" | grep -q 1; then
  # Managed Postgres: the admin is not a superuser, so the extension is created explicitly and
  # objects are created as the admin, then handed to askindia_app.
  psql "$ADMIN" -v ON_ERROR_STOP=1 -v app_pw="$ASKINDIA_APP_PASSWORD" -v ro_pw="$ASKINDIA_RO_PASSWORD" \
    -f ../../scripts/db/sql/init_db.sql
  psql "$ADMIN" -v ON_ERROR_STOP=1 -f ../../scripts/db/sql/seed.sql
fi
export DATABASE_URL="postgresql://askindia_app:${ASKINDIA_APP_PASSWORD}@${PG_HOST}:5432/askindia?sslmode=require"
export DATABASE_URL_RO="postgresql://askindia_ro:${ASKINDIA_RO_PASSWORD}@${PG_HOST}:5432/askindia?sslmode=require"
cd ../..
uv run python -m askindia_ingestion.migrate
uv run scripts/ingest.py --snapshots data/snapshots
uv run scripts/index_dictionaries.py
uv run scripts/check_dictionaries.py | tail -1
