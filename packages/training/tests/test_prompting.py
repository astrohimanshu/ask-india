"""Training examples reproduce the agent's prompt and the JSON contract it parses."""

import json

from askindia_agents.graph import prompts
from askindia_agents.graph.state import SQLDraft
from askindia_training.prompting import contexts, to_chat_example


def test_chat_example_matches_runtime_contract() -> None:
    ctx = contexts()
    assert set(ctx) >= {"census_2011_pca", "dgca_airline_traffic"}
    ex = to_chat_example(
        ctx["census_2011_pca"], "Population of Bihar?", "SELECT 1 FROM data.census_2011_pca"
    )
    assert ex["messages"][0]["content"] == prompts.SQL_SYSTEM
    assert "### Dataset census_2011_pca" in ex["messages"][1]["content"]
    assert ex["messages"][1]["content"].endswith("Question: Population of Bihar?")
    draft = SQLDraft.model_validate(json.loads(ex["messages"][2]["content"]))
    assert draft.sql == "SELECT 1 FROM data.census_2011_pca"
