#!/usr/bin/env bash
# Monthly budget alert at $30 with 50/80/100 % notifications.
set -euo pipefail
cd "$(dirname "$0")"; . ./00_vars.sh
SUB=$(az account show --query id -o tsv)
START=$(date -u +%Y-%m-01)
az rest --method PUT \
  --url "https://management.azure.com/subscriptions/${SUB}/providers/Microsoft.Consumption/budgets/askindia-monthly?api-version=2023-05-01" \
  --body "$(cat <<JSON
{"properties":{"category":"Cost","amount":30,"timeGrain":"Monthly",
 "timePeriod":{"startDate":"${START}T00:00:00Z","endDate":"2027-12-01T00:00:00Z"},
 "notifications":{
  "p50":{"enabled":true,"operator":"GreaterThan","threshold":50,"contactEmails":["${BUDGET_EMAIL}"],"thresholdType":"Actual"},
  "p80":{"enabled":true,"operator":"GreaterThan","threshold":80,"contactEmails":["${BUDGET_EMAIL}"],"thresholdType":"Actual"},
  "p100":{"enabled":true,"operator":"GreaterThan","threshold":100,"contactEmails":["${BUDGET_EMAIL}"],"thresholdType":"Actual"}}}}
JSON
)" -o none
echo "budget armed: \$30/month → ${BUDGET_EMAIL}"
