"""Graph nodes. Each is a plain function of (state, deps) so it can be tested with stubs."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from askindia_agents.executor import QueryResult, SQLError, SQLErrorKind
from askindia_agents.graph import prompts
from askindia_agents.graph.claims import Decomposition, TriageDecision, VerdictProse, judge
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
        self,
        question: str,
        *,
        top_chunks: int = 12,
        top_datasets: int = 3,
        only_dataset: str | None = None,
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


_WH = re.compile(
    r"^\s*(who|what|which|when|where|why|how|is|are|was|were|do|does|did|can|could|has|have|"
    r"compare|list|show|tell|give)\b",
    re.I,
)
_QUANTITY = re.compile(
    r"\d|\b(lakh|crore|million|billion|percent|per cent|doubled|tripled|halved|more than|"
    r"less than|higher than|lower than|busier|bigger|larger|smaller)\b",
    re.I,
)
_DATE_EXCUSE = re.compile(
    r"\b(19|20)\d\d\b|\b(after|up to|until|beyond|future|not (yet )?available|does not cover|"
    r"coverage)\b",
    re.I,
)
_NO_TOPIC_EXCUSE = re.compile(
    r"\b(not contain|does not include|no data (related|about|on)|unrelated|no dataset|not related|"
    r"nothing about|none of the datasets|not covered by any)\b",
    re.I,
)
_TOPIC_STOPWORDS = {
    "from",
    "with",
    "data",
    "onwards",
    "monthly",
    "annual",
    "static",
    "seed",
    "fixture",
    "statistics",
    "estimates",
    "india",
    "indian",
    "state",
    "states",
    "four",
    "since",
    "metros",
}


def looks_like_claim(text: str) -> bool:
    """A declarative sentence with a quantity or comparison is a claim; a question is not."""
    t = text.strip()
    return not t.endswith("?") and not _WH.match(t) and bool(_QUANTITY.search(t))


def topic_terms(manifest: str) -> set[str]:
    words = {w for line in manifest.splitlines() for w in re.findall(r"[a-z]{4,}", line.lower())}
    return words - _TOPIC_STOPWORDS


def mentions_catalogue_topic(text: str, manifest: str) -> bool:
    words = set(re.findall(r"[a-z]{4,}", text.lower()))
    return bool(words & topic_terms(manifest))


def intake(state: AgentState, deps: Deps) -> AgentState:
    manifest = deps.manifest()
    if looks_like_claim(state["question"]):
        return {
            "intent": "claim",
            "intake_reason": "declarative statement with a quantity",
            "attempts": 0,
            "errors": [],
        }
    try:
        decision = deps.llm.complete_json(
            model=deps.chat_model,
            system=prompts.INTAKE_SYSTEM,
            user=(
                f"Today's date: {date.today():%Y-%m-%d}\nMessage: {state['question']}\n\n"
                f"Catalogue:\n{manifest}"
            ),
            schema=IntakeDecision,
            metadata={"node": "intake"},
        )
    except ContractViolationError as e:
        return {
            "intent": "out_of_scope",
            "intake_reason": f"the message could not be classified ({e})",
            "attempts": 0,
            "errors": [],
        }
    intent, reason = decision.intent, decision.reason
    if (
        intent == "out_of_scope"
        and _DATE_EXCUSE.search(reason)
        and not _NO_TOPIC_EXCUSE.search(reason)
    ):
        # Small models refuse in-coverage dates as "the future"; coverage is settled by the query.
        intent, reason = "question", "topic is in the catalogue; date coverage decided by the query"
    return {"intent": intent, "intake_reason": reason, "attempts": 0, "errors": []}


def triage(state: AgentState, deps: Deps) -> AgentState:
    """The integrity gate for claims: only a claim one catalogue dataset can settle proceeds."""
    try:
        decision = deps.llm.complete_json(
            model=deps.chat_model,
            system=prompts.TRIAGE_SYSTEM,
            user=(
                f"Today's date: {date.today():%Y-%m-%d}\nClaim: {state['question']}\n\n"
                f"Catalogue:\n{deps.manifest()}"
            ),
            schema=TriageDecision,
            metadata={"node": "triage"},
        )
    except ContractViolationError as e:
        return {
            "claim": state["question"],
            "triage": {
                "triage": "statistical_uncovered",
                "dataset": None,
                "reason": f"the claim could not be classified reliably ({e})",
                "data_needed": "a clearer statement of the claim",
            },
        }
    known = {
        line[2:].split(":", 1)[0] for line in deps.manifest().splitlines() if line.startswith("- ")
    }
    result = decision.model_dump()
    if decision.triage == "checkable" and known and decision.dataset not in known:
        result["triage"] = "statistical_uncovered"
        result["reason"] = (
            f"{result['reason']} (named dataset {decision.dataset!r} is not in the catalogue)"
        )
    return {"claim": state["question"], "triage": result}


def route_after_triage(state: AgentState) -> str:
    return "decompose" if state["triage"]["triage"] == "checkable" else "unverifiable"


def decompose(state: AgentState, deps: Deps) -> AgentState:
    try:
        decomp = deps.llm.complete_json(
            model=deps.chat_model,
            system=prompts.DECOMPOSE_SYSTEM,
            user=f"Claim: {state['claim']}",
            schema=Decomposition,
            metadata={"node": "decompose"},
        )
    except ContractViolationError as e:
        return {"decomposition": {}, "errors": [*state.get("errors", []), _violation(e)]}
    # The sub-question drives the ordinary query path; the claim text is kept for the verdict.
    return {"decomposition": decomp.model_dump(), "question": decomp.question}


def route_after_decompose(state: AgentState) -> str:
    return "retrieve" if state.get("decomposition") else "fail_closed"


def synthesize_verdict(state: AgentState, deps: Deps) -> AgentState:
    decomp = Decomposition.model_validate(state["decomposition"])
    result = judge(decomp, state["result"]["rows"])
    return {"verdict": result.to_dict()}


def compose_verdict(state: AgentState, deps: Deps) -> AgentState:
    v = state["verdict"]
    citation = state.get("citation")
    cite = (
        f"{citation['dataset']}, version {citation['dataset_version']}, "
        f"coverage {citation['coverage']}"
        if citation
        else "unknown dataset"
    )
    user = (
        f"Claim: {state['claim']}\nQuestion checked: {state['question']}\n"
        f"Verdict (decided by arithmetic): {v['verdict']} — {v['explanation']}\n"
        f"Claimed: {v['claimed']}  Actual: {v['actual']}\n"
        f"SQL executed:\n{state['admitted_sql']}\nRows:\n{_rows_preview(state['result'])}\n"
        f"Dataset: {cite}\nValidation notes: {state.get('validation_notes', [])}"
    )
    if state.get("regenerated"):
        user += "\n\nYour previous text used numbers not in this material. Use only these numbers."
    try:
        prose = deps.llm.complete_json(
            model=deps.chat_model,
            system=prompts.VERDICT_SYSTEM,
            user=user,
            schema=VerdictProse,
            metadata={"node": "compose_verdict"},
        )
    except ContractViolationError as e:
        return {"composition": {}, "errors": [*state.get("errors", []), _violation(e)]}
    return {"composition": {"prose": prose.prose, "chart": None, "caveats": prose.caveats}}


def _violation(e: Exception) -> ErrorRecord:
    return {"attempt": 0, "kind": "contract_violation", "message": str(e), "sql": None}


def route_after_compose(state: AgentState) -> str:
    return "guard" if state.get("composition") else "fail_closed"


def unverifiable(state: AgentState, deps: Deps) -> AgentState:
    t = state.get("triage", {})
    if t.get("triage") == "not_statistical":
        why = t.get("reason") or "it does not assert a checkable statistic"
        prose = f"This is not a statistical claim I can check: {why}."
    else:
        needed = t.get("data_needed") or "an official dataset covering this claim"
        prose = (
            "Unverifiable with the available data. "
            f"{t.get('reason', '')} To check this claim I would need: {needed}."
        ).replace("  ", " ")
    final: FinalAnswer = {
        "status": "unverifiable",
        "mode": "claim",
        "claim": state.get("claim"),
        "verdict": {
            "verdict": "Unverifiable",
            "claimed": None,
            "actual": None,
            "relative_error": None,
            "explanation": t.get("reason", ""),
            "tolerance": None,
        },
        "prose": prose,
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


def retrieve(state: AgentState, deps: Deps) -> AgentState:
    only = (state.get("triage") or {}).get("dataset") if state.get("claim") else None
    result = deps.retriever.retrieve(state["question"], only_dataset=only)
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
        f"Today's date: {date.today():%Y-%m-%d}\nContext:\n\n\n"
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
    try:
        composition = deps.llm.complete_json(
            model=deps.chat_model,
            system=prompts.COMPOSE_SYSTEM,
            user=user,
            schema=Composition,
            metadata={"node": "compose"},
        )
    except ContractViolationError as e:
        return {"composition": {}, "errors": [*state.get("errors", []), _violation(e)]}
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
    verdict = state.get("verdict") or {}
    provenance = " ".join(
        [
            state["question"],
            state.get("claim", ""),
            state.get("admitted_sql", ""),
            *(str(v) for v in citation.values()),
            *(str(verdict.get(k)) for k in ("claimed", "actual") if verdict.get(k) is not None),
            *_verdict_numbers(verdict),
        ]
    )
    report: GuardReport = check_groundedness(
        state["composition"]["prose"], state["result"]["rows"], provenance_text=provenance
    )
    return {"guard": report.to_dict()}


def route_after_validate(state: AgentState) -> str:
    return "synthesize_verdict" if state.get("claim") else "compose"


def route_after_regenerate(state: AgentState) -> str:
    return "compose_verdict" if state.get("claim") else "compose"


def _verdict_numbers(verdict: dict[str, Any]) -> list[str]:
    """Figures the verdict text may legitimately quote: tolerance bands and the relative error."""
    out: list[str] = []
    tol = verdict.get("tolerance") or {}
    if tol.get("supported_within") is not None:
        out.append(f"{tol['supported_within'] * 100:g}%")
    if tol.get("misleading_factor") is not None:
        out.append(f"{tol['misleading_factor']:g}")
    rel = verdict.get("relative_error")
    if isinstance(rel, int | float) and math.isfinite(rel):
        out.extend([f"{rel * 100:.1f}%", f"{rel * 100:.0f}%", f"{rel * 100:.2f}%"])
    return out


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
    is_claim = "verdict" in state
    final: FinalAnswer = {
        "status": "verdict" if is_claim else "answered",
        "mode": "claim" if is_claim else "question",
        "claim": state.get("claim"),
        "verdict": state.get("verdict"),
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
        "mode": "question",
        "claim": None,
        "verdict": None,
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
        "mode": "claim" if state.get("claim") else "question",
        "claim": state.get("claim"),
        "verdict": {
            "verdict": "Unverifiable",
            "claimed": None,
            "actual": None,
            "relative_error": None,
            "explanation": "could not compute",
            "tolerance": None,
        }
        if state.get("claim")
        else None,
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
