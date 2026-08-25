"""Request and response contracts for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500, description="Plain-English question")


class CitationOut(BaseModel):
    dataset: str
    table: str
    dataset_version: str | None = None
    source: str | None = None
    coverage: str | None = None


class VerdictOut(BaseModel):
    verdict: Literal["Supported", "Misleading", "Contradicted", "Unverifiable"]
    claimed: float | None = None
    actual: float | None = None
    relative_error: float | None = None
    explanation: str = ""
    tolerance: dict[str, float] | None = None


class AnswerOut(BaseModel):
    status: Literal["answered", "out_of_scope", "failed", "verdict", "unverifiable"]
    mode: Literal["question", "claim"] = "question"
    claim: str | None = None
    verdict: VerdictOut | None = None
    prose: str
    chart: dict[str, Any] | None = None
    sql: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    citation: CitationOut | None = None
    assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    attempts: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    guard: dict[str, Any] | None = None
    elapsed_seconds: float = 0.0


class DatasetOut(BaseModel):
    dataset: str
    table_name: str
    title: str
    source_org: str
    source_url: str | None = None
    cadence: str | None = None
    coverage_from: str | None = None
    coverage_to: str | None = None
    current_version: str
    is_seed: bool
    updated_at: str


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    datasets: int
    sql_model: str
    chat_model: str
