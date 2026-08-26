# Deployment

Live: https://web.jollyocean-ec5e02b3.centralindia.azurecontainerapps.io · API health:
https://api.jollyocean-ec5e02b3.centralindia.azurecontainerapps.io/health

```
GitHub Actions (deploy.yml) ──▶ GHCR: ask-india-api, ask-india-web, ask-india-ollama
                                        │
   infra/azure/30_deploy.sh (operator) ──▶ Azure Container Apps (scale to zero)
                                            ├── web     Next.js, external ingress
                                            ├── api     FastAPI, external ingress
                                            └── ollama  CPU model server, internal ingress
   Azure Database for PostgreSQL Flexible B1ms ── data + pgvector + catalogue
   Azure Key Vault ── connection strings and keys ·  Blob ── dataset snapshots
   Langfuse Cloud ── traces ·  budget alert at $30/month
```

## Why it looks like this

- **Images from CI, rollout from an operator machine.** The tenant does not allow app
  registrations, so GitHub Actions has no Azure credential; it publishes images to GHCR and
  `30_deploy.sh` (idempotent `az containerapp create/update`) rolls them out using the operator's
  own `az login`.
- **One Container Apps environment per subscription.** The subscription already owns one, so the
  three apps live in their own resource group and reference that environment by id.
- **The production model is a CPU model, and it is weaker.** No Azure OpenAI is available on
  this subscription, and a 7B model does not run usefully on the 4 vCPU consumption plan. The
  live service therefore runs `qwen2.5-coder:3b` inside an Ollama container with the model baked
  into the image. Measured on the same 60-question L1 set: **40.0 %** execution accuracy (vs
  76.7 % for the 7B pair used in development). The number is shown here rather than hidden;
  switching to a hosted OpenAI-compatible model is one environment variable (`SQL_MODEL`,
  `CHAT_MODEL`) plus its key.
- **Scale to zero.** All three apps scale to zero; the first request after idle pays a cold start
  (the Ollama replica pulls a 2.5 GB image and loads the model: several minutes the first time,
  then about 40 s). Observed on the live site: 2–3 minutes per question on 4 vCPUs. This is a
  disclosed trade-off for a $100 credit, not a bug.
- **Postgres firewall.** Container Apps reach the server through Azure-internal addresses, so the
  `AllowAllAzureServicesAndResourcesWithinAzureIps` rule is required in addition to any operator
  IPs; without it every request from the API hung on the database connection.
- **Secrets never touch the repository.** Passwords are generated on the operator machine,
  stored in Key Vault, and injected into the apps as Container App secrets.

## Steps

```bash
export PG_ADMIN_PASSWORD=… ASKINDIA_APP_PASSWORD=… ASKINDIA_RO_PASSWORD=… \
       LANGFUSE_PUBLIC_KEY=… LANGFUSE_SECRET_KEY=… AZ_ENV_ID=<existing environment id>
infra/azure/10_provision.sh   # resource group, Postgres (pgvector), Key Vault, Blob, identity
infra/azure/20_db_init.sh     # schemas + roles, migrations, ingest the six datasets, index dictionaries
infra/azure/30_deploy.sh      # ollama, api, web Container Apps from the GHCR images
infra/azure/40_budget.sh      # $30/month budget with 50/80/100 % alerts
infra/azure/50_smoke.sh       # health, catalogue, one question, one claim — from outside
```
