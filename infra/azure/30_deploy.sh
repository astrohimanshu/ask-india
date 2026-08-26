#!/usr/bin/env bash
# Deploy or update the three Container Apps from GHCR images: ollama (internal, CPU model),
# api (external), web (external). Secrets are read from Key Vault at deploy time and stored as
# Container App secrets; scale-to-zero keeps idle cost near zero.
set -euo pipefail
cd "$(dirname "$0")"; . ./00_vars.sh
ID_RES=$(az identity show -g "$AZ_RG" -n "$AZ_IDENTITY" --query id -o tsv)
ENV_REF="${AZ_ENV_ID:-$AZ_ENV}"
secret() { az keyvault secret show --vault-name "$AZ_KV" -n "$1" --query value -o tsv; }
DB_URL=$(secret DATABASE-URL); DB_URL_RO=$(secret DATABASE-URL-RO)
LF_PK=$(secret LANGFUSE-PUBLIC-KEY); LF_SK=$(secret LANGFUSE-SECRET-KEY)

# Create the app, or update it in place. `az containerapp update` does not accept --env-vars or
# --secrets (those exist only on create), so an update sets secrets first and then passes the
# environment with --set-env-vars. Everything after the fixed arguments is treated as env pairs;
# secrets are passed separately in SECRETS.
upsert() { # name image ingress(external|internal) port cpu memory min max [KEY=VALUE ...]
  local name=$1 image=$2 ingress=$3 port=$4 cpu=$5 mem=$6 min=$7 max=$8; shift 8
  local envs=("$@")
  if az containerapp show -g "$AZ_RG" -n "$name" -o none 2>/dev/null; then
    if [ ${#SECRETS[@]} -gt 0 ]; then
      az containerapp secret set -g "$AZ_RG" -n "$name" --secrets "${SECRETS[@]}" -o none
    fi
    az containerapp update -g "$AZ_RG" -n "$name" --image "$image" --cpu "$cpu" --memory "$mem" \
      --min-replicas "$min" --max-replicas "$max" \
      ${envs:+--set-env-vars "${envs[@]}"} -o none
  else
    az containerapp create -g "$AZ_RG" -n "$name" --environment "$ENV_REF" --image "$image" \
      --ingress "$ingress" --target-port "$port" --cpu "$cpu" --memory "$mem" \
      --min-replicas "$min" --max-replicas "$max" --user-assigned "$ID_RES" \
      ${SECRETS:+--secrets "${SECRETS[@]}"} ${envs:+--env-vars "${envs[@]}"} -o none
  fi
  SECRETS=()
}

SECRETS=()
upsert ollama "$OLLAMA_IMAGE" internal 11434 4.0 8.0Gi 0 1 \
  OLLAMA_KEEP_ALIVE=30m OLLAMA_NUM_PARALLEL=1
OLLAMA_FQDN=$(az containerapp show -g "$AZ_RG" -n ollama --query properties.configuration.ingress.fqdn -o tsv)

SECRETS=("database-url=$DB_URL" "database-url-ro=$DB_URL_RO" "lf-pk=$LF_PK" "lf-sk=$LF_SK")
upsert api "$API_IMAGE" external 8000 1.0 2.0Gi 0 2 \
  DATABASE_URL=secretref:database-url DATABASE_URL_RO=secretref:database-url-ro \
  LANGFUSE_PUBLIC_KEY=secretref:lf-pk LANGFUSE_SECRET_KEY=secretref:lf-sk \
  LANGFUSE_BASE_URL=https://cloud.langfuse.com \
  OLLAMA_BASE_URL="https://${OLLAMA_FQDN}" SQL_MODEL="$PROD_MODEL" CHAT_MODEL="$PROD_MODEL" \
  SQL_TIMEOUT_SECONDS=10 RATE_LIMIT=10/minute
API_FQDN=$(az containerapp show -g "$AZ_RG" -n api --query properties.configuration.ingress.fqdn -o tsv)

# The web image bakes NEXT_PUBLIC_API_URL at build time; the deploy workflow builds it with the API URL.
SECRETS=()
upsert web "$WEB_IMAGE" external 3000 0.5 1.0Gi 0 1
WEB_FQDN=$(az containerapp show -g "$AZ_RG" -n web --query properties.configuration.ingress.fqdn -o tsv)
az containerapp update -g "$AZ_RG" -n api --set-env-vars WEB_ORIGIN="https://${WEB_FQDN}" -o none
echo "api: https://${API_FQDN}   web: https://${WEB_FQDN}   ollama(internal): ${OLLAMA_FQDN}"
