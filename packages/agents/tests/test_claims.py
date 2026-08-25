"""Claim mode: triage fails closed, decomposition drives the query path, verdicts are arithmetic."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from askindia_agents.executor import QueryResult
from askindia_agents.graph import Deps, build_graph
from askindia_agents.graph.claims import Decomposition, judge
from askindia_agents.llm import ScriptedLLM
from askindia_agents.retriever import RetrievalResult, RetrievedChunk

CHUNK = RetrievedChunk(
    1,
    "census_2011_pca",
    "table",
    "data.census_2011_pca",
    "Columns: name, population_total",
    {},
    1.0,
    1,
    1,
)
ROWS = [{"name": "UTTAR PRADESH", "population_total": 199812341}]
GOOD_SQL = {
    "sql": "SELECT name, population_total FROM data.census_2011_pca ORDER BY 2 DESC LIMIT 1",
    "assumptions": [],
}


class StubRetriever:
    def retrieve(
        self, question: str, *, top_chunks: int = 12, top_datasets: int = 3
    ) -> RetrievalResult:
        return RetrievalResult(question=question, chunks=[CHUNK], datasets=["census_2011_pca"])


def ok_executor(sql: str) -> QueryResult:
    return QueryResult(sql=sql, columns=("name", "population_total"), rows=ROWS, elapsed_ms=1.0)


def deps(llm: ScriptedLLM, execute: Callable[[str], QueryResult] = ok_executor) -> Deps:
    return Deps(
        llm=llm,
        retriever=StubRetriever(),
        execute=execute,
        sql_model="stub-sql",
        chat_model="stub-chat",
        citation_for=lambda d: {
            "dataset": d,
            "table": f"data.{d}",
            "dataset_version": "v1",
            "source": "ORGI",
            "coverage": "2011",
        },
        manifest=lambda: "- census_2011_pca: Census 2011 (2011-03-01 to 2011-03-01)",
    )


CLAIM = {"intent": "claim", "reason": ""}
CHECKABLE = {
    "triage": "checkable",
    "dataset": "census_2011_pca",
    "reason": "population is in the census",
}
DECOMP = {
    "question": "What was the population of Uttar Pradesh in 2011?",
    "claimed_value": 200000000,
    "comparison": "value",
    "unit": "people",
    "scale": 1,
}
VERDICT_PROSE = {
    "prose": "Supported: the claim of 200,000,000 is within 10% of the census figure "
    "of 199,812,341.",
    "caveats": [],
}


def test_supported_claim_end_to_end() -> None:
    llm = ScriptedLLM([CLAIM, CHECKABLE, DECOMP, GOOD_SQL, VERDICT_PROSE])
    final = build_graph(deps(llm)).invoke({"question": "UP had 20 crore people in 2011"})["final"]
    assert final["status"] == "verdict" and final["mode"] == "claim"
    assert final["verdict"]["verdict"] == "Supported"
    assert final["verdict"]["actual"] == 199812341 and final["verdict"]["claimed"] == 200000000
    assert final["rows"] == ROWS and final["sql"]
    assert final["guard"]["passed"] is True
    assert [c["schema"] for c in llm.calls] == [
        "IntakeDecision",
        "TriageDecision",
        "Decomposition",
        "SQLDraft",
        "VerdictProse",
    ]


def test_uncovered_claim_is_unverifiable_and_never_queries() -> None:
    llm = ScriptedLLM(
        [
            CLAIM,
            {
                "triage": "statistical_uncovered",
                "reason": "GDP is not in the catalogue",
                "data_needed": "MoSPI national accounts",
            },
        ]
    )

    def execute(sql: str) -> QueryResult:
        raise AssertionError("must not execute")

    final = build_graph(deps(llm, execute)).invoke({"question": "India's GDP grew 8% in 2024"})[
        "final"
    ]
    assert final["status"] == "unverifiable"
    assert final["verdict"]["verdict"] == "Unverifiable"
    assert "MoSPI national accounts" in final["prose"]
    assert len(llm.calls) == 2


def test_checkable_with_unknown_dataset_is_downgraded() -> None:
    llm = ScriptedLLM([CLAIM, {"triage": "checkable", "dataset": "gdp_quarterly", "reason": "x"}])
    final = build_graph(deps(llm)).invoke({"question": "GDP doubled"})["final"]
    assert final["status"] == "unverifiable"
    assert "not in the catalogue" in final["verdict"]["explanation"]


def test_not_statistical_claim() -> None:
    llm = ScriptedLLM([CLAIM, {"triage": "not_statistical", "reason": "it is an opinion"}])
    final = build_graph(deps(llm)).invoke({"question": "Delhi is the best city"})["final"]
    assert final["status"] == "unverifiable" and "not a statistical claim" in final["prose"]


def test_guard_still_applies_to_verdict_prose() -> None:
    bad = {"prose": "Supported: UP had 250,000,000 people.", "caveats": []}
    llm = ScriptedLLM([CLAIM, CHECKABLE, DECOMP, GOOD_SQL, bad, bad])
    final = build_graph(deps(llm)).invoke({"question": "UP had 20 crore people in 2011"})["final"]
    assert final["status"] == "failed" and final["verdict"]["verdict"] == "Unverifiable"
    assert final["guard"]["ungrounded"] == ["250,000,000"]


@pytest.mark.parametrize(
    ("claimed", "comparison", "rows", "expected"),
    [
        (100.0, "value", [{"v": 105}], "Supported"),
        (100.0, "value", [{"v": 150}], "Misleading"),
        (100.0, "value", [{"v": 300}], "Contradicted"),
        (-20.0, "change_pct", [{"pct": 15.0}], "Contradicted"),
        (2.0, "ratio", [{"ratio": 1.38}], "Misleading"),
        (None, "greater", [{"a": 10, "b": 5}], "Supported"),
        (None, "less", [{"a": 10, "b": 5}], "Contradicted"),
        (None, "greater", [{"name": "A", "v": 100}, {"name": "B", "v": 99}], "Misleading"),
        (5.0, "value", [], "Unverifiable"),
    ],
)
def test_tolerance_bands(
    claimed: float | None, comparison: str, rows: list[dict[str, Any]], expected: str
) -> None:
    d = Decomposition(question="what is it?", claimed_value=claimed, comparison=comparison)  # type: ignore[arg-type]
    assert judge(d, rows).verdict == expected


def test_scale_converts_units() -> None:
    d = Decomposition(
        question="what is it?", claimed_value=96.0, comparison="value", unit="lakh", scale=100000
    )
    assert judge(d, [{"passengers_carried": 9614311}]).verdict == "Supported"
