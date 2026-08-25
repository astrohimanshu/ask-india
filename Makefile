.PHONY: stack-up stack-down stack-logs psql psql-ro test lint

COMPOSE = docker compose --project-directory . -f infra/compose/compose.yaml

stack-up:
	$(COMPOSE) up -d --wait

stack-down:
	$(COMPOSE) down

stack-logs:
	$(COMPOSE) logs -f --tail=100

psql:
	$(COMPOSE) exec db psql -U askindia_app -d askindia

psql-ro:
	$(COMPOSE) exec db psql -U askindia_ro -d askindia

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy
