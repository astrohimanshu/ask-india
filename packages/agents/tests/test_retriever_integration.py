"""Against the local database: hybrid retrieval lands on the right dataset for probe questions."""

import os

import psycopg
import pytest
from pgvector.psycopg import register_vector

from askindia_agents.dictionary import Dictionary
from askindia_agents.embedder import HashEmbedder
from askindia_agents.indexer import index_dictionary
from askindia_agents.retriever import SchemaRetriever

pytestmark = pytest.mark.integration
DSN = os.environ.get("DATABASE_URL", "")
DSN_RO = os.environ.get("DATABASE_URL_RO", "")

AIR = Dictionary.model_validate(
    {
        "dataset": "probe_air",
        "table": "data.probe_air",
        "title": "Airline passengers",
        "purpose": "Monthly domestic passengers carried per airline with market share.",
        "source": "probe",
        "cadence": "monthly",
        "coverage": "2024",
        "columns": [
            {"name": "airline", "type": "text", "description": "carrier name such as IndiGo"},
            {"name": "passengers_carried", "type": "bigint", "description": "passengers flown"},
        ],
        "exemplars": [
            {
                "question": "Which airline flew the most passengers?",
                "sql": "SELECT airline FROM data.probe_air",
            }
        ],
    }
)
RAIN = Dictionary.model_validate(
    {
        "dataset": "probe_rain",
        "table": "data.probe_rain",
        "title": "Rainfall by subdivision",
        "purpose": "Monthly rainfall in millimetres for each meteorological subdivision.",
        "source": "probe",
        "cadence": "monthly",
        "coverage": "1901-2020",
        "columns": [
            {
                "name": "subdivision",
                "type": "text",
                "description": "IMD meteorological subdivision",
            },
            {
                "name": "rainfall_mm",
                "type": "numeric",
                "description": "rain in millimetres",
                "unit": "mm",
            },
        ],
    }
)


@pytest.fixture(autouse=True)
def corpus() -> None:
    if not DSN:
        pytest.skip("DATABASE_URL not set")
    with psycopg.connect(DSN) as conn:
        register_vector(conn)
        index_dictionary(conn, AIR, HashEmbedder())
        index_dictionary(conn, RAIN, HashEmbedder())
    yield  # type: ignore[misc]
    with psycopg.connect(DSN) as conn:
        conn.execute("DELETE FROM rag.chunks WHERE dataset LIKE 'probe_%'")


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Which airline carried the most passengers in 2024?", "probe_air"),
        ("How much rainfall did Kerala subdivision get in July?", "probe_rain"),
        ("market share of IndiGo", "probe_air"),
        ("rainfall_mm by subdivision", "probe_rain"),
    ],
)
def test_probe_questions_land_on_the_right_dataset(question: str, expected: str) -> None:
    result = SchemaRetriever(DSN_RO, HashEmbedder()).retrieve(question)
    assert result.datasets and result.datasets[0] == expected
    assert any(c.kind == "table" and c.dataset == expected for c in result.chunks)
    assert expected in result.context_text()
