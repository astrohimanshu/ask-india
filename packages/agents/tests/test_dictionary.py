"""Dictionaries chunk into one table unit, one per column, caveat and exemplar."""

from askindia_agents.dictionary import Dictionary, chunk_dictionary
from askindia_agents.retriever import keyword_terms, rrf

DOC = {
    "dataset": "test_traffic",
    "table": "data.test_traffic",
    "title": "Test traffic",
    "purpose": "Monthly passengers per airline.",
    "source": "test",
    "cadence": "monthly",
    "coverage": "2024",
    "columns": [
        {"name": "period", "type": "date", "description": "first day of month"},
        {"name": "pax", "type": "bigint", "description": "passengers carried", "unit": "persons"},
    ],
    "caveats": ["Domestic scheduled only."],
    "exemplars": [
        {"question": "Total pax in 2024?", "sql": "SELECT SUM(pax) FROM data.test_traffic"}
    ],
}


def test_chunking_shapes() -> None:
    chunks = chunk_dictionary(Dictionary.model_validate(DOC))
    kinds = [c.kind for c in chunks]
    assert kinds == ["table", "column", "column", "caveat", "exemplar"]
    table = chunks[0]
    assert "data.test_traffic" in table.title and "pax" in table.content
    assert table.metadata["ddl"] == "data.test_traffic(period date, pax bigint)"
    assert chunks[-1].metadata["sql"].startswith("SELECT")
    assert len({c.sha for c in chunks}) == len(chunks)


def test_rrf_prefers_items_ranked_by_both_searches() -> None:
    scores = rrf([[1, 2, 3], [3, 1, 4]])
    assert scores[1] > scores[3] > scores[2] > scores[4]


def test_keyword_terms_drop_short_tokens() -> None:
    assert keyword_terms("What is the PLF of IndiGo in 2024?") == ["what", "the", "plf", "indigo"]
