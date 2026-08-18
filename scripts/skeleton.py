"""Walking skeleton: question -> model -> {sql, assumptions} -> guard -> read-only execution.

    uv run scripts/skeleton.py "Which carrier carried the most passengers in March 2024?"
    uv run scripts/skeleton.py --sql "DROP TABLE dgca_airline_traffic"

The ``--sql`` form skips the model and feeds the text straight to the guard, which is how the
destructive-input case is exercised deterministically.
"""

from __future__ import annotations

import argparse
import sys
import time

from pydantic import BaseModel, Field

from askindia_agents.executor import SQLError, execute_readonly
from askindia_agents.llm import ContractViolationError, complete_json
from askindia_agents.settings import get_settings
from askindia_agents.sqlguard import SQLRejectedError, admit

# The retrieval layer replaces this hard-coded dictionary later; the skeleton only needs one table.
SCHEMA = """
Table data.dgca_airline_traffic — monthly airline traffic and operating statistics,
one row per airline per month per segment.
  period date                       first day of the month (e.g. '2024-03-01' is March 2024)
  airline text                      carrier name
  segment text                      'scheduled_domestic', 'scheduled_international', ...
  departures integer                aircraft departures flown in the month
  passengers_carried bigint         passengers flown in that month
  passenger_load_factor_pct numeric seats filled, 0-100
  dataset_version text              provenance stamp; rows tagged 'seed-v0' are fixtures
"""

SYSTEM = """You translate questions about Indian government statistics into one PostgreSQL SELECT.
Rules: exactly one SELECT statement; only the tables described; never modify data; filter on
period with date literals; prefer explicit column names over *.
Reply with JSON only: {"sql": "<the query>", "assumptions": ["<each interpretation you made>"]}"""


class SQLDraft(BaseModel):
    sql: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)


def generate(question: str, model: str) -> SQLDraft:
    return complete_json(
        model=model,
        system=SYSTEM,
        user=f"Schema:\n{SCHEMA}\nQuestion: {question}",
        schema=SQLDraft,
        metadata={"stage": "skeleton"},
    )


def run(sql: str, *, assumptions: list[str]) -> int:
    settings = get_settings()
    print(f"proposed SQL : {sql}")
    for a in assumptions:
        print(f"assumption   : {a}")
    try:
        admitted = admit(sql, row_limit=settings.sql_row_limit)
    except SQLRejectedError as e:
        print(f"REJECTED by guard: {e}")
        return 2
    print(f"admitted SQL : {admitted.sql}")
    try:
        result = execute_readonly(
            admitted,
            dsn=settings.database_url_ro.get_secret_value(),
            timeout_seconds=settings.sql_timeout_seconds,
            max_cost=settings.sql_max_cost,
        )
    except SQLError as e:
        print(f"EXECUTION FAILED ({e.kind}): {e.message}")
        return 3
    print(
        f"{result.row_count} row(s) in {result.elapsed_ms:.0f} ms, plan cost {result.plan_cost:.0f}"
    )
    print(" | ".join(result.columns))
    for row in result.rows:
        print(" | ".join(str(row[c]) for c in result.columns))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("question", nargs="?", help="natural-language question")
    parser.add_argument("--sql", help="skip the model; send this SQL to the guard")
    parser.add_argument("--model", default=None, help="LiteLLM model id (default: SQL_MODEL)")
    args = parser.parse_args()
    if not args.question and not args.sql:
        parser.error("give a question or --sql")

    if args.sql:
        return run(args.sql, assumptions=[])

    model = args.model or get_settings().sql_model
    print(f"model        : {model}")
    started = time.perf_counter()
    try:
        draft = generate(args.question, model)
    except ContractViolationError as e:
        print(f"CONTRACT VIOLATION: {e}")
        return 4
    print(f"generation   : {(time.perf_counter() - started) * 1000:.0f} ms")
    return run(draft.sql, assumptions=draft.assumptions)


if __name__ == "__main__":
    sys.exit(main())
