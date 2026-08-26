"""The exact prompt the SQL generator uses, so training pairs match inference token-for-token.

The training target is the JSON contract the agent parses at run time; the context is the same
dictionary rendering the retriever would produce for that dataset.
"""

from __future__ import annotations

import json
from datetime import date

from askindia_agents.dictionary import Dictionary, chunk_dictionary, load_all
from askindia_agents.graph import prompts


def dataset_context(d: Dictionary, *, max_exemplars: int = 3) -> str:
    """Render a dictionary the way RetrievalResult.context_text does for one dataset."""
    chunks = chunk_dictionary(d)
    table = [c.content for c in chunks if c.kind == "table"]
    columns = [c.content for c in chunks if c.kind == "column"]
    caveats = [c.content for c in chunks if c.kind == "caveat"]
    exemplars = [c.content for c in chunks if c.kind == "exemplar"][:max_exemplars]
    parts = [f"### Dataset {d.dataset}", *table]
    if columns:
        parts.append("Relevant column notes:\n" + "\n".join(f"- {c}" for c in columns))
    if caveats:
        parts.append("Caveats:\n" + "\n".join(f"- {c}" for c in caveats))
    if exemplars:
        parts.append("Examples:\n" + "\n\n".join(exemplars))
    return "\n\n".join(parts)


def contexts() -> dict[str, str]:
    return {d.dataset: dataset_context(d) for d in load_all()}


def user_message(context: str, question: str, *, today: date | None = None) -> str:
    today = today or date(2026, 8, 26)
    return f"Today's date: {today:%Y-%m-%d}\nContext:\n{context}\n\nQuestion: {question}"


def target_message(sql: str, assumptions: list[str] | None = None) -> str:
    return json.dumps(
        {"sql": sql, "rationale": "", "assumptions": assumptions or [], "expected_shape": ""},
        ensure_ascii=False,
    )


def to_chat_example(context: str, question: str, sql: str) -> dict[str, list[dict[str, str]]]:
    """Prompt/completion conversational format: the trainer computes loss on the completion only."""
    return {
        "prompt": [
            {"role": "system", "content": prompts.SQL_SYSTEM},
            {"role": "user", "content": user_message(context, question)},
        ],
        "completion": [{"role": "assistant", "content": target_message(sql)}],
    }
