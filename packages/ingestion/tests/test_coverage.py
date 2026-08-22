"""Catalogue coverage is derived from the right column for each kind of dataset."""

from datetime import date

import pandas as pd

from askindia_ingestion.contracts import DatasetSpec
from askindia_ingestion.persistence import coverage_bounds


def test_period_column(spec: DatasetSpec) -> None:
    frame = pd.DataFrame({"period": [date(2024, 3, 1), date(2024, 1, 1)]})
    assert coverage_bounds(spec, frame) == ("2024-01-01", "2024-03-01")


def test_crop_year_and_static(spec: DatasetSpec) -> None:
    s = spec.model_copy(update={"coverage_column": "crop_year"})
    frame = pd.DataFrame({"crop_year": ["2021-22", "2025-26"]})
    assert coverage_bounds(s, frame) == ("2021-07-01", "2026-06-30")
    fixed = spec.model_copy(update={"coverage_static": (date(2011, 3, 1), date(2011, 3, 1))})
    assert coverage_bounds(fixed, pd.DataFrame()) == ("2011-03-01", "2011-03-01")


def test_no_date_column_is_unknown(spec: DatasetSpec) -> None:
    assert coverage_bounds(spec, pd.DataFrame({"x": [1]})) == (None, None)
