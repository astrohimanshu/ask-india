#!/usr/bin/env bash
# Build both images, create (or reuse) the local kind cluster, load the images and apply the
# kustomize overlay. Run from the repository root with a populated .env.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
API_IMG=ghcr.io/astrohimanshu/ask-india-api:dev
WEB_IMG=ghcr.io/astrohimanshu/ask-india-web:dev

docker build -f apps/api/Dockerfile -t "$API_IMG" .
docker build -t "$WEB_IMG" --build-arg NEXT_PUBLIC_API_URL=http://localhost:30800 apps/web

kind get clusters | grep -qx askindia || kind create cluster --config infra/k8s/overlays/kind/kind.yaml
kind load docker-image "$API_IMG" "$WEB_IMG" --name askindia

# Secrets come from the development .env; the database URLs point at the in-cluster service.
set -a; . ./.env; set +a
cat > infra/k8s/overlays/kind/secrets.env <<ENV
POSTGRES_USER=postgres
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=askindia
ASKINDIA_APP_PASSWORD=${ASKINDIA_APP_PASSWORD}
ASKINDIA_RO_PASSWORD=${ASKINDIA_RO_PASSWORD}
DATABASE_URL=postgresql://askindia_app:${ASKINDIA_APP_PASSWORD}@db:5432/askindia
DATABASE_URL_RO=postgresql://askindia_ro:${ASKINDIA_RO_PASSWORD}@db:5432/askindia
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
ENV

# The host's Ollama listens on 127.0.0.1 only; expose it to the kind network on the docker bridge
# IPv4 gateway with a small forwarder and hand pods that address through the config map.
GATEWAY=$(docker network inspect kind | python3 -c 'import sys,json; print(next(c["Gateway"] for c in json.load(sys.stdin)[0]["IPAM"]["Config"] if ":" not in c["Subnet"]))')
if ! ss -ltn | grep -q "${GATEWAY}:11434"; then
  nohup uv run scripts/tcp_forward.py "$GATEWAY" 11434 127.0.0.1 11434 >/dev/null 2>&1 &
  sleep 2
fi
echo "OLLAMA_BASE_URL=http://${GATEWAY}:11434" > infra/k8s/overlays/kind/ollama.env

# The overlay reads the init SQL from scripts/db, outside its directory, so load restrictions are relaxed.
kubectl kustomize --load-restrictor LoadRestrictionsNone infra/k8s/overlays/kind | kubectl apply -f -
kubectl -n askindia rollout status statefulset/db --timeout=180s
kubectl -n askindia rollout status deployment/api --timeout=300s
kubectl -n askindia rollout status deployment/web --timeout=180s
kubectl -n askindia get pods -o wide
echo "api: http://localhost:30800/health   web: http://localhost:30300"
