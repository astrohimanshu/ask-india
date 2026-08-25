#!/usr/bin/env bash
# Verify the public deployment from outside: health, catalogue, one question, one claim.
set -euo pipefail
cd "$(dirname "$0")"; . ./00_vars.sh
API="https://$(az containerapp show -g "$AZ_RG" -n api --query properties.configuration.ingress.fqdn -o tsv)"
WEB="https://$(az containerapp show -g "$AZ_RG" -n web --query properties.configuration.ingress.fqdn -o tsv)"
echo "API $API"; curl -sf "$API/health"; echo
curl -sf "$API/datasets" | python3 -c "import sys,json; print(len(json.load(sys.stdin)), 'datasets')"
curl -sf -m 300 -X POST "$API/ask" -H 'content-type: application/json' \
  -d '{"question": "Which state had the highest literacy rate in the 2011 census?"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'], '|', d['prose'], '|', d['elapsed_seconds'], 's')"
curl -sf -m 300 -X POST "$API/ask" -H 'content-type: application/json' \
  -d '{"question": "India'"'"'s GDP grew 8% in 2024"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'], '|', d['prose'][:160])"
echo "WEB $WEB"; curl -sf "$WEB" | grep -o "<title>[^<]*</title>"
