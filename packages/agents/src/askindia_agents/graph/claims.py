"""Claim verification: triage against the catalogue, decompose into a checkable question with the
claimed value, then a verdict from documented tolerance bands. The comparison is arithmetic, not
a model opinion; the model only extracts and phrases."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

Verdict = Literal["Supported", "Misleading", "Contradicted", "Unverifiable"]
TriageClass = Literal["checkable", "statistical_uncovered", "not_statistical"]
Comparison = Literal["value", "greater", "less", "ratio", "change_pct"]


class TriageDecision(BaseModel):
    triage: TriageClass
    dataset: str | None = Field(default=None, description="catalogue dataset key if checkable")
    reason: str = ""
    data_needed: str = Field(default="", description="what dataset would be needed if uncovered")


class Decomposition(BaseModel):
    question: str = Field(min_length=3, description="the question whose answer decides the claim")
    claimed_value: float | None = Field(default=None, description="number asserted by the claim")
    comparison: Comparison = Field(
        default="value",
        description=(
            "value: claim states a number; greater/less: claim says A is greater/less than B "
            "(question must return A and B); ratio: claim says A is k times B (claimed_value=k); "
            "change_pct: claim says something changed by k percent (claimed_value=k)"
        ),
    )
    unit: str = Field(default="", description="unit of claimed_value, e.g. 'lakh passengers', '%'")
    scale: float = Field(
        default=1.0, description="multiply claimed_value by this to match the data's unit"
    )


class VerdictProse(BaseModel):
    prose: str = Field(min_length=1)
    caveats: list[str] = Field(default_factory=list)


# Tolerance bands (documented in the UI): within ±10 % of the official figure → Supported; same
# sign and within a factor of two either way → Misleading; otherwise Contradicted.
SUPPORTED_TOL = 0.10
MISLEADING_FACTOR = 2.0


@dataclass(frozen=True)
class VerdictResult:
    verdict: Verdict
    claimed: float | None
    actual: float | None
    relative_error: float | None
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "claimed": self.claimed,
            "actual": self.actual,
            "relative_error": self.relative_error,
            "explanation": self.explanation,
            "tolerance": {
                "supported_within": SUPPORTED_TOL,
                "misleading_factor": MISLEADING_FACTOR,
            },
        }


def _numbers(row: dict[str, Any]) -> list[float]:
    out: list[float] = []
    for v in row.values():
        if isinstance(v, bool) or v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def judge(decomp: Decomposition, rows: list[dict[str, Any]]) -> VerdictResult:
    """Compare the claimed figure with the computed rows under the tolerance bands."""
    if not rows:
        return VerdictResult(
            "Unverifiable", decomp.claimed_value, None, None, "the query returned no rows"
        )
    nums = _numbers(rows[0]) if len(rows) == 1 else [n for r in rows for n in _numbers(r)]

    if decomp.comparison in ("greater", "less"):
        if len(rows) == 2:
            a, b = (_numbers(rows[0]) or [math.nan])[-1], (_numbers(rows[1]) or [math.nan])[-1]
        elif len(nums) >= 2:
            a, b = nums[0], nums[1]
        else:
            return VerdictResult("Unverifiable", None, None, None, "need two values to compare")
        holds = a > b if decomp.comparison == "greater" else a < b
        margin = abs(a - b) / max(abs(b), 1e-9)
        if holds:
            if margin < 0.02:
                return VerdictResult(
                    "Misleading", a, b, margin, "true, but the difference is under 2 %"
                )
            return VerdictResult("Supported", a, b, margin, "the comparison holds in the data")
        return VerdictResult("Contradicted", a, b, margin, "the data shows the opposite")

    if decomp.claimed_value is None:
        return VerdictResult(
            "Unverifiable", None, nums[0] if nums else None, None, "no number was claimed"
        )
    claimed = decomp.claimed_value * (decomp.scale or 1.0)
    if not nums:
        return VerdictResult("Unverifiable", claimed, None, None, "the result has no numeric value")
    actual = nums[-1] if len(rows) == 1 else nums[0]
    if actual == 0:
        rel = math.inf if claimed != 0 else 0.0
    else:
        rel = abs(claimed - actual) / abs(actual)
    same_direction = (claimed >= 0) == (actual >= 0)
    factor = (
        max(abs(claimed), abs(actual)) / min(abs(claimed), abs(actual))
        if claimed and actual
        else math.inf
    )
    if rel <= SUPPORTED_TOL:
        return VerdictResult(
            "Supported",
            claimed,
            actual,
            rel,
            f"claimed {claimed:g} vs actual {actual:g}, within ±{SUPPORTED_TOL:.0%}",
        )
    if same_direction and factor <= MISLEADING_FACTOR:
        return VerdictResult(
            "Misleading",
            claimed,
            actual,
            rel,
            f"right direction but claimed {claimed:g} vs actual {actual:g} ({rel:.0%} off)",
        )
    return VerdictResult(
        "Contradicted", claimed, actual, rel, f"claimed {claimed:g} vs actual {actual:g}"
    )
