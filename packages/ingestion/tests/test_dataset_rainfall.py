"""IMD subdivision rainfall parser against two real IMD Pune pages."""

from pathlib import Path

from askindia_ingestion.datasets.rainfall import SPEC, RainfallLoader, parse_index
from askindia_ingestion.loaders.bundle import bundle

FIXTURES = Path(__file__).parent / "fixtures"


def _frame():  # type: ignore[no-untyped-def]
    raw = bundle(
        SPEC.key,
        SPEC.source_url,
        [
            (
                "anisland.html|Andaman & Nicobar Islands",
                (FIXTURES / "rainfall_anisland.html").read_bytes(),
            ),
            ("lakshadweep.html|Lakshadweep", (FIXTURES / "rainfall_lakshadweep.html").read_bytes()),
        ],
    )
    return RainfallLoader(SPEC).parse(raw)


def test_values_match_the_published_table() -> None:
    frame = _frame()
    andaman = frame[frame.subdivision == "Andaman & Nicobar Islands"].set_index(["year", "month"])
    assert andaman.loc[(1901, "Jan"), "rainfall_mm"] == 49.2
    assert andaman.loc[(1901, "Annual"), "rainfall_mm"] == 3373.2
    assert andaman.loc[(1902, "Jan"), "rainfall_mm"] == 0.0
    assert andaman.loc[(2025, "Jun"), "rainfall_mm"] == 643.7
    assert andaman.loc[(1901, "Jan"), "normal_mm"] == 56.4
    assert andaman.loc[(2025, "Annual"), "normal_mm"] == 2838.2


def test_shape_is_long_with_thirteen_rows_per_year() -> None:
    frame = _frame()
    per_year = frame.groupby(["subdivision", "year"]).size()
    assert (per_year == 13).all()
    assert set(frame.subdivision) == {"Andaman & Nicobar Islands", "Lakshadweep"}
    assert frame.year.min() == 1901 and frame.year.max() >= 2024


def test_index_parser_handles_sloppy_markup() -> None:
    html = (
        '<option value="anisland.html">Andaman & Nicobar Islands</option>'
        '<option value= "arunachalpradesh.html">Arunachal Pradesh</option>'
        '<option value="jharkhand.html"> Jharkhand</option>'
    )
    assert parse_index(html) == [
        ("anisland.html", "Andaman & Nicobar Islands"),
        ("arunachalpradesh.html", "Arunachal Pradesh"),
        ("jharkhand.html", "Jharkhand"),
    ]


def test_excerpt_passes_validation_except_row_floor() -> None:
    report = RainfallLoader(SPEC.model_copy(update={"min_rows": 100})).validate(_frame())
    assert report.passed
