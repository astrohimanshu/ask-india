import pytest

from askindia_ingestion.contracts import Cadence, ColumnSpec, DatasetSpec, SourceFormat


@pytest.fixture
def spec() -> DatasetSpec:
    return DatasetSpec(
        key="test_traffic",
        title="Test traffic",
        source_org="test",
        source_url="https://example.invalid/traffic.csv",
        fmt=SourceFormat.CSV,
        cadence=Cadence.MONTHLY,
        table_name="data.test_traffic",
        columns=(
            ColumnSpec(name="period", pg_type="date", description="month"),
            ColumnSpec(name="airline", pg_type="text", description="carrier"),
            ColumnSpec(name="pax", pg_type="bigint", description="passengers", min=0),
            ColumnSpec(
                name="share",
                pg_type="numeric(5,2)",
                description="share",
                unit="%",
                min=0,
                max=100,
                nullable=True,
            ),
        ),
        unique_key=("period", "airline"),
        min_rows=2,
    )


GOOD_CSV = b"period,airline,pax,share,extra\n2024-01-01,A,100,60.0,x\n2024-01-01,B,50,40.0,y\n"


@pytest.fixture
def good_csv() -> bytes:
    return GOOD_CSV
