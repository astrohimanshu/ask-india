"""Census 2011 PCA parser against a real excerpt of the ORGI workbook (India + J&K rows)."""

from pathlib import Path

from askindia_ingestion.contracts import RawArtifact
from askindia_ingestion.datasets.census import SPEC, CensusLoader

FIXTURE = Path(__file__).parent / "fixtures" / "census_pca_excerpt.xlsx"


def _frame():  # type: ignore[no-untyped-def]
    raw = RawArtifact.from_bytes(SPEC.key, SPEC.source_url, FIXTURE.read_bytes())
    return CensusLoader(SPEC).parse(raw)


def test_india_totals_match_the_published_figures() -> None:
    frame = _frame()
    india = frame[(frame.level == "INDIA") & (frame.tru == "Total")].iloc[0]
    assert india.population_total == 1_210_854_977
    assert india.population_male == 623_270_258
    assert india.households == 249_501_663
    rural = frame[(frame.level == "INDIA") & (frame.tru == "Rural")].iloc[0]
    assert rural.population_total == 833_748_852


def test_state_and_district_rows_are_coded() -> None:
    frame = _frame()
    jk = frame[(frame.level == "STATE") & (frame.tru == "Total")].iloc[0]
    assert jk["name"] == "JAMMU & KASHMIR" and jk.state_code == "01" and jk.district_code == "000"
    assert jk.population_total == 12_541_302
    districts = frame[frame.level == "DISTRICT"]
    assert not districts.empty and (districts.state_code == "01").all()
    assert set(frame.tru) == {"Total", "Rural", "Urban"}


def test_excerpt_passes_validation_except_row_floor() -> None:
    frame = _frame()
    report = CensusLoader(SPEC.model_copy(update={"min_rows": 10})).validate(frame)
    assert report.passed
