# Shared names for the Azure scripts. Source this file; every script is idempotent.
# The subscription policy allows only Malaysia West, East Asia, UAE North, Central India and
# Southeast Asia, and it permits a single Container Apps environment in total. That environment
# already exists in Central India for another project, so the apps are placed into it by resource
# id (AZ_ENV_ID) in their own resource group; nothing in the other project is modified.
export AZ_LOCATION="${AZ_LOCATION:-centralindia}"
export AZ_ENV_ID="${AZ_ENV_ID:-}"
export AZ_RG="${AZ_RG:-rg-askindia}"
export AZ_ENV="${AZ_ENV:-cae-askindia}"
export AZ_LOGS="${AZ_LOGS:-log-askindia}"
export AZ_PG="${AZ_PG:-pg-askindia}"
export AZ_PG_ADMIN="${AZ_PG_ADMIN:-pgadmin}"
export AZ_KV="${AZ_KV:-kv-askindia-$(az account show --query id -o tsv | cut -c1-6)}"
export AZ_STORAGE="${AZ_STORAGE:-staskindia$(az account show --query id -o tsv | tr -d '-' | cut -c1-8)}"
export AZ_IDENTITY="${AZ_IDENTITY:-id-askindia}"
export IMAGE_TAG="${IMAGE_TAG:-latest}"
export API_IMAGE="ghcr.io/astrohimanshu/ask-india-api:${IMAGE_TAG}"
export WEB_IMAGE="ghcr.io/astrohimanshu/ask-india-web:${IMAGE_TAG}"
export OLLAMA_IMAGE="ghcr.io/astrohimanshu/ask-india-ollama:${IMAGE_TAG}"
export PROD_MODEL="${PROD_MODEL:-ollama/qwen2.5-coder:3b}"
export BUDGET_EMAIL="${BUDGET_EMAIL:-himanshu.252cd007@nitk.edu.in}"
