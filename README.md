# Ask India

Plain-English questions about India, answered from official government datasets — and, next,
viral statistical claims checked against them. Every answer shows its work: the SQL that was
executed, the dataset it ran against, and that dataset's vintage.

**Status:** working locally end to end (question → grounded answer with chart and receipts) on six
real government datasets. Claim verification, evaluation numbers and a public deployment are in
progress; nothing is deployed yet.

**Last updated:** 2026-08-26, 12:10 IST

![An answer with the SQL, dataset, vintage and rows expanded](docs/screenshots/answer-show-your-work.png)

## What it does

- Turns a question like *"How has the petrol price in Delhi changed each year since 2017?"* into
  one PostgreSQL `SELECT`, runs it as a read-only database role, and writes the answer only from
  the rows that came back.
- Shows the receipt on every answer: executed SQL, dataset name, version (fetch date + content
  hash), coverage dates, assumptions the query writer made, and the rows.
- Refuses rather than guesses. Three things make that mechanical, not a matter of prompting:
  - **SQL admission guard** — `sqlglot` parses model output; anything but a single `SELECT` over
    the data schema is rejected before it reaches the database, which itself only grants the
    agent a `SELECT`-only, read-only-transaction role with a 10 s statement timeout.
  - **Groundedness guard** — a programmatic check extracts every numeral from the composed
    answer and requires it to be derivable from the result rows (or the question, SQL or
    citation). A failure triggers one regeneration, then the answer is refused.
  - **Fail-closed intake** — questions outside the catalogue get an explanation of what data
    would be needed, never a made-up number.

## The data

Six datasets fetched from their publishing ministries, validated, versioned and loaded
([details and what did not make v1](docs/DATASETS.md)):

| | Source | Coverage |
|---|---|---|
| Airline traffic | DGCA carrier-wise monthly statistics | Jan 2019 – Jul 2026 |
| Airport traffic | AAI airport-wise monthly passengers | Jan 2023 – Jun 2026 |
| Census 2011 | ORGI Primary Census Abstract, state and district | 1 Mar 2011 |
| Crops | DA&FW area, production and yield by state | 2021-22 – 2025-26 |
| Rainfall | IMD monthly rainfall by meteorological subdivision | 1901 – 2025 |
| Fuel prices | PPAC daily petrol and diesel prices, four metros | Jun 2017 – Aug 2026 |

Ingestion fails loud: a batch that fails validation is quarantined and recorded, never partially
loaded. Every row carries `dataset_version`; the catalogue (`/datasets`) reports each dataset's
current version and coverage.

## How it works

```
question ──▶ intake ──▶ schema retrieval (pgvector + keyword, RRF) ──▶ SQL generation (JSON contract)
         ──▶ sqlglot admission guard ──▶ execute as read-only role ──▶ classify error, retry ≤ 3
         ──▶ validate ──▶ compose answer + chart spec ──▶ groundedness guard ──▶ stream to UI
```

- `packages/agents` — LangGraph graph, prompts, guards, retriever, dictionaries, Langfuse tracing
- `packages/ingestion` — dataset loaders (`BaseLoader`: fetch → snapshot → parse → validate → load),
  validation, atomic persistence with audit rows
- `apps/api` — FastAPI: `POST /ask`, `POST /ask/stream` (Server-Sent Events per graph node),
  `GET /datasets`, `/health`, `/metrics` (Prometheus)
- `apps/web` — Next.js + Tailwind + shadcn/ui + Recharts

Models are routed through LiteLLM: local Ollama (`qwen2.5-coder:7b` for SQL, `qwen2.5:7b-instruct`
for classification and prose) in development; the model ids are environment variables.

## Running it

Requires Docker, `uv`, Node 22 with `pnpm`, and Ollama.

```bash
cp .env.example .env                                   # fill in passwords and keys
docker compose --project-directory . -f infra/compose/compose.yaml up -d --wait
uv sync --all-packages --group dev
uv run python -m askindia_ingestion.migrate
scripts/dev_ollama.sh                                  # starts Ollama, pulls the two models
uv run scripts/ingest.py                               # fetch and load the six datasets (~2 min)
uv run scripts/index_dictionaries.py                   # embed the data dictionaries
uv run scripts/ask.py "Which state had the highest literacy rate in 2011?"
uv run uvicorn askindia_api.main:app --port 8000
cd apps/web && pnpm install && pnpm dev                # http://localhost:3000
```

Tests, lint and type checks (also run in CI on every pull request):

```bash
uv run pytest            # unit tests; add -m integration for tests against the local database
uv run ruff check . && uv run mypy
uv run scripts/check_dictionaries.py   # executes every exemplar query in the dictionaries
```

## License

MIT — see [LICENSE](LICENSE).
