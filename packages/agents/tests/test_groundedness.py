"""The guard is programmatic: numerals in prose must be derivable from result rows."""

from datetime import date
from decimal import Decimal

import pytest

from askindia_agents.groundedness import check_groundedness, extract_numerals

ROWS = [
    {
        "name": "UTTAR PRADESH",
        "population_total": 199812341,
        "share_pct": Decimal("16.50"),
        "as_of": date(2011, 3, 1),
    },
    {
        "name": "MAHARASHTRA",
        "population_total": 112374333,
        "share_pct": Decimal("9.28"),
        "as_of": date(2011, 3, 1),
    },
]


@pytest.mark.parametrize(
    "prose",
    [
        "Uttar Pradesh had 199,812,341 people, 16.5% of India.",
        "About 19.98 crore people lived in Uttar Pradesh in 2011.",
        "Maharashtra: 112.4 million (9.28 percent) as of 1 March 2011.",
        "Two states are shown; the larger has 199812341 residents.",
        "Roughly 200 million people (rounded) lived there.",
    ],
)
def test_grounded_prose_passes(prose: str) -> None:
    report = check_groundedness(prose, ROWS, provenance_text="population in 2011")
    assert report.passed, report.ungrounded


@pytest.mark.parametrize(
    ("prose", "bad"),
    [
        ("Uttar Pradesh had 250,000,000 people.", ["250,000,000"]),
        ("The share was 17.9%.", ["17.9%"]),
        ("Population grew 12.5% since 2001.", ["12.5%", "2001"]),
        ("As of 2011 it was 199,812,341, up from 166,197,921 in 2001.", ["166,197,921", "2001"]),
        ("It has 75 districts.", ["75"]),
    ],
)
def test_invented_numbers_fail(prose: str, bad: list[str]) -> None:
    report = check_groundedness(prose, ROWS)
    assert not report.passed
    assert report.ungrounded == bad


def test_small_counts_used_as_words_are_ignored() -> None:
    assert check_groundedness("One of the 2 states listed; top 5 are not shown.", ROWS).passed


def test_question_and_sql_numerals_are_provenance() -> None:
    prose = (
        "Since 2001 the top state's population reached 199,812,341 (version 2026-08-25-7a8f70d4)."
    )
    assert check_groundedness(prose, ROWS).ungrounded == ["2001"]
    ok = check_groundedness(prose, ROWS, provenance_text="How did population change since 2001?")
    assert ok.passed, ok.ungrounded


def test_extract_numerals_handles_indian_grouping_and_units() -> None:
    found = extract_numerals("19,98,12,341 people, 1.2 lakh more, 3 crore, 45%")
    assert [v for _, v in found] == [199812341.0, 120000.0, 30000000.0, 45.0]
