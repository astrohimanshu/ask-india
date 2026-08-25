#!/usr/bin/env bash
# Provision the production footprint: resource group, Log Analytics, Container Apps environment,
# PostgreSQL Flexible Server (B1ms, pgvector), Key Vault with the secrets, Blob storage for
# dataset snapshots, and a user-assigned identity for the apps. Idempotent.
set -euo pipefail
cd "$(dirname "$0")"; . ./00_vars.sh
: "${PG_ADMIN_PASSWORD:?set PG_ADMIN_PASSWORD}" "${ASKINDIA_APP_PASSWORD:?}" "${ASKINDIA_RO_PASSWORD:?}"

az provider register -n Microsoft.DBforPostgreSQL --wait >/dev/null
az provider register -n Microsoft.App --wait >/dev/null
az group create -n "$AZ_RG" -l "$AZ_LOCATION" -o none

az monitor log-analytics workspace create -g "$AZ_RG" -n "$AZ_LOGS" -l "$AZ_LOCATION" -o none
LOG_ID=$(az monitor log-analytics workspace show -g "$AZ_RG" -n "$AZ_LOGS" --query customerId -o tsv)
LOG_KEY=$(az monitor log-analytics workspace get-shared-keys -g "$AZ_RG" -n "$AZ_LOGS" --query primarySharedKey -o tsv)
az containerapp env show -g "$AZ_RG" -n "$AZ_ENV" -o none 2>/dev/null || \
  az containerapp env create -g "$AZ_RG" -n "$AZ_ENV" -l "$AZ_LOCATION" \
    --logs-workspace-id "$LOG_ID" --logs-workspace-key "$LOG_KEY" -o none

az identity create -g "$AZ_RG" -n "$AZ_IDENTITY" -o none

if ! az postgres flexible-server show -g "$AZ_RG" -n "$AZ_PG" -o none 2>/dev/null; then
  az postgres flexible-server create -g "$AZ_RG" -n "$AZ_PG" -l "$AZ_LOCATION" \
    --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 \
    --admin-user "$AZ_PG_ADMIN" --admin-password "$PG_ADMIN_PASSWORD" \
    --database-name askindia --public-access 0.0.0.0 --yes -o none
fi
az postgres flexible-server parameter set -g "$AZ_RG" -s "$AZ_PG" -n azure.extensions --value vector -o none
az postgres flexible-server parameter set -g "$AZ_RG" -s "$AZ_PG" -n shared_preload_libraries --value pg_stat_statements -o none || true

az storage account create -g "$AZ_RG" -n "$AZ_STORAGE" -l "$AZ_LOCATION" --sku Standard_LRS --kind StorageV2 \
  --allow-blob-public-access false -o none
az storage container create --account-name "$AZ_STORAGE" -n snapshots --auth-mode login -o none || true

az keyvault show -g "$AZ_RG" -n "$AZ_KV" -o none 2>/dev/null || \
  az keyvault create -g "$AZ_RG" -n "$AZ_KV" -l "$AZ_LOCATION" --enable-rbac-authorization true -o none
ME=$(az ad signed-in-user show --query id -o tsv)
KV_ID=$(az keyvault show -g "$AZ_RG" -n "$AZ_KV" --query id -o tsv)
az role assignment create --assignee "$ME" --role "Key Vault Secrets Officer" --scope "$KV_ID" -o none 2>/dev/null || true
PG_HOST="$AZ_PG.postgres.database.azure.com"
sleep 20
for kv in \
  "DATABASE-URL=postgresql://askindia_app:${ASKINDIA_APP_PASSWORD}@${PG_HOST}:5432/askindia?sslmode=require" \
  "DATABASE-URL-RO=postgresql://askindia_ro:${ASKINDIA_RO_PASSWORD}@${PG_HOST}:5432/askindia?sslmode=require" \
  "PG-ADMIN-PASSWORD=${PG_ADMIN_PASSWORD}" \
  "LANGFUSE-PUBLIC-KEY=${LANGFUSE_PUBLIC_KEY:-}" \
  "LANGFUSE-SECRET-KEY=${LANGFUSE_SECRET_KEY:-}"; do
  az keyvault secret set --vault-name "$AZ_KV" -n "${kv%%=*}" --value "${kv#*=}" -o none
done
echo "provisioned: rg=$AZ_RG pg=$PG_HOST kv=$AZ_KV storage=$AZ_STORAGE env=$AZ_ENV"
