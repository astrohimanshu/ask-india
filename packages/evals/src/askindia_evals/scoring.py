"""Result equivalence for execution accuracy.

Two queries are equivalent when they return the same information, not the same text. The gold
result's rows must be matched one-to-one by predicted rows: every gold value in a row must appear
among that predicted row's values (so extra predicted columns are fine), numbers compare with a
small relative tolerance (rounding differences), strings compare case- and whitespace-
insensitively, and dates compare by their ISO form.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

REL_TOL = 5e-3  # 0.5 %: covers rounding to 2 decimals on any value above ~0.2
_WS = re.compile(r"\s+")


def normalise(value: Any) -> float | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | Decimal):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, datetime | date):
        return value.isoformat()[:10]
    text = _WS.sub(" ", str(value)).strip().lower()
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return text


def values_match(gold: Any, pred: Any) -> bool:
    g, p = normalise(gold), normalise(pred)
    if isinstance(g, float) and isinstance(p, float):
        if g == p:
            return True
        return abs(g - p) <= REL_TOL * max(abs(g), abs(p), 1e-9) or abs(g - p) < 0.005
    if isinstance(g, str) and isinstance(p, str):
        return g == p or (len(g) > 3 and (g in p or p in g))
    if isinstance(g, str) and isinstance(p, float):
        return _year_like(g, p)
    if isinstance(g, float) and isinstance(p, str):
        return _year_like(p, g)
    return g == p


def _year_like(text: str, number: float) -> bool:
    return number.is_integer() and text.startswith(str(int(number)))


def row_matches(gold_row: dict[str, Any], pred_row: dict[str, Any]) -> bool:
    remaining = list(pred_row.values())
    for gv in gold_row.values():
        for i, pv in enumerate(remaining):
            if values_match(gv, pv):
                remaining.pop(i)
                break
        else:
            return False
    return True


@dataclass(frozen=True)
class Score:
    correct: bool
    reason: str


def score_result(gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]) -> Score:
    if not gold_rows:
        return Score(False, "gold returned no rows")
    if not pred_rows:
        return Score(False, "prediction returned no rows")
    if len(pred_rows) != len(gold_rows):
        return Score(False, f"row count {len(pred_rows)} != gold {len(gold_rows)}")
    unmatched = list(pred_rows)
    for g in gold_rows:
        for i, p in enumerate(unmatched):
            if row_matches(g, p):
                unmatched.pop(i)
                break
        else:
            return Score(False, f"no predicted row matches gold row {g}")
    return Score(True, "rows equivalent")
