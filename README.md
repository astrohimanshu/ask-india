# Ask India

Plain-English questions about India, answered from official government datasets — and viral
statistical claims checked against them. Every answer shows its work: the SQL that was
executed, the dataset it ran against, and that dataset's vintage.

**Status:** early scaffold. No data, no model, no UI yet.

**Last updated:** 2026-08-25, 23:20 IST

## Layout

```
apps/api/            FastAPI service (SSE streaming)
apps/web/            Next.js front end
packages/agents/     LangGraph agent: retrieval, SQL generation, execution, guards
packages/ingestion/  dataset loaders, validation, versioned persistence
packages/evals/      execution-accuracy and verdict-accuracy harnesses
packages/training/   training-data factory, QLoRA fine-tuning, benchmark
infra/compose/       local stack (Postgres + pgvector, Ollama)
infra/k8s/           kind-targeted manifests
infra/azure/         provisioning scripts
scripts/             one-off and operational scripts
```

## Running the tests

```bash
uv sync
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
