#!/usr/bin/env bash
# Load a data snapshot into the demo database. Idempotent: safe to re-run.
#
#   ./restore.sh [path-to-dump]        default: ~/demo/askindia-data.dump
#
# The dump is data, not code: it is never committed. Take a fresh one with
#   docker exec askindia-db-1 pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
#     --no-owner --no-privileges -Fc > ~/demo/askindia-data.dump
set -euo pipefail
cd "$(dirname "$0")"
DUMP="${1:-$HOME/demo/askindia-data.dump}"
PW="${DEMO_PG_PASSWORD:-demo}"

[ -f "$DUMP" ] || { echo "no dump at $DUMP — see the header for how to take one"; exit 1; }
C="$(docker compose -f compose.demo.yaml ps -q db)"
[ -n "$C" ] || { echo "db is not running: docker compose -f compose.demo.yaml up -d db"; exit 1; }

echo "waiting for postgres..."
until docker exec "$C" pg_isready -U postgres -d askindia -q 2>/dev/null; do sleep 1; done

echo "creating roles..."
docker exec -i "$C" psql -U postgres -d askindia -q \
  -v app_pw="$PW" -v ro_pw="$PW" < 01-roles.sql 2>&1 | grep -v "already exists" || true

echo "restoring data from $DUMP ..."
docker exec -i "$C" pg_restore -U postgres -d askindia --no-owner --no-privileges \
  --clean --if-exists < "$DUMP" 2>&1 | grep -Ev "does not exist|already exists" || true

echo "applying grants..."
docker exec -i "$C" psql -U postgres -d askindia -q < 02-grants.sql

echo
echo "loaded:"
docker exec "$C" psql -U postgres -d askindia -tA -F'  ' -c "
SELECT 'census_2011_pca', count(*) FROM data.census_2011_pca
UNION ALL SELECT 'imd_subdivision_rainfall', count(*) FROM data.imd_subdivision_rainfall
UNION ALL SELECT 'fuel_prices_metro', count(*) FROM data.fuel_prices_metro
UNION ALL SELECT 'crop_production', count(*) FROM data.crop_production
UNION ALL SELECT 'dgca_airline_traffic', count(*) FROM data.dgca_airline_traffic
UNION ALL SELECT 'aai_airport_traffic', count(*) FROM data.aai_airport_traffic
ORDER BY 1;"
echo "retrieval chunks: $(docker exec "$C" psql -U postgres -d askindia -tAc 'SELECT count(*) FROM rag.chunks')"
