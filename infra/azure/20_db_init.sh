#!/usr/bin/env bash
# Initialise the managed database exactly like the local one: schemas, roles, migrations, then
# ingest the datasets and index the dictionaries from this machine. Idempotent where possible.
set -euo pipefail
cd "$(dirname "$0")"; . ./00_vars.sh
: "${PG_ADMIN_PASSWORD:?}" "${ASKINDIA_APP_PASSWORD:?}" "${ASKINDIA_RO_PASSWORD:?}"
PG_HOST="$AZ_PG.postgres.database.azure.com"
MYIP=$(curl -s https://api.ipify.org)
az postgres flexible-server firewall-rule create -g "$AZ_RG" -n "$AZ_PG" -r laptop --start-ip-address "$MYIP" --end-ip-address "$MYIP" -o none
ADMIN="postgresql://${AZ_PG_ADMIN}:${PG_ADMIN_PASSWORD}@${PG_HOST}:5432/askindia?sslmode=require"
cd ../..
if ! uv run python -c "import sys,psycopg; sys.exit(0 if psycopg.connect('$ADMIN').execute(\"select 1 from pg_roles where rolname='askindia_app'\").fetchone() else 1)"; then
  # Managed Postgres has no psql here and no superuser: the same init SQL is applied through
  # psycopg with the psql variables substituted.
  uv run scripts/db/apply_sql.py "$ADMIN" scripts/db/sql/init_db.sql app_pw="$ASKINDIA_APP_PASSWORD" ro_pw="$ASKINDIA_RO_PASSWORD"
  uv run scripts/db/apply_sql.py "$ADMIN" scripts/db/sql/seed.sql
fi
export DATABASE_URL="postgresql://askindia_app:${ASKINDIA_APP_PASSWORD}@${PG_HOST}:5432/askindia?sslmode=require"
export DATABASE_URL_RO="postgresql://askindia_ro:${ASKINDIA_RO_PASSWORD}@${PG_HOST}:5432/askindia?sslmode=require"
uv run python -m askindia_ingestion.migrate
uv run scripts/ingest.py --snapshots data/snapshots
uv run scripts/index_dictionaries.py
uv run scripts/check_dictionaries.py | tail -1
