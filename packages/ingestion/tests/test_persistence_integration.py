"""Against the real local database: loads are atomic and a quarantine leaves the table untouched."""

import os

import psycopg
import pytest

from askindia_ingestion.contracts import DatasetSpec, LoadStatus
from askindia_ingestion.loaders.mock import MockLoader
from askindia_ingestion.persistence import PostgresPersister

pytestmark = pytest.mark.integration

DSN = os.environ.get("DATABASE_URL", "")
DSN_RO = os.environ.get("DATABASE_URL_RO", "")


@pytest.fixture(autouse=True)
def clean(spec: DatasetSpec) -> None:
    if not DSN:
        pytest.skip("DATABASE_URL not set")
    with psycopg.connect(DSN) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {spec.table_name}")
        conn.execute("DELETE FROM meta.dataset_runs WHERE dataset = %s", (spec.key,))
        conn.execute("DELETE FROM meta.datasets WHERE dataset = %s", (spec.key,))


def _count(table: str, dsn: str = DSN) -> int:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        return int(row[0]) if row else -1


def test_load_then_quarantine_keeps_previous_version(spec: DatasetSpec, good_csv: bytes) -> None:
    persister = PostgresPersister(DSN)

    first = MockLoader(spec, good_csv).run(persister)
    assert first.status is LoadStatus.LOADED and first.row_count == 2
    assert _count(spec.table_name) == 2
    with psycopg.connect(DSN_RO) as ro:
        versions = {r[0] for r in ro.execute(f"SELECT dataset_version FROM {spec.table_name}")}
    assert versions == {first.dataset_version}

    bad = b"period,airline,pax,share\n2024-02-01,A,-1,10\n2024-02-01,B,5,10\n"
    second = MockLoader(spec, bad).run(persister)
    persister.record(second)
    assert second.status is LoadStatus.QUARANTINED
    assert _count(spec.table_name) == 2, "quarantine must not touch the table"

    with psycopg.connect(DSN) as conn:
        runs = conn.execute(
            "SELECT status, row_count FROM meta.dataset_runs WHERE dataset = %s ORDER BY id",
            (spec.key,),
        ).fetchall()
        current = conn.execute(
            "SELECT current_version, is_seed FROM meta.datasets WHERE dataset = %s", (spec.key,)
        ).fetchone()
    assert [tuple(r) for r in runs] == [("loaded", 2), ("quarantined", 0)]
    assert current is not None and current[0] == first.dataset_version and current[1] is False


def test_reload_replaces_atomically(spec: DatasetSpec, good_csv: bytes) -> None:
    persister = PostgresPersister(DSN)
    MockLoader(spec, good_csv).run(persister)
    bigger = good_csv + b"2024-01-01,C,25,0.0,z\n"
    result = MockLoader(spec, bigger).run(persister)
    assert result.status is LoadStatus.LOADED and result.row_count == 3
    assert _count(spec.table_name) == 3
    with psycopg.connect(DSN) as conn:
        versions = {
            r[0] for r in conn.execute(f"SELECT DISTINCT dataset_version FROM {spec.table_name}")
        }
    assert versions == {result.dataset_version}
