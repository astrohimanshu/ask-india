"""The loader contract: every outcome is a recorded LoadResult, and nothing partial is persisted."""

from pathlib import Path

import pandas as pd
import pytest

from askindia_ingestion.contracts import DatasetSpec, LoadResult, LoadStatus, version_stamp
from askindia_ingestion.loaders.mock import ExplodingLoader, MockLoader
from askindia_ingestion.validation import ValidationFailedError, validate_frame


def test_happy_path_without_persister(spec: DatasetSpec, good_csv: bytes) -> None:
    result = MockLoader(spec, good_csv).run()
    assert result.status is LoadStatus.LOADED
    assert result.row_count == 2
    assert result.validation is not None and result.validation.passed
    assert result.raw_sha256 and len(result.raw_sha256) == 64
    assert result.dataset_version.endswith(result.raw_sha256[:8])


def test_undeclared_columns_dropped_before_persist(spec: DatasetSpec, good_csv: bytes) -> None:
    seen: dict[str, object] = {}

    def persist(s: DatasetSpec, frame: pd.DataFrame, version: str, r: LoadResult) -> int:
        seen["cols"] = list(frame.columns)
        seen["version"] = version
        return len(frame)

    result = MockLoader(spec, good_csv).run(persist)
    assert result.status is LoadStatus.LOADED
    assert seen["cols"] == ["period", "airline", "pax", "share"]
    assert seen["version"] == result.dataset_version


def test_validation_failure_quarantines_and_never_calls_persister(spec: DatasetSpec) -> None:
    bad = b"period,airline,pax,share\n2024-01-01,A,-5,60.0\n2024-01-01,A,50,140.0\n"
    calls: list[str] = []

    def persist(s: DatasetSpec, frame: pd.DataFrame, version: str, r: LoadResult) -> int:
        calls.append(version)
        return len(frame)

    result = MockLoader(spec, bad).run(persist)
    assert result.status is LoadStatus.QUARANTINED
    assert result.row_count == 0
    assert calls == []
    assert result.validation is not None
    failed = {c.name for c in result.validation.failures}
    assert failed == {"range:pax", "range:share", "unique_key"}
    assert result.error and "validation failed" in result.error


def test_missing_column_is_a_quarantine(spec: DatasetSpec) -> None:
    result = MockLoader(spec, b"period,airline\n2024-01-01,A\n2024-01-01,B\n").run()
    assert result.status is LoadStatus.QUARANTINED
    assert result.validation is not None
    assert result.validation.failures[0].name == "columns_present"


def test_too_few_rows_is_a_quarantine(spec: DatasetSpec) -> None:
    result = MockLoader(spec, b"period,airline,pax,share\n2024-01-01,A,1,1\n").run()
    assert result.status is LoadStatus.QUARANTINED
    assert any(c.name == "min_rows" for c in result.validation.failures)  # type: ignore[union-attr]


@pytest.mark.parametrize("stage", ["fetch", "parse"])
def test_fetch_and_parse_errors_become_failed_results(spec: DatasetSpec, stage: str) -> None:
    result = ExplodingLoader(spec, fail_at=stage).run()
    assert result.status is LoadStatus.FAILED
    assert result.error and "simulated" in result.error
    assert (result.raw_sha256 is None) == (stage == "fetch")


def test_persister_exception_is_a_failed_result(spec: DatasetSpec, good_csv: bytes) -> None:
    def persist(s: DatasetSpec, frame: pd.DataFrame, version: str, r: LoadResult) -> int:
        raise RuntimeError("database down")

    result = MockLoader(spec, good_csv).run(persist)
    assert result.status is LoadStatus.FAILED
    assert result.row_count == 0
    assert result.error and "database down" in result.error


def test_snapshot_written_once_and_named_by_hash(
    spec: DatasetSpec, tmp_path: Path, good_csv: bytes
) -> None:
    loader = MockLoader(spec, good_csv, snapshot_dir=tmp_path)
    first = loader.run()
    second = loader.run()
    assert first.snapshot_path is not None and first.snapshot_path.exists()
    assert first.snapshot_path == second.snapshot_path
    assert first.snapshot_path.read_bytes() == good_csv
    assert first.snapshot_path.parent.name == "test_traffic"


def test_version_stamp_is_deterministic_for_identical_bytes(
    spec: DatasetSpec, good_csv: bytes
) -> None:
    a = MockLoader(spec, good_csv).fetch_raw()
    b = MockLoader(spec, good_csv).fetch_raw()
    assert version_stamp(spec, a)[-8:] == version_stamp(spec, b)[-8:]


def test_validate_frame_reports_every_failure_at_once(spec: DatasetSpec) -> None:
    frame = pd.DataFrame(
        {"period": ["p", "p"], "airline": ["A", "A"], "pax": ["x", -1], "share": [101, None]}
    )
    with pytest.raises(ValidationFailedError) as e:
        validate_frame(frame, spec)
    names = {c.name for c in e.value.report.failures}
    assert {"numeric:pax", "range:pax", "range:share", "unique_key"} <= names
