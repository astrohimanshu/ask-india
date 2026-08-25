"""Typed graph state and the JSON contracts each model call must satisfy."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

Intent = Literal["question", "claim", "out_of_scope"]
MAX_ATTEMPTS = 3


class IntakeDecision(BaseModel):
    intent: Intent
    reason: str = ""


class SQLDraft(BaseModel):
    sql: str = Field(min_length=1)
    rationale: str = ""
    assumptions: list[str] = Field(default_factory=list)
    expected_shape: str = Field(default="", description="e.g. 'one row', 'one row per year'")


class ChartSpec(BaseModel):
    type: Literal["bar", "line", "table"] = "table"
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    title: str = ""


class Composition(BaseModel):
    prose: str = Field(min_length=1)
    chart: ChartSpec | None = None
    caveats: list[str] = Field(default_factory=list)


class Citation(TypedDict):
    dataset: str
    table: str
    dataset_version: str | None
    source: str | None
    coverage: str | None


class ErrorRecord(TypedDict):
    attempt: int
    kind: str
    message: str
    sql: str | None


class FinalAnswer(TypedDict, total=False):
    status: Literal["answered", "out_of_scope", "failed", "verdict", "unverifiable"]
    mode: Literal["question", "claim"]
    claim: str | None
    verdict: dict[str, Any] | None
    prose: str
    chart: dict[str, Any] | None
    sql: str | None
    rows: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    citation: Citation | None
    assumptions: list[str]
    caveats: list[str]
    attempts: int
    errors: list[ErrorRecord]
    guard: dict[str, Any] | None


class AgentState(TypedDict, total=False):
    question: str
    claim: str
    triage: dict[str, Any]
    decomposition: dict[str, Any]
    verdict: dict[str, Any]
    intent: Intent
    intake_reason: str
    context: str
    datasets: list[str]
    citation: Citation | None
    draft: dict[str, Any]
    admitted_sql: str
    attempts: int
    errors: list[ErrorRecord]
    result: dict[str, Any]
    validation_notes: list[str]
    composition: dict[str, Any]
    guard: dict[str, Any]
    regenerated: bool
    final: FinalAnswer
