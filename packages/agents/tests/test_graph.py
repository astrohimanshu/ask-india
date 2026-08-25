"""The agent graph with scripted LLM, stub retriever and stub executor, every path exercised."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from askindia_agents.executor import QueryResult, SQLError, SQLErrorKind
from askindia_agents.graph import Deps, build_graph
from askindia_agents.graph.state import MAX_ATTEMPTS
from askindia_agents.llm import ScriptedLLM
from askindia_agents.retriever import RetrievalResult, RetrievedChunk

TABLE_CHUNK = RetrievedChunk(
    id=1,
    dataset="census_2011_pca",
    kind="table",
    title="data.census_2011_pca",
    content="Census 2011 PCA. Columns:\n- name (text)\n- population_total (bigint)",
    metadata={},
    score=1.0,
    vector_rank=1,
    keyword_rank=1,
)


class StubRetriever:
    def retrieve(
        self,
        question: str,
        *,
        top_chunks: int = 12,
        top_datasets: int = 3,
        only_dataset: str | None = None,
    ) -> RetrievalResult:
        return RetrievalResult(
            question=question, chunks=[TABLE_CHUNK], datasets=["census_2011_pca"]
        )


ROWS = [{"name": "UTTAR PRADESH", "population_total": 199812341}]


def ok_executor(sql: str) -> QueryResult:
    return QueryResult(sql=sql, columns=("name", "population_total"), rows=ROWS, elapsed_ms=1.0)


def failing_then_ok(kinds: list[SQLErrorKind]) -> Callable[[str], QueryResult]:
    calls: list[str] = []

    def execute(sql: str) -> QueryResult:
        calls.append(sql)
        if len(calls) <= len(kinds):
            raise SQLError(kinds[len(calls) - 1], f"simulated {kinds[len(calls) - 1]}")
        return ok_executor(sql)

    return execute


def citation(dataset: str) -> Any:
    return {
        "dataset": dataset,
        "table": f"data.{dataset}",
        "dataset_version": "2026-08-25-7a8f70d4",
        "source": "ORGI",
        "coverage": "2011",
    }


def deps(llm: ScriptedLLM, execute: Callable[[str], QueryResult] = ok_executor) -> Deps:
    return Deps(
        llm=llm,
        retriever=StubRetriever(),
        execute=execute,
        sql_model="stub-sql",
        chat_model="stub-chat",
        citation_for=citation,
        manifest=lambda: "- census_2011_pca: Census 2011 (2011-03-01 to 2011-03-01)",
    )


INTAKE_Q = {"intent": "question", "reason": ""}
GOOD_SQL = {
    "sql": "SELECT name, population_total FROM data.census_2011_pca ORDER BY 2 DESC LIMIT 1",
    "assumptions": ["Total population, all areas"],
}
GOOD_PROSE = {
    "prose": "Uttar Pradesh was the most populous state in 2011 with 199,812,341 people "
    "(Census 2011, version 2026-08-25-7a8f70d4).",
    "chart": None,
    "caveats": [],
}


def test_happy_path_answers_with_receipts() -> None:
    llm = ScriptedLLM([INTAKE_Q, GOOD_SQL, GOOD_PROSE])
    final = build_graph(deps(llm)).invoke({"question": "Most populous state in 2011?"})["final"]
    assert final["status"] == "answered"
    assert final["sql"].endswith("LIMIT 1")
    assert final["rows"] == ROWS and final["row_count"] == 1
    assert final["citation"]["dataset"] == "census_2011_pca"
    assert final["assumptions"] == ["Total population, all areas"]
    assert final["attempts"] == 1 and final["errors"] == []
    assert final["guard"]["passed"] is True
    assert [c["schema"] for c in llm.calls] == ["IntakeDecision", "SQLDraft", "Composition"]
    assert "Catalogue:\n- census_2011_pca" in llm.calls[0]["user"]


def test_bad_column_triggers_targeted_retry_then_succeeds() -> None:
    seen_prompts: list[str] = []

    def second_sql(system: str, user: str) -> dict[str, Any]:
        seen_prompts.append(user)
        return GOOD_SQL

    llm = ScriptedLLM(
        [INTAKE_Q, {"sql": "SELECT nam FROM data.census_2011_pca"}, second_sql, GOOD_PROSE]
    )
    execute = failing_then_ok([SQLErrorKind.BAD_COLUMN])
    final = build_graph(deps(llm, execute)).invoke({"question": "Most populous state?"})["final"]
    assert final["status"] == "answered"
    assert final["attempts"] == 2
    assert [e["kind"] for e in final["errors"]] == ["bad_column"]
    assert "does not exist" in seen_prompts[0] and "Previous SQL: SELECT nam" in seen_prompts[0]


def test_three_failures_fail_closed_without_guessing() -> None:
    llm = ScriptedLLM([INTAKE_Q] + [GOOD_SQL] * MAX_ATTEMPTS)
    execute = failing_then_ok([SQLErrorKind.EMPTY_RESULT] * MAX_ATTEMPTS)
    final = build_graph(deps(llm, execute)).invoke({"question": "Population of Atlantis?"})["final"]
    assert final["status"] == "failed"
    assert final["attempts"] == MAX_ATTEMPTS
    assert final["rows"] == [] and "not going to guess" in final["prose"]
    assert len(llm.calls) == 1 + MAX_ATTEMPTS  # no composer call on the failure path


def test_destructive_sql_is_rejected_and_counts_as_an_attempt() -> None:
    llm = ScriptedLLM([INTAKE_Q, {"sql": "DROP TABLE data.census_2011_pca"}, GOOD_SQL, GOOD_PROSE])
    calls: list[str] = []

    def execute(sql: str) -> QueryResult:
        calls.append(sql)
        return ok_executor(sql)

    final = build_graph(deps(llm, execute)).invoke({"question": "Most populous state?"})["final"]
    assert final["status"] == "answered"
    assert final["errors"][0]["kind"] == "rejected"
    assert all("DROP" not in c for c in calls), "rejected SQL must never reach the executor"


def test_contract_violation_is_an_attempt() -> None:
    llm = ScriptedLLM([INTAKE_Q, "this is not json", GOOD_SQL, GOOD_PROSE])
    final = build_graph(deps(llm)).invoke({"question": "Most populous state?"})["final"]
    assert final["status"] == "answered" and final["attempts"] == 2
    assert final["errors"][0]["kind"] == "contract_violation"


def test_out_of_scope_never_touches_the_database() -> None:
    llm = ScriptedLLM(
        [{"intent": "out_of_scope", "reason": "Needs GDP data, which is not in the catalogue."}]
    )

    def execute(sql: str) -> QueryResult:
        raise AssertionError("must not execute")

    final = build_graph(deps(llm, execute)).invoke({"question": "Will GDP grow next year?"})[
        "final"
    ]
    assert final["status"] == "out_of_scope"
    assert "GDP" in final["prose"] and final["sql"] is None
    assert len(llm.calls) == 1


def test_hallucinated_number_is_caught_regenerated_then_fails_closed() -> None:
    bad = {"prose": "Uttar Pradesh had 250,000,000 people in 2011.", "chart": None, "caveats": []}
    llm = ScriptedLLM([INTAKE_Q, GOOD_SQL, bad, bad])
    final = build_graph(deps(llm)).invoke({"question": "Most populous state?"})["final"]
    assert final["status"] == "failed"
    assert final["guard"]["passed"] is False and final["guard"]["ungrounded"] == ["250,000,000"]
    assert "could not be traced" in final["prose"]
    assert "not in the rows" in llm.calls[-1]["user"]


def test_hallucination_then_corrected_answer_passes() -> None:
    bad = {"prose": "Uttar Pradesh had 250 million people.", "chart": None, "caveats": []}
    llm = ScriptedLLM([INTAKE_Q, GOOD_SQL, bad, GOOD_PROSE])
    final = build_graph(deps(llm)).invoke({"question": "Most populous state?"})["final"]
    assert final["status"] == "answered" and final["guard"]["passed"] is True


def test_chart_with_unknown_columns_is_dropped() -> None:
    prose = {**GOOD_PROSE, "chart": {"type": "bar", "x": "state", "y": ["pop"], "title": "x"}}
    llm = ScriptedLLM([INTAKE_Q, GOOD_SQL, prose])
    final = build_graph(deps(llm)).invoke({"question": "Most populous state?"})["final"]
    assert final["chart"] is None


def test_seed_data_is_flagged_in_caveats() -> None:
    def seed_citation(dataset: str) -> Any:
        return {**citation(dataset), "dataset_version": "seed-v0"}

    llm = ScriptedLLM([INTAKE_Q, GOOD_SQL, GOOD_PROSE])
    d = deps(llm)
    d.citation_for = seed_citation
    final = build_graph(d).invoke({"question": "Most populous state?"})["final"]
    assert final["caveats"][0].startswith("This answer was computed from a synthetic seed fixture")


@pytest.mark.parametrize("bad_reply", [{"intent": "maybe"}, "{}"])
def test_intake_contract_violation_fails_closed(bad_reply: Any) -> None:
    llm = ScriptedLLM([bad_reply])
    final = build_graph(deps(llm)).invoke({"question": "tell me something"})["final"]
    assert final["status"] == "out_of_scope" and "could not be classified" in final["prose"]


def test_compose_contract_violation_fails_closed() -> None:
    llm = ScriptedLLM([INTAKE_Q, GOOD_SQL, "not json at all"])
    final = build_graph(deps(llm)).invoke({"question": "Most populous state?"})["final"]
    assert final["status"] == "failed" and final["errors"][-1]["kind"] == "contract_violation"
