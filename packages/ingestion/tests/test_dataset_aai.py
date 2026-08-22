"""AAI Annexure-III passenger parser against the real June 2025 file.

The fixture is Jun2k25Annex3.pdf as published (all 7 pages), recompressed with pypdf to fit the
repository size limit; the content streams are unchanged. Expected values were read off the PDF.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from askindia_ingestion.contracts import RawArtifact
from askindia_ingestion.datasets.aai import (
    SPEC,
    TRAFFIC_TYPES,
    AaiAirportTrafficLoader,
    combine_reports,
    discover_annexure3_links,
    parse_annexure3,
    year_listing_url,
)
from askindia_ingestion.loaders.bundle import bundle

FIXTURE = Path(__file__).parent / "fixtures" / "aai_jun2k25_annex3.pdf"
JUN25, JUN24 = date(2025, 6, 1), date(2024, 6, 1)


def _frame() -> pd.DataFrame:
    raw = bundle(SPEC.key, SPEC.source_url, [("01_Jun2k25Annex3.pdf", FIXTURE.read_bytes())])
    return AaiAirportTrafficLoader(SPEC).parse(raw)


def _pax(frame: pd.DataFrame, period: date, airport: str, traffic_type: str) -> int:
    sel = frame[
        (frame.period == period) & (frame.airport == airport) & (frame.traffic_type == traffic_type)
    ]
    assert len(sel) == 1, f"{airport} {traffic_type} {period}: {len(sel)} rows"
    return int(sel.passengers.iloc[0])


def test_metro_airports_match_the_published_tables() -> None:
    frame = _frame()
    # Page 1, Annexure-IIIA International.
    assert _pax(frame, JUN25, "Delhi", "international") == 1705780
    assert _pax(frame, JUN25, "Mumbai (Mial)", "international") == 1280195
    assert _pax(frame, JUN25, "Bengaluru (Bial)", "international") == 555388
    assert _pax(frame, JUN25, "Hyderabad (Ghial)", "international") == 442592
    assert _pax(frame, JUN25, "Chennai", "international") == 513300
    assert _pax(frame, JUN25, "Kolkata", "international") == 186049
    assert _pax(frame, JUN25, "Amritsar", "international") == 82151
    assert _pax(frame, JUN25, "Nasik (Hal Ozar)", "international") == 152
    # Pages 2-4, Annexure-IIIB Domestic (Begumpet and HAL are on the continuation page 3).
    assert _pax(frame, JUN25, "Delhi", "domestic") == 4456863
    assert _pax(frame, JUN25, "Mumbai (Mial)", "domestic") == 3152371
    assert _pax(frame, JUN25, "Bengaluru (Bial)", "domestic") == 3083167
    assert _pax(frame, JUN25, "Hyderabad (Ghial)", "domestic") == 2183315
    assert _pax(frame, JUN25, "Chennai", "domestic") == 1410205
    assert _pax(frame, JUN25, "Hyderabad (Begumpet)", "domestic") == 895
    assert _pax(frame, JUN25, "Bengaluru (Hal)", "domestic") == 1494
    assert _pax(frame, JUN25, "Durgapur", "domestic") == 49408
    assert _pax(frame, JUN25, "Ziro", "domestic") == 67
    # Pages 5-7, Annexure-IIIC Total.
    assert _pax(frame, JUN25, "Delhi", "total") == 6162643
    assert _pax(frame, JUN25, "Mumbai (Mial)", "total") == 4432566
    assert _pax(frame, JUN25, "Bengaluru (Bial)", "total") == 3638555
    assert _pax(frame, JUN25, "Chennai", "total") == 1923505
    assert _pax(frame, JUN25, "Ziro", "total") == 67


def test_same_month_previous_year_column_is_emitted_for_june_2024() -> None:
    frame = _frame()
    assert set(frame.period) == {JUN25, JUN24}
    assert _pax(frame, JUN24, "Delhi", "international") == 1758498
    assert _pax(frame, JUN24, "Mumbai (Mial)", "domestic") == 3130650
    assert _pax(frame, JUN24, "Bengaluru (Bial)", "total") == 3321878
    assert _pax(frame, JUN24, "Amritsar", "international") == 92504
    assert _pax(frame, JUN24, "Ziro", "domestic") == 0
    # Every June 2025 row has its June 2024 counterpart and vice versa.
    a = frame[frame.period == JUN25].set_index(["airport", "traffic_type"]).index
    b = frame[frame.period == JUN24].set_index(["airport", "traffic_type"]).index
    assert set(a) == set(b)


def test_airport_rows_sum_to_the_grand_totals_and_no_total_rows_leak() -> None:
    frame = _frame()
    assert list(frame.columns) == list(SPEC.column_names)
    sums = frame.groupby(["period", "traffic_type"]).passengers.sum()
    assert sums[(JUN25, "international")] == 6436961
    assert sums[(JUN25, "domestic")] == 27572024
    assert sums[(JUN25, "total")] == 34008985
    assert sums[(JUN24, "international")] == 6225697
    assert sums[(JUN24, "domestic")] == 26582752
    assert sums[(JUN24, "total")] == 32808449
    names = frame.airport
    assert not names.str.contains("total|airports|annexure", case=False).any()
    assert names.map(lambda n: n.isascii() and n == n.strip() and "  " not in n).all()
    assert names.map(lambda n: n == n.title()).all()
    assert set(frame.traffic_type) == set(TRAFFIC_TYPES)
    assert frame.passengers.dtype == "int64"
    # International passengers never exceed the airport's total.
    wide = frame.pivot_table(
        index=["period", "airport"], columns="traffic_type", values="passengers", aggfunc="first"
    ).dropna()
    assert (wide["international"] <= wide["total"]).all()
    assert (wide["domestic"] <= wide["total"]).all()


def test_fixture_passes_validation_except_row_floor() -> None:
    report = AaiAirportTrafficLoader(SPEC.model_copy(update={"min_rows": 500})).validate(_frame())
    assert report.passed


def _report(
    name: str, period: date, prev: date, pax: int, prev_pax: int
) -> tuple[str, pd.DataFrame]:
    return name, pd.DataFrame(
        {
            "period": [period],
            "airport": ["Delhi"],
            "traffic_type": ["total"],
            "passengers": [pax],
            "prev_period": [prev],
            "prev_passengers": [prev_pax],
        }
    )


def test_direct_report_beats_previous_year_column_and_repeat_months_are_skipped() -> None:
    reports = [
        _report("01_Jun2k26.pdf", date(2026, 6, 1), JUN25, 10, 8),
        _report("02_Jun2k25.pdf", JUN25, JUN24, 9, 7),
        _report("03_Jun2k25-rev.pdf", JUN25, JUN24, 99, 77),  # same month again: ignored
    ]
    out = combine_reports(reports)
    got = {(r.period, r.passengers) for r in out.itertuples()}
    assert got == {(date(2026, 6, 1), 10), (JUN25, 9), (JUN24, 7)}
    assert list(out.columns) == list(SPEC.column_names)


def test_discovery_uses_link_text_not_filename() -> None:
    html = (
        '<a href="https://www.aai.aero/sites/default/files/traffic-news/Nov2k25Annex1_2.pdf" '
        'target="_blank">Annexure-II-Aircraft Movement</a>'
        '<a href="https://www.aai.aero/sites/default/files/traffic-news/Nov2k25Annex1_3.pdf" '
        'target="_blank">Annexure-III-Passengers</a>'
        '<div class="down-load-traffic"><a href="https://www.aai.aero/sites/default/files/'
        'traffic-news/Nov2k25Annex1_3.pdf">Annexure-III-Passengers</a></div>'
        '<a href="/sites/default/files/traffic-news/Sep2k25Annex3%20.pdf">'
        "Annexure-III-Passengers</a>"
        '<a href="https://www.aai.aero/sites/default/files/traffic-news/Oct2k25Annex4.pdf">'
        "Annexure-IV-Freight</a>"
    )
    assert discover_annexure3_links(html) == [
        "https://www.aai.aero/sites/default/files/traffic-news/Nov2k25Annex1_3.pdf",
        "https://www.aai.aero/sites/default/files/traffic-news/Sep2k25Annex3%20.pdf",
    ]
    assert discover_annexure3_links("<a href='/x.pdf'>nothing</a>") == []
    assert year_listing_url(2025) == (
        "https://www.aai.aero/en/business-opportunities/aai-traffic-news"
        "?field_news_date_value%5Bvalue%5D%5Byear%5D=2025"
    )


def test_garbage_pdf_fails_loud() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pdfplumber raises its own parse error type
        parse_annexure3(b"%PDF-1.4 not really")
    raw = RawArtifact.from_bytes(SPEC.key, SPEC.source_url, b"PK not a zip either")
    with pytest.raises(Exception):  # noqa: B017 - zipfile.BadZipFile
        AaiAirportTrafficLoader(SPEC).parse(raw)
