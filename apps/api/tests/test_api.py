"""HTTP contract against a stubbed graph: JSON answers, SSE progress, catalogue, health, limits."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from askindia_agents.executor import QueryResult
from askindia_agents.graph import Deps
from askindia_agents.llm import ScriptedLLM
from askindia_agents.retriever import RetrievalResult, RetrievedChunk

os.environ.setdefault("DATABASE_URL", "postgresql://x:y@localhost/none")
os.environ.setdefault("DATABASE_URL_RO", "postgresql://x:y@localhost/none")
os.environ["BUILD_DEPS"] = "false"

from askindia_api.main import create_app

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


class StubRetriever:
    def retrieve(
        self,
        question: str,
        *,
        top_chunks: int = 12,
        top_datasets: int = 3,
        only_dataset: str | None = None,
    ) -> RetrievalResult:
        return RetrievalResult(question=question, chunks=[CHUNK], datasets=["census_2011_pca"])


def make_deps(replies: list[Any]) -> Deps:
    return Deps(
        llm=ScriptedLLM(replies),
        retriever=StubRetriever(),
        execute=lambda sql: QueryResult(sql=sql, columns=("name", "population_total"), rows=ROWS),
        sql_model="stub",
        chat_model="stub",
        citation_for=lambda d: {
            "dataset": d,
            "table": f"data.{d}",
            "dataset_version": "v1",
            "source": "ORGI",
            "coverage": "2011",
        },
        manifest=lambda: "- census_2011_pca: Census 2011 (2011-03-01 to 2011-03-01)",
    )


HAPPY = [
    {"intent": "question", "reason": ""},
    {"sql": "SELECT name, population_total FROM data.census_2011_pca ORDER BY 2 DESC LIMIT 1"},
    {"prose": "Uttar Pradesh: 199,812,341 people (Census 2011).", "chart": None, "caveats": []},
]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_deps(HAPPY * 5), rate_limit="1000/minute")) as c:
        yield c


def test_ask_returns_grounded_answer(client: TestClient) -> None:
    r = client.post("/ask", json={"question": "Most populous state in 2011?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "answered"
    assert body["rows"] == ROWS and body["sql"].startswith("SELECT")
    assert body["citation"]["dataset"] == "census_2011_pca"
    assert body["guard"]["passed"] is True and body["elapsed_seconds"] >= 0


def test_ask_validates_input(client: TestClient) -> None:
    assert client.post("/ask", json={"question": "hi"}).status_code == 422
    assert client.post("/ask", json={"question": "x" * 501}).status_code == 422


def test_stream_emits_progress_then_final(client: TestClient) -> None:
    with client.stream("POST", "/ask/stream", json={"question": "Most populous state?"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(r.iter_lines())
    names = [e["event"] for e in events]
    assert names[-1] == "final" and names.count("status") >= 5
    nodes = [json.loads(e["data"])["node"] for e in events if e["event"] == "status"]
    assert nodes[:3] == ["intake", "retrieve", "generate_sql"] and "guard" in nodes
    final = json.loads(events[-1]["data"])
    assert final["status"] == "answered" and final["row_count"] == 1


def test_health_and_metrics(client: TestClient) -> None:
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["datasets"] == 1
    client.post("/ask", json={"question": "Most populous state in 2011?"})
    m = client.get("/metrics").text
    assert 'askindia_requests_total{status="answered"}' in m
    assert "askindia_request_seconds_bucket" in m


def test_rate_limit_is_enforced() -> None:
    with TestClient(create_app(make_deps(HAPPY * 5), rate_limit="2/minute")) as c:
        codes = [
            c.post("/ask", json={"question": "Most populous state?"}).status_code for _ in range(3)
        ]
    assert codes == [200, 200, 429]


def _parse_sse(lines: Iterator[str]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in lines:
        if not line:
            if current:
                events.append(current)
                current = {}
            continue
        key, _, value = line.partition(":")
        current[key.strip()] = (
            value.strip() if key != "data" else (current.get("data", "") + value.strip())
        )
    if current:
        events.append(current)
    return events
