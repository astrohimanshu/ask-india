"""Programmatic groundedness guard: every numeral in the prose must come from the result rows.

Not an LLM. Numerals are extracted from the composed text, normalised (thousands separators,
percent signs, lakh/crore words, rounding) and matched against every numeric value present in
the rows, including values reachable by the rounding the composer is allowed to do. Years that
appear as row values count as grounded; small integers (1-12) used as ordinary words do not need
grounding. Anything else fails the guard.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

_NUMERAL = re.compile(
    r"(?<![\w.\-])(-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)(?![\w\-])"
    r"\s*(lakh|crore|million|billion|thousand|%)?",
    re.IGNORECASE,
)
_SCALE = {"thousand": 1e3, "lakh": 1e5, "million": 1e6, "crore": 1e7, "billion": 1e9}
_ORDINARY_MAX = 12  # "one of the 5 largest" — small counts are prose, not data


@dataclass
class GuardReport:
    passed: bool
    numerals: list[str] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "numerals": self.numerals, "ungrounded": self.ungrounded}


def _row_values(rows: list[dict[str, Any]]) -> set[float]:
    values: set[float] = set()
    for row in rows:
        for v in row.values():
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, int | float | Decimal):
                f = float(v)
                if math.isfinite(f):
                    values.add(f)
            elif isinstance(v, datetime | date):
                values.update({float(v.year), float(v.month), float(v.day)})
            elif isinstance(v, str):
                for m in re.finditer(r"-?\d+(?:\.\d+)?", v):
                    values.add(float(m.group()))
    return values


def _matches(candidate: float, values: set[float]) -> bool:
    for v in values:
        if v == candidate:
            return True
        # the composer may round to 0-2 decimals, or present a large number in lakh/crore/million
        for digits in (0, 1, 2):
            if round(v, digits) == candidate:
                return True
        if abs(v) >= 1000 and candidate != 0:
            for scale in _SCALE.values():
                scaled = v / scale
                if any(round(scaled, d) == candidate for d in (0, 1, 2)):
                    return True
        if abs(v) >= 1 and candidate != 0 and abs(v - candidate) / abs(v) < 5e-4:
            return True
    return False


def extract_numerals(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for m in _NUMERAL.finditer(text):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        value = float(raw.replace(",", ""))
        if unit in _SCALE:
            value *= _SCALE[unit]
        out.append((m.group(0).strip(), value))
    return out


def check_groundedness(
    prose: str, rows: list[dict[str, Any]], *, provenance_text: str = ""
) -> GuardReport:
    """``provenance_text`` is text whose numerals are grounded by construction — the user's own
    question, the SQL that was executed (its literals), and the citation (dataset version,
    coverage). Anything else must come from the rows."""
    values = _row_values(rows)
    values.update(v for _, v in extract_numerals(provenance_text))
    numerals = extract_numerals(prose)
    ungrounded: list[str] = []
    for raw, value in numerals:
        if value.is_integer() and 0 <= value <= _ORDINARY_MAX and "%" not in raw and "," not in raw:
            continue
        if _matches(value, values):
            continue
        # a scaled numeral ("12.1 crore") whose base ("12.1") is in the rows as-is
        base = float(re.sub(r"[^\d.\-]", "", raw.split()[0])) if raw else value
        if base != value and _matches(base, values):
            continue
        ungrounded.append(raw)
    return GuardReport(
        passed=not ungrounded, numerals=[r for r, _ in numerals], ungrounded=ungrounded
    )
