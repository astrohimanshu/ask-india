"""Graph nodes. Each is a plain function of (state, deps) so it can be tested with stubs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from askindia_agents.executor import QueryResult, SQLError, SQLErrorKind
from askindia_agents.graph import prompts
from askindia_agents.graph.state import (
    MAX_ATTEMPTS,
    AgentState,
    Citation,
    Composition,
    ErrorRecord,
    FinalAnswer,
    IntakeDecision,
    SQLDraft,
)
from askindia_agents.groundedness import GuardReport, check_groundedness
from askindia_agents.llm import ContractViolationError, JSONCompleter
from askindia_agents.retriever import RetrievalResult
from askindia_agents.sqlguard import SQLRejectedError, admit

log = logging.getLogger(__name__)


class Retriever(Protocol):
    def retrieve(
        self, question: str, *, top_chunks: int = 12, top_datasets: int = 3
    ) -> RetrievalResult: ...


Executor = Callable[[str], QueryResult]
CitationLookup = Callable[[str], Citation]


@dataclass
class Deps:
    llm: JSONCompleter
    retriever: Retriever
    execute: Executor
    sql_model: str
    chat_model: str
    citation_for: CitationLookup
    manifest: Callable[[], str] = lambda: "(catalogue unavailable)"
    row_limit: int = 500


def intake(state: AgentState, deps: Deps) -> AgentState:
    decision = deps.llm.complete_json(
        model=deps.chat_model,
        system=prompts.INTAKE_SYSTEM,
        user=(
            f"Today's date: {date.today():%Y-%m-%d}\nMessage: {state['question']}\n\n"
            f"Catalogue:\n{deps.manifest()}"
        ),
        schema=IntakeDecision,
        metadata={"node": "intake"},
    )
    return {
        "intent": decision.intent,
        "intake_reason": decision.reason,
        "attempts": 0,
        "errors": [],
    }


def retrieve(state: AgentState, deps: Deps) -> AgentState:
    result = deps.retriever.retrieve(state["question"])
    citation = deps.citation_for(result.datasets[0]) if result.datasets else None
    return {"context": result.context_text(), "datasets": result.datasets, "citation": citation}


def _error_prompt(errors: list[ErrorRecord]) -> str:
    last = errors[-1]
    kind = SQLErrorKind(last["kind"]) if last["kind"] in SQLErrorKind.__members__.values() else None
    guidance = (
        prompts.RETRY_GUIDANCE.get(kind, prompts.RETRY_GUIDANCE[SQLErrorKind.OTHER])
        if kind
        else (
            "The previous reply did not follow the JSON contract. Reply with the exact JSON shape."
        )
    )
    return (
        f"\n\nPrevious attempt failed ({last['kind']}): {last['message']}\n"
        f"Previous SQL: {last['sql'] or '(none)'}\nGuidance: {guidance}"
    )


def generate_sql(state: AgentState, deps: Deps) -> AgentState:
    attempts = state.get("attempts", 0) + 1
    errors = list(state.get("errors", []))
    user = (
        f"Today's date: {date.today():%Y-%m-%d}\nContext:\n{state.get('context', '')}\n\n"
        f"Question: {state['question']}"
    )
    if errors:
        user += _error_prompt(errors)
    try:
        draft = deps.llm.complete_json(
            model=deps.sql_model,
            system=prompts.SQL_SYSTEM,
            user=user,
            schema=SQLDraft,
            metadata={"node": "generate_sql", "attempt": str(attempts)},
        )
    except ContractViolationError as e:
        errors.append(
            {"attempt": attempts, "kind": "contract_violation", "message": str(e), "sql": None}
        )
        return {"attempts": attempts, "errors": errors, "draft": {}, "admitted_sql": ""}
    return {"attempts": attempts, "errors": errors, "draft": draft.model_dump(), "admitted_sql": ""}


def execute(state: AgentState, deps: Deps) -> AgentState:
    errors = list(state.get("errors", []))
    if errors and errors[-1]["attempt"] == state.get("attempts") and not state.get("draft"):
        return {}  # contract violation already recorded for this attempt
    sql = str(state.get("draft", {}).get("sql", ""))
    try:
        admitted = admit(sql, row_limit=deps.row_limit)
    except SQLRejectedError as e:
        errors.append(
            {"attempt": state["attempts"], "kind": "rejected", "message": str(e), "sql": sql}
        )
        return {"errors": errors}
    try:
        result = deps.execute(admitted.sql)
    except SQLError as e:
        errors.append(
            {
                "attempt": state["attempts"],
                "kind": e.kind.value,
                "message": e.message,
                "sql": admitted.sql,
            }
        )
        return {"errors": errors, "admitted_sql": admitted.sql}
    return {
        "admitted_sql": admitted.sql,
        "result": {
            "columns": list(result.columns),
            "rows": [dict(r) for r in result.rows],
            "elapsed_ms": result.elapsed_ms,
        },
    }


def route_after_execute(state: AgentState) -> str:
    if state.get("result"):
        return "validate"
    if state.get("attempts", 0) < MAX_ATTEMPTS:
        return "generate_sql"
    return "fail_closed"


def validate(state: AgentState, deps: Deps) -> AgentState:
    """Cheap, deterministic sanity checks; findings become caveats, never silent edits."""
    notes: list[str] = []
    result = state["result"]
    rows, columns = result["rows"], result["columns"]
    if len(rows) >= deps.row_limit:
        notes.append(
            f"Only the first {deps.row_limit} rows were returned; totals may be incomplete."
        )
    if len(columns) == 1 and len(rows) == 1 and rows[0][columns[0]] is None:
        notes.append("The query returned a NULL, which usually means no matching data.")
    return {"validation_notes": notes}


def _rows_preview(result: dict[str, Any], limit: int = 60) -> str:
    columns: list[str] = result["columns"]
    lines = [" | ".join(columns)]
    for row in result["rows"][:limit]:
        lines.append(" | ".join(str(row[c]) for c in columns))
    if len(result["rows"]) > limit:
        lines.append(f"... ({len(result['rows']) - limit} more rows)")
    return "\n".join(lines)


def compose(state: AgentState, deps: Deps) -> AgentState:
    citation = state.get("citation")
    cite_text = (
        f"Dataset: {citation['dataset']} ({citation['table']}), "
        f"version {citation['dataset_version']}, source: {citation['source']}, "
        f"coverage: {citation['coverage']}"
        if citation
        else "Dataset: unknown"
    )
    user = (
        f"Question: {state['question']}\n\nSQL executed:\n{state['admitted_sql']}\n\n"
        f"Rows:\n{_rows_preview(state['result'])}\n\n{cite_text}\n"
        f"Assumptions made by the query writer: {state.get('draft', {}).get('assumptions', [])}\n"
        f"Validation notes: {state.get('validation_notes', [])}"
    )
    if state.get("regenerated"):
        user += (
            "\n\nYour previous answer contained numbers that are not in the rows. Rewrite it using "
            "only numbers that appear verbatim in the rows above."
        )
    composition = deps.llm.complete_json(
        model=deps.chat_model,
        system=prompts.COMPOSE_SYSTEM,
        user=user,
        schema=Composition,
        metadata={"node": "compose"},
    )
    chart = composition.chart.model_dump() if composition.chart else None
    if chart and not _chart_columns_exist(chart, state["result"]["columns"]):
        chart = None
    return {"composition": {**composition.model_dump(), "chart": chart}}


def _chart_columns_exist(chart: dict[str, Any], columns: list[str]) -> bool:
    if chart.get("type") == "table":
        return True
    return (
        chart.get("x") in columns and bool(chart.get("y")) and all(y in columns for y in chart["y"])
    )


def guard(state: AgentState, deps: Deps) -> AgentState:
    citation: dict[str, Any] = dict(state.get("citation") or {})
    provenance = " ".join(
        [state["question"], state.get("admitted_sql", ""), *(str(v) for v in citation.values())]
    )
    report: GuardReport = check_groundedness(
        state["composition"]["prose"], state["result"]["rows"], provenance_text=provenance
    )
    return {"guard": report.to_dict()}


def route_after_guard(state: AgentState) -> str:
    if state["guard"]["passed"]:
        return "finish"
    if not state.get("regenerated"):
        return "regenerate"
    return "fail_closed"


def mark_regenerated(state: AgentState, deps: Deps) -> AgentState:
    return {"regenerated": True}


def finish(state: AgentState, deps: Deps) -> AgentState:
    composition = state["composition"]
    caveats = [*composition.get("caveats", []), *state.get("validation_notes", [])]
    citation = state.get("citation")
    if citation and (citation.get("dataset_version") or "").startswith("seed-"):
        caveats.insert(0, "This answer was computed from a synthetic seed fixture, not real data.")
    final: FinalAnswer = {
        "status": "answered",
        "prose": composition["prose"],
        "chart": composition.get("chart"),
        "sql": state["admitted_sql"],
        "rows": state["result"]["rows"],
        "columns": state["result"]["columns"],
        "row_count": len(state["result"]["rows"]),
        "citation": citation,
        "assumptions": list(state.get("draft", {}).get("assumptions", [])),
        "caveats": caveats,
        "attempts": state.get("attempts", 0),
        "errors": state.get("errors", []),
        "guard": state.get("guard"),
    }
    return {"final": final}


def out_of_scope(state: AgentState, deps: Deps) -> AgentState:
    reason = (
        state.get("intake_reason") or "This is not a question the available datasets can answer."
    )
    final: FinalAnswer = {
        "status": "out_of_scope",
        "prose": (
            "I can only answer questions computed from the official datasets in my catalogue. "
            f"{reason}"
        ),
        "chart": None,
        "sql": None,
        "rows": [],
        "columns": [],
        "row_count": 0,
        "citation": None,
        "assumptions": [],
        "caveats": [],
        "attempts": 0,
        "errors": [],
        "guard": None,
    }
    return {"final": final}


def fail_closed(state: AgentState, deps: Deps) -> AgentState:
    errors = state.get("errors", [])
    if state.get("guard") and not state["guard"]["passed"]:
        why = "the drafted answer contained numbers that could not be traced to the query result"
    elif errors:
        why = f"the last attempt failed with: {errors[-1]['message']}"
    else:
        why = "no query could be produced"
    final: FinalAnswer = {
        "status": "failed",
        "prose": (
            "I could not compute a grounded answer to this question from the available data, so I "
            f"am not going to guess. Reason: {why}."
        ),
        "chart": None,
        "sql": state.get("admitted_sql") or None,
        "rows": [],
        "columns": [],
        "row_count": 0,
        "citation": state.get("citation"),
        "assumptions": [],
        "caveats": [],
        "attempts": state.get("attempts", 0),
        "errors": errors,
        "guard": state.get("guard"),
    }
    return {"final": final}
