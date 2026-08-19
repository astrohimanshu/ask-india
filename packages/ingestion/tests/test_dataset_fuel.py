"""PPAC metro petrol/diesel parser against a real two-page excerpt of the 25-Aug-2026 file.

The fixture is pages 1 and 35 of the cumulative PDF: 25-Aug-26 back to 30-Apr-26 (118 dates) and
21-Jun-17 back to 16-Jun-17 (6 dates, plus the footnotes). Expected values were read off the PDF.
"""

from datetime import date
from pathlib import Path

import pytest

from askindia_ingestion.contracts import RawArtifact
from askindia_ingestion.datasets.fuel import CITIES, SPEC, FuelPricesLoader, discover_pdf_url

FIXTURE = Path(__file__).parent / "fixtures" / "fuel_ppac_metro_excerpt.pdf"


def _frame():  # type: ignore[no-untyped-def]
    raw = RawArtifact.from_bytes(SPEC.key, SPEC.source_url, FIXTURE.read_bytes())
    return FuelPricesLoader(SPEC).parse(raw)


def _price(frame, day: date, city: str, fuel: str) -> float:  # type: ignore[no-untyped-def]
    sel = frame[(frame.price_date == day) & (frame.city == city) & (frame.fuel == fuel)]
    assert len(sel) == 1
    return float(sel.price_inr_per_litre.iloc[0])


def test_three_digit_prices_are_joined_not_split() -> None:
    # pdfplumber renders these as "1 02.12", "1 11.21", "1 07.77", "1 13.51".
    frame = _frame()
    latest = date(2026, 8, 25)
    assert _price(frame, latest, "Delhi", "petrol") == 102.12
    assert _price(frame, latest, "Mumbai", "petrol") == 111.21
    assert _price(frame, latest, "Chennai", "petrol") == 107.77
    assert _price(frame, latest, "Kolkata", "petrol") == 113.51
    assert _price(frame, latest, "Delhi", "diesel") == 95.20
    assert _price(frame, latest, "Mumbai", "diesel") == 97.83
    assert _price(frame, latest, "Chennai", "diesel") == 99.55
    assert _price(frame, latest, "Kolkata", "diesel") == 99.82


def test_first_day_of_dynamic_pricing_matches_the_last_page() -> None:
    frame = _frame()
    first = date(2017, 6, 16)
    assert _price(frame, first, "Delhi", "petrol") == 65.48
    assert _price(frame, first, "Mumbai", "petrol") == 76.70
    assert _price(frame, first, "Chennai", "petrol") == 68.02
    assert _price(frame, first, "Kolkata", "petrol") == 68.03
    assert _price(frame, first, "Delhi", "diesel") == 54.49
    assert _price(frame, first, "Mumbai", "diesel") == 59.90
    assert _price(frame, first, "Chennai", "diesel") == 57.41
    assert _price(frame, first, "Kolkata", "diesel") == 56.65
    # Two-digit prices ("9 4.77") and the bottom row of page 1.
    assert _price(frame, date(2026, 4, 30), "Delhi", "petrol") == 94.77
    assert _price(frame, date(2026, 4, 30), "Delhi", "diesel") == 87.67
    assert _price(frame, date(2017, 6, 21), "Mumbai", "petrol") == 75.79
    assert _price(frame, date(2017, 6, 21), "Mumbai", "diesel") == 59.34


def test_shape_is_eight_rows_per_revision_date() -> None:
    frame = _frame()
    assert list(frame.columns) == list(SPEC.column_names)
    per_date = frame.groupby("price_date").size()
    assert (per_date == 8).all()
    assert len(per_date) == 118 + 6
    assert len(frame) == 124 * 8
    assert set(frame.city) == set(CITIES)
    assert set(frame.fuel) == {"petrol", "diesel"}
    assert frame.price_date.min() == date(2017, 6, 16)
    assert frame.price_date.max() == date(2026, 8, 25)
    # Page 1 is a contiguous daily run.
    page1 = sorted(d for d in per_date.index if d.year == 2026)
    assert (page1[-1] - page1[0]).days + 1 == len(page1) == 118


def test_excerpt_passes_validation_except_row_floor() -> None:
    report = FuelPricesLoader(SPEC.model_copy(update={"min_rows": 900})).validate(_frame())
    assert report.passed


def test_discovery_picks_newest_file_by_filename_date() -> None:
    html = (
        '<a href="https://ppac.gov.in/download.php?file=whatsnew/'
        '1785476355_PP_9_a_DailyPriceMSHSD_Metro_31.07.2026.pdf">older</a>'
        '<a class="x" href="/uploads/page-images/'
        '1787642523_PP_9_a_DailyPriceMSHSD_Metro_25.08.2026.pdf" target="_BLANK">'
    )
    assert discover_pdf_url(html) == (
        "https://ppac.gov.in/uploads/page-images/"
        "1787642523_PP_9_a_DailyPriceMSHSD_Metro_25.08.2026.pdf"
    )
    with pytest.raises(ValueError, match="no PP_9_a"):
        discover_pdf_url("<html><a href='/x.pdf'>nothing</a></html>")


def test_garbage_pdf_fails_loud() -> None:
    raw = RawArtifact.from_bytes(SPEC.key, SPEC.source_url, b"%PDF-1.4 not really")
    with pytest.raises(Exception):  # noqa: B017 - pdfplumber raises its own parse error type
        FuelPricesLoader(SPEC).parse(raw)
