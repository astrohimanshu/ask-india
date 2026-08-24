"""Ask India HTTP API: one question in, a grounded answer (or an honest refusal) out.

POST /ask         → the full answer as JSON
POST /ask/stream  → Server-Sent Events: one `status` event per graph node, then `final`
GET  /datasets    → the catalogue manifest (what data exists, for which dates)
GET  /health, GET /metrics
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import psycopg
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic_settings import BaseSettings, SettingsConfigDict
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

from askindia_agents import tracing
from askindia_agents.graph import Deps, build_graph
from askindia_agents.graph.build import real_deps
from askindia_agents.settings import get_settings
from askindia_api import metrics
from askindia_api.schemas import AnswerOut, AskRequest, DatasetOut, HealthOut


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    web_origin: str = "http://localhost:3000"
    rate_limit: str = "20/minute"
    build_deps: bool = True  # tests inject their own Deps


api_settings = ApiSettings()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    tracing.configure()
    if api_settings.build_deps and getattr(app.state, "deps", None) is None:
        app.state.deps = await asyncio.to_thread(real_deps)
    app.state.graph = build_graph(app.state.deps) if getattr(app.state, "deps", None) else None
    yield


app = FastAPI(title="Ask India", version="0.1.0", lifespan=lifespan)
app.state.deps = None
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, cast(Any, _rate_limit_exceeded_handler))
app.add_middleware(
    CORSMiddleware,
    allow_origins=[api_settings.web_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def get_graph(request: Request) -> Any:
    graph = request.app.state.graph
    if graph is None:
        request.app.state.graph = build_graph(request.app.state.deps)
        graph = request.app.state.graph
    return graph


def get_deps(request: Request) -> Deps:
    deps: Deps = request.app.state.deps
    return deps


@app.get("/health", response_model=HealthOut)
def health(deps: Deps = Depends(get_deps)) -> HealthOut:  # noqa: B008
    manifest = deps.manifest()
    count = sum(1 for line in manifest.splitlines() if line.startswith("- "))
    settings = get_settings()
    return HealthOut(
        status="ok" if count else "degraded",
        datasets=count,
        sql_model=settings.sql_model,
        chat_model=settings.chat_model,
    )


@app.get("/metrics")
def prometheus_metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/datasets", response_model=list[DatasetOut])
def datasets() -> list[DatasetOut]:
    dsn = get_settings().database_url_ro.get_secret_value()
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT dataset, table_name, title, source_org, source_url, cadence, coverage_from,"
            " coverage_to, current_version, is_seed, updated_at FROM meta.datasets ORDER BY dataset"
        ).fetchall()
    return [
        DatasetOut(
            dataset=r[0],
            table_name=r[1],
            title=r[2],
            source_org=r[3],
            source_url=r[4],
            cadence=r[5],
            coverage_from=str(r[6]) if r[6] else None,
            coverage_to=str(r[7]) if r[7] else None,
            current_version=r[8],
            is_seed=bool(r[9]),
            updated_at=str(r[10]),
        )
        for r in rows
    ]


def _to_answer(final: dict[str, Any], elapsed: float) -> AnswerOut:
    return AnswerOut(**{**final, "elapsed_seconds": round(elapsed, 2)})


@app.post("/ask", response_model=AnswerOut)
@limiter.limit(lambda: api_settings.rate_limit)
async def ask(request: Request, body: AskRequest, graph: Any = Depends(get_graph)) -> AnswerOut:  # noqa: B008
    started = time.perf_counter()
    state = await asyncio.to_thread(_invoke, graph, body.question)
    elapsed = time.perf_counter() - started
    metrics.observe_final(state["final"], elapsed)
    tracing.flush()
    return _to_answer(state["final"], elapsed)


def _invoke(graph: Any, question: str) -> dict[str, Any]:
    with tracing.observation("ask-india", as_type="agent", input={"question": question}) as trace:
        state: dict[str, Any] = graph.invoke({"question": question})
        if trace is not None:
            trace.update(output={"status": state["final"]["status"]})
    return state


PROGRESS_LABELS = {
    "intake": "Reading the question",
    "retrieve": "Finding the right dataset",
    "generate_sql": "Writing the query",
    "execute": "Running it against the data",
    "validate": "Checking the result",
    "compose": "Writing the answer",
    "guard": "Verifying every number against the rows",
    "mark_regenerated": "A number could not be traced; rewriting",
}


@app.post("/ask/stream")
@limiter.limit(lambda: api_settings.rate_limit)
async def ask_stream(
    request: Request,
    body: AskRequest,
    graph: Any = Depends(get_graph),  # noqa: B008
) -> EventSourceResponse:
    queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    started = time.perf_counter()

    def worker() -> None:
        try:
            with tracing.observation(
                "ask-india", as_type="agent", input={"question": body.question}
            ) as trace:
                final: dict[str, Any] | None = None
                for update in graph.stream({"question": body.question}, stream_mode="updates"):
                    for node, delta in update.items():
                        if isinstance(delta, dict) and "final" in delta:
                            final = delta["final"]
                        else:
                            loop.call_soon_threadsafe(
                                queue.put_nowait, ("status", _status(node, delta))
                            )
                if final is None:
                    raise RuntimeError("graph finished without a final answer")
                if trace is not None:
                    trace.update(output={"status": final["status"]})
            elapsed = time.perf_counter() - started
            metrics.observe_final(final, elapsed)
            loop.call_soon_threadsafe(
                queue.put_nowait, ("final", _to_answer(final, elapsed).model_dump())
            )
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, ("error", {"message": str(e)}))
        finally:
            tracing.flush()
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, worker)

    async def events() -> AsyncIterator[dict[str, str]]:
        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield {"event": event, "data": json.dumps(data, default=str)}

    return EventSourceResponse(events())


def _status(node: str, delta: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"node": node, "label": PROGRESS_LABELS.get(node, node)}
    if isinstance(delta, dict):
        if delta.get("datasets"):
            out["datasets"] = delta["datasets"]
        if delta.get("attempts"):
            out["attempt"] = delta["attempts"]
        if delta.get("admitted_sql"):
            out["sql"] = delta["admitted_sql"]
        if delta.get("errors"):
            out["last_error"] = delta["errors"][-1]
        if delta.get("guard"):
            out["guard"] = delta["guard"]
    return out


def create_app(deps: Deps | None = None, *, rate_limit: str | None = None) -> FastAPI:
    """App factory for tests: inject Deps, skip real dependency construction."""
    if deps is not None:
        app.state.deps = deps
        app.state.graph = build_graph(deps)
    if rate_limit is not None:
        api_settings.rate_limit = rate_limit
    return app


Handler = Callable[..., Any]
