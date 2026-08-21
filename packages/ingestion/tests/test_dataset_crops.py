"""DA&FW crop estimates parser against a real four-sheet excerpt (Rice, Wheat, Maize, Cotton)
of the 'Five-Years 2021-22 to 2025-26 (3rd AE)' workbook. Values below were read off the sheets.
"""

from pathlib import Path

import pandas as pd
import pytest

from askindia_ingestion.contracts import RawArtifact
from askindia_ingestion.datasets.crops import (
    SPEC,
    CropProductionLoader,
    advance_years,
    discover_xlsx_url,
)

FIXTURE = Path(__file__).parent / "fixtures" / "crops_five_year_excerpt.xlsx"
YEARS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    raw = RawArtifact.from_bytes(SPEC.key, SPEC.source_url, FIXTURE.read_bytes())
    return CropProductionLoader(SPEC).parse(raw)


def _row(frame: pd.DataFrame, crop: str, state: str, season: str, year: str) -> pd.Series:
    hit = frame[
        (frame.crop == crop)
        & (frame.state == state)
        & (frame.season == season)
        & (frame.crop_year == year)
    ]
    assert len(hit) == 1, (crop, state, season, year)
    return hit.iloc[0]


def test_shape_is_long_with_one_row_per_crop_state_season_year(frame: pd.DataFrame) -> None:
    assert list(frame.columns) == list(SPEC.column_names)
    assert set(frame.crop) == {"Rice", "Wheat", "Maize", "Cotton"}
    assert sorted(frame.crop_year.unique()) == YEARS
    assert set(frame.season) <= set(SPEC.columns[2].allowed or ())
    assert (frame.groupby(["crop", "state", "season"]).size() <= 5).all()
    assert not frame.duplicated(subset=list(SPEC.unique_key)).any()


def test_rice_values_match_the_sheet(frame: pd.DataFrame) -> None:
    # Rice sheet, block for Andhra Pradesh: Kharif row, first column of each measure.
    kharif = _row(frame, "Rice", "Andhra Pradesh", "Kharif", "2021-22")
    assert kharif.area_thousand_ha == 1508
    assert kharif.production_thousand_tonnes == 4326.45
    assert kharif.yield_kg_per_ha == 2869
    assert kharif.estimate_type == "final"
    # Rabi row, last (2025-26) column of each measure.
    rabi = _row(frame, "Rice", "Andhra Pradesh", "Rabi", "2025-26")
    assert rabi.area_thousand_ha == 916
    assert rabi.production_thousand_tonnes == 4258.48
    assert rabi.yield_kg_per_ha == 4649
    assert rabi.estimate_type == "3rd advance estimate"
    # Last data block: All India / Total.
    india = _row(frame, "Rice", "All India", "Total", "2025-26")
    assert india.area_thousand_ha == 52832.42
    assert india.production_thousand_tonnes == 154024.26
    assert india.yield_kg_per_ha == 2915


def test_estimate_type_follows_the_sheet_footnote(frame: pd.DataFrame) -> None:
    by_year = frame.groupby("crop_year").estimate_type.unique()
    for year in YEARS[:-1]:
        assert list(by_year[year]) == ["final"]
    assert list(by_year["2025-26"]) == ["3rd advance estimate"]
    assert advance_years(["Data for the year 2025-26 is of 3ʳᵈ Advance Estimates"]) == {
        "2025-26": "3rd advance estimate"
    }
    assert advance_years(["Data for the year 2026-27 is of 1st Advance Estimates"]) == {
        "2026-27": "1st advance estimate"
    }
    assert advance_years(["Source: DA&FW"]) == {}


def test_blank_year_columns_are_dropped_and_single_blanks_are_null(frame: pd.DataFrame) -> None:
    # A&N Islands rice has no 2025-26 figures at all; the other four years are present.
    an = frame[(frame.crop == "Rice") & (frame.state == "A&N Islands") & (frame.season == "Kharif")]
    assert sorted(an.crop_year) == YEARS[:-1]
    assert _row(frame, "Rice", "A&N Islands", "Kharif", "2024-25").area_thousand_ha == 4.37
    # All India summer rice is blank for 2021-22 only.
    summer = frame[
        (frame.crop == "Rice") & (frame.state == "All India") & (frame.season == "Summer")
    ]
    assert sorted(summer.crop_year) == YEARS[1:]
    assert _row(frame, "Rice", "All India", "Summer", "2022-23").area_thousand_ha == 3100.88
    # Maize A&N Rabi: zeros in 2021-22 are kept as 0, 2022-23 and 2023-24 blank rows are dropped.
    zero = _row(frame, "Maize", "Andaman And Nicobar Islands", "Rabi", "2021-22")
    assert (zero.area_thousand_ha, zero.production_thousand_tonnes, zero.yield_kg_per_ha) == (
        0,
        0,
        0,
    )
    maize_an = frame[
        (frame.crop == "Maize")
        & (frame.state == "Andaman And Nicobar Islands")
        & (frame.season == "Rabi")
    ]
    assert sorted(maize_an.crop_year) == ["2021-22", "2024-25"]
    assert (
        _row(
            frame, "Maize", "Andaman And Nicobar Islands", "Rabi", "2024-25"
        ).production_thousand_tonnes
        == 0.03
    )


def test_wheat_crop_name_comes_from_the_title_when_the_crop_cell_is_empty(
    frame: pd.DataFrame,
) -> None:
    wheat = frame[frame.crop == "Wheat"]
    assert not wheat.empty
    assert set(wheat.season) == {"Rabi"}
    bihar = _row(frame, "Wheat", "Bihar", "Rabi", "2023-24")
    assert bihar.area_thousand_ha == 2275.58
    assert bihar.production_thousand_tonnes == 7168.07
    assert bihar.yield_kg_per_ha == 3150


def test_cotton_bales_are_converted_with_the_factor_printed_on_the_sheet(
    frame: pd.DataFrame,
) -> None:
    # Sheet: Gujarat Kharif 2021-22 area 2283.7, production 7509.34 thousand bales, yield 559;
    # footnote '# Cotton Production in Thousand Bales, 1Bale=170 Kg'.
    gujarat = _row(frame, "Cotton", "Gujarat", "Kharif", "2021-22")
    assert gujarat.area_thousand_ha == 2283.7
    assert gujarat.production_thousand_tonnes == round(7509.34 * 170 / 1000, 2)
    assert gujarat.yield_kg_per_ha == 559
    # The published yield is consistent with the converted production.
    assert gujarat.production_thousand_tonnes * 1000 / gujarat.area_thousand_ha == pytest.approx(
        559, abs=1
    )
    india = _row(frame, "Cotton", "All India", "Kharif", "2021-22")
    assert india.production_thousand_tonnes == round(31117.59 * 170 / 1000, 2)


def test_footnote_rows_never_become_data(frame: pd.DataFrame) -> None:
    assert not frame.crop.str.contains("Advance|Bale", regex=True).any()
    assert not frame.state.str.contains("Advance|Bale", regex=True).any()


def test_listing_page_link_discovery() -> None:
    html = """
    <a href="/wp-content/uploads/2025/01/Normal-Estimates.pdf">pdf</a>
    <a href="https://desagri.gov.in/wp-content/uploads/2026/06/Five-Years-2021-22-to-2025-263rd-AE.xlsx"
       target="_blank">Download File (English)</a>
    <a href="/wp-content/uploads/2024/01/Something-else.xlsx">other</a>
    """
    assert discover_xlsx_url(html) == (
        "https://desagri.gov.in/wp-content/uploads/2026/06/Five-Years-2021-22-to-2025-263rd-AE.xlsx"
    )
    assert discover_xlsx_url('<a href="/uploads/only.xlsx">x</a>') == (
        "https://desagri.gov.in/uploads/only.xlsx"
    )
    with pytest.raises(ValueError, match=r"no \.xlsx link"):
        discover_xlsx_url('<a href="/uploads/only.pdf">x</a>')
    with pytest.raises(ValueError, match="none is a five-year"):
        discover_xlsx_url('<a href="/a.xlsx">x</a><a href="/b.xlsx">y</a>')


def test_excerpt_passes_validation_except_row_floor(frame: pd.DataFrame) -> None:
    report = CropProductionLoader(SPEC.model_copy(update={"min_rows": 100})).validate(frame)
    assert report.passed
