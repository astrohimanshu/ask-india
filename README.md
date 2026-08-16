# Ask India

Plain-English questions about India, answered from official government datasets — and viral
statistical claims checked against them. Every answer shows its work: the SQL that was
executed, the dataset it ran against, and that dataset's vintage.

**Status:** local development stack only — nothing deployed. Postgres with a read-only
agent role, a sqlglot admission guard, a walking skeleton (question → SQL → read-only
execution) verified against a synthetic `seed-v0` fixture, ingestion contracts with
quarantine semantics, and pgvector schema retrieval. **No real government data is loaded
yet**; every row in the database is a stamped fixture.

**Last updated:** 2026-08-26, 00:20 IST

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
