"""DGCA carrier traffic parser against two real DGCA workbooks (IndiGo 2025 and 2019)."""

import json
from datetime import date
from pathlib import Path

import pytest

from askindia_ingestion.datasets.dgca import (
    SEGMENTS,
    SPEC,
    DgcaLoader,
    listing_is_complete,
    parse_listing,
    parse_workbook,
)
from askindia_ingestion.loaders.bundle import bundle

FIXTURES = Path(__file__).parent / "fixtures"


def _frame():  # type: ignore[no-untyped-def]
    raw = bundle(
        SPEC.key,
        SPEC.source_url,
        [
            ("listing.json", b"{}"),
            ("2025|Indigo|indigo25.xlsx", (FIXTURES / "dgca_indigo25.xlsx").read_bytes()),
            ("2019|Indigo|indigo19.xlsx", (FIXTURES / "dgca_indigo19.xlsx").read_bytes()),
            ("manifest.json", b"[]"),
        ],
    )
    return DgcaLoader(SPEC).parse(raw)


def _row(frame, period: date, segment: str):  # type: ignore[no-untyped-def]
    rows = frame[(frame.period == period) & (frame.segment == segment)]
    assert len(rows) == 1, (period, segment, len(rows))
    return rows.iloc[0]


def test_2025_scheduled_domestic_matches_the_workbook() -> None:
    jan = _row(_frame(), date(2025, 1, 1), "scheduled_domestic")
    assert jan.airline == "Indigo"
    assert jan.departures == 60152
    assert jan.hours_flown == 107177.65
    assert jan.km_flown_thousand == 52567.90
    assert jan.passengers_carried == 9614311
    assert jan.passenger_km_thousand == 9125277
    assert jan.available_seat_km_thousand == 10164452
    assert jan.passenger_load_factor_pct == 89.78


def test_month_labels_july_and_jul_both_map_to_july() -> None:
    frame = _frame()
    # The domestic block spells it 'JULY', the international block 'JUL'.
    assert _row(frame, date(2025, 7, 1), "scheduled_domestic").passengers_carried == 8215364
    assert _row(frame, date(2025, 7, 1), "scheduled_international").departures == 8639
    # 2019 uses 'JUNE'.
    assert _row(frame, date(2019, 6, 1), "scheduled_domestic").passengers_carried == 5778376


def test_all_four_segments_are_read_from_the_stacked_sheet() -> None:
    frame = _frame()
    y2025 = frame[frame.period >= date(2025, 1, 1)]
    assert set(y2025.segment) == set(SEGMENTS)
    assert (y2025.groupby("segment").size() == 12).all()
    intl_cargo = _row(frame, date(2025, 1, 1), "non_scheduled_international")
    assert intl_cargo.departures == 120 and intl_cargo.passengers_carried == 0
    assert intl_cargo.passenger_load_factor_pct == 0
    assert _row(frame, date(2025, 12, 1), "non_scheduled_domestic").passengers_carried == 25987


def test_2019_layout_with_header_drift_and_blank_months() -> None:
    frame = _frame()
    y2019 = frame[frame.period < date(2020, 1, 1)]
    jan = _row(y2019, date(2019, 1, 1), "scheduled_domestic")
    assert jan.airline == "Indigo"
    assert jan.departures == 37199 and jan.passengers_carried == 5321832
    assert jan.passenger_load_factor_pct == 86.44  # published as 86.4406...
    # Non-scheduled domestic only has October-December; the international block is empty.
    per_segment = y2019.groupby("segment").size().to_dict()
    assert per_segment == {
        "scheduled_domestic": 12,
        "scheduled_international": 12,
        "non_scheduled_domestic": 3,
    }
    assert _row(y2019, date(2019, 10, 1), "non_scheduled_domestic").passengers_carried == 2018


def test_total_rows_are_skipped_and_key_is_unique() -> None:
    frame = _frame()
    assert len(frame) == 48 + 27
    assert frame.period.map(lambda d: d.day).eq(1).all()
    assert not frame.duplicated(subset=list(SPEC.unique_key)).any()
    assert list(frame.columns) == list(SPEC.column_names)


def test_totals_file_is_labelled_all_airlines() -> None:
    content = (FIXTURES / "dgca_indigo25.xlsx").read_bytes()
    records = parse_workbook(content, year=2025, listing_name="Total Domestic")
    # The workbook itself names the carrier, so the name cell wins over the listing label...
    assert {r["airline"] for r in records} == {"Indigo"}
    # ...and a listing/workbook year mismatch fails loud.
    with pytest.raises(ValueError, match="workbook says 2025"):
        parse_workbook(content, year=2024, listing_name="Indigo")


def test_listing_parser_maps_portal_paths_to_s3() -> None:
    table = (
        "<table><tbody><tr><td>1.</td><td><font>&nbsp;Indigo</font></td>"
        '<td><a data-url="jsp/dgca/InventoryList/dataReports/aviationDataStatistics/'
        'airTransport/domestic/monthly/indigo25.pdf">Click</a></td>'
        '<td><a data-url="jsp/dgca/InventoryList/dataReports/aviationDataStatistics/'
        'airTransport/domestic/monthly/indigo25.xlsx">Click</a></td></tr>'
        "<tr><td>2.</td><td>Akasa Air</td>"
        '<td><a data-url="jsp/dgca/InventoryList/dataReports/aviationDataStatistics/'
        'airTransport/domestic/monthly/akasa air 25.xlsx">Click</a></td></tr>'
        "</tbody></table>"
    )
    payload = json.dumps(
        {
            "ruleBookContentDtlsList": [
                {"contentIdentifier": "Operator (year 2025)", "contentText": table},
                {"contentIdentifier": "Operator (year 2015)", "contentText": table},
                {"contentIdentifier": "Domestic City Pair Traffic - 2025", "contentText": ""},
            ]
        }
    ).encode()
    found = parse_listing(payload)
    assert [(f.year, f.name, f.filename) for f in found] == [
        (2025, "Indigo", "indigo25.xlsx"),
        (2025, "Akasa Air", "akasa air 25.xlsx"),
    ]
    assert found[1].url == (
        "https://public-prd-dgca.s3.ap-south-1.amazonaws.com/InventoryList/dataReports/"
        "aviationDataStatistics/airTransport/domestic/monthly/akasa%20air%2025.xlsx"
    )
    assert found[0].bundle_name == "2025|Indigo|indigo25.xlsx"


def test_portal_stub_is_recognised_as_incomplete() -> None:
    # About half of identical POSTs get this single-item answer instead of the listing.
    stub = json.dumps(
        {"contentId": 4751, "contentIdentifier": "Domestic City Pair Traffic - 2022"}
    ).encode()
    assert not listing_is_complete(stub)
    assert not listing_is_complete(b"<html>maintenance</html>")
    assert listing_is_complete(
        json.dumps({"ruleBookContentDtlsList": [{"contentText": ""}, {"contentText": ""}]}).encode()
    )
    with pytest.raises(ValueError, match="no carrier XLSX"):
        parse_listing(stub)


def test_excerpt_passes_validation_except_row_floor() -> None:
    report = DgcaLoader(SPEC.model_copy(update={"min_rows": 50})).validate(_frame())
    assert report.passed
