"""Assemble the LangGraph and provide a convenience runner with real dependencies."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, cast

import psycopg
from langgraph.graph import END, StateGraph

from askindia_agents import tracing
from askindia_agents.embedder import FastEmbedEmbedder
from askindia_agents.executor import execute_readonly
from askindia_agents.graph import nodes
from askindia_agents.graph.nodes import Deps
from askindia_agents.graph.state import AgentState, Citation, FinalAnswer
from askindia_agents.llm import LiteLLMClient
from askindia_agents.retriever import SchemaRetriever
from askindia_agents.settings import get_settings
from askindia_agents.sqlguard import AdmittedSQL

NodeFn = Callable[[AgentState, Deps], AgentState]


def _bind(fn: NodeFn, deps: Deps) -> Callable[[AgentState], AgentState]:
    @functools.wraps(fn)
    def bound(state: AgentState) -> AgentState:
        return fn(state, deps)

    return bound


NODE_TYPES = {"retrieve": "retriever", "execute": "tool", "guard": "guardrail"}


def _traced(
    fn: Callable[[AgentState], AgentState], name: str
) -> Callable[[AgentState], AgentState]:
    """Wrap a node in a Langfuse observation; a no-op when tracing is not configured."""
    traced: Callable[[AgentState], AgentState] = tracing.traced_node(
        name, fn, as_type=NODE_TYPES.get(name, "chain")
    )
    return traced


def build_graph(deps: Deps) -> Any:
    g = StateGraph(AgentState)
    for name, fn in (
        ("intake", nodes.intake),
        ("retrieve", nodes.retrieve),
        ("generate_sql", nodes.generate_sql),
        ("execute", nodes.execute),
        ("validate", nodes.validate),
        ("compose", nodes.compose),
        ("guard", nodes.guard),
        ("mark_regenerated", nodes.mark_regenerated),
        ("finish", nodes.finish),
        ("out_of_scope", nodes.out_of_scope),
        ("fail_closed", nodes.fail_closed),
    ):
        g.add_node(name, cast(Any, _traced(_bind(fn, deps), name)))
    g.set_entry_point("intake")
    g.add_conditional_edges(
        "intake",
        lambda s: "out_of_scope" if s.get("intent") == "out_of_scope" else "retrieve",
        {"out_of_scope": "out_of_scope", "retrieve": "retrieve"},
    )
    g.add_edge("retrieve", "generate_sql")
    g.add_edge("generate_sql", "execute")
    g.add_conditional_edges(
        "execute",
        nodes.route_after_execute,
        {"validate": "validate", "generate_sql": "generate_sql", "fail_closed": "fail_closed"},
    )
    g.add_edge("validate", "compose")
    g.add_edge("compose", "guard")
    g.add_conditional_edges(
        "guard",
        nodes.route_after_guard,
        {"finish": "finish", "regenerate": "mark_regenerated", "fail_closed": "fail_closed"},
    )
    g.add_edge("mark_regenerated", "compose")
    g.add_edge("finish", END)
    g.add_edge("out_of_scope", END)
    g.add_edge("fail_closed", END)
    return g.compile()


def citation_lookup(dsn_ro: str) -> Callable[[str], Citation]:
    def lookup(dataset: str) -> Citation:
        with psycopg.connect(dsn_ro) as conn:
            row = (
                conn.execute(
                    "SELECT dataset, table_name, current_version, source_url, "
                    "coverage_from, coverage_to FROM meta.datasets WHERE dataset = %s",
                    (dataset,),
                ).fetchone()
                if _has_meta_access(conn)
                else None
            )
        if row is None:
            return {
                "dataset": dataset,
                "table": f"data.{dataset}",
                "dataset_version": None,
                "source": None,
                "coverage": None,
            }
        return {
            "dataset": row[0],
            "table": row[1],
            "dataset_version": row[2],
            "source": row[3],
            "coverage": f"{row[4]} to {row[5]}" if row[4] else None,
        }

    return lookup


def _has_meta_access(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute("SELECT has_schema_privilege('meta', 'USAGE')").fetchone()
    return bool(row and row[0])


def manifest_lookup(dsn_ro: str) -> Callable[[], str]:
    """Plain-text catalogue: what data exists and for which dates; drives intake honesty."""

    def manifest() -> str:
        with psycopg.connect(dsn_ro) as conn:
            if not _has_meta_access(conn):
                return "(catalogue unavailable)"
            rows = conn.execute(
                "SELECT dataset, title, coverage_from, coverage_to, is_seed FROM meta.datasets"
                " ORDER BY dataset"
            ).fetchall()
        lines = []
        for dataset, title, c_from, c_to, is_seed in rows:
            cov = f"{c_from} to {c_to}" if c_from else "coverage unknown"
            lines.append(f"- {dataset}: {title} ({cov}){' [SEED FIXTURE]' if is_seed else ''}")
        return "\n".join(lines) or "(catalogue empty)"

    return manifest


def real_deps() -> Deps:
    settings = get_settings()
    dsn_ro = settings.database_url_ro.get_secret_value()

    def execute(sql: str) -> Any:
        admitted = AdmittedSQL(sql=sql, tables=(), limit_injected=False)
        return execute_readonly(
            admitted,
            dsn=dsn_ro,
            timeout_seconds=settings.sql_timeout_seconds,
            max_cost=settings.sql_max_cost,
        )

    return Deps(
        llm=LiteLLMClient(),
        retriever=SchemaRetriever(dsn_ro, FastEmbedEmbedder()),
        execute=execute,
        sql_model=settings.sql_model,
        chat_model=settings.chat_model,
        citation_for=citation_lookup(dsn_ro),
        manifest=manifest_lookup(dsn_ro),
        row_limit=settings.sql_row_limit,
    )


def run_question(question: str, deps: Deps | None = None) -> FinalAnswer:
    tracing.configure()
    graph = build_graph(deps or real_deps())
    with tracing.observation("ask-india", as_type="agent", input={"question": question}) as trace:
        state: AgentState = graph.invoke({"question": question})
        final = state["final"]
        if trace is not None:
            trace.update(output={"status": final["status"], "prose": final["prose"]})
    tracing.flush()
    return final
