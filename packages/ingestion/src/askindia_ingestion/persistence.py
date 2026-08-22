"""Writes validated frames to Postgres and keeps the ingestion audit trail.

A load replaces the table's contents in one transaction: DELETE, COPY, then the catalogue and
audit rows. Either every row of the new version lands or none does; the previous version stays
queryable until then. Raw snapshots on disk are the reproducibility record for older versions.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import psycopg
from psycopg import sql

from askindia_ingestion.contracts import DatasetSpec, LoadResult, LoadStatus


def ddl_for(spec: DatasetSpec) -> sql.Composed:
    schema, table = spec.table_name.split(".", 1)
    cols: list[sql.Composable] = [
        sql.SQL("{} {}{}").format(
            sql.Identifier(c.name), sql.SQL(c.pg_type), sql.SQL("" if c.nullable else " NOT NULL")
        )
        for c in spec.columns
    ]
    cols.append(sql.SQL("dataset_version text NOT NULL"))
    unique = sql.SQL(", ").join(sql.Identifier(k) for k in (*spec.unique_key, "dataset_version"))
    return sql.SQL(
        "CREATE TABLE IF NOT EXISTS {}.{} (id bigserial PRIMARY KEY, {}, UNIQUE ({}))"
    ).format(sql.Identifier(schema), sql.Identifier(table), sql.SQL(", ").join(cols), unique)


def _cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


def coverage_bounds(spec: DatasetSpec, frame: pd.DataFrame) -> tuple[str | None, str | None]:
    """Coverage dates for the catalogue: a static span, or min/max of the dataset's date column."""
    if spec.coverage_static:
        return spec.coverage_static[0].isoformat(), spec.coverage_static[1].isoformat()
    if not len(frame):
        return None, None
    candidates = (
        [spec.coverage_column]
        if spec.coverage_column
        else [
            c.name
            for c in spec.columns
            if c.pg_type == "date" or c.name in ("period", "year", "crop_year")
        ]
    )
    for col in candidates:
        if col not in frame.columns:
            continue
        series = frame[col].dropna()
        if series.empty:
            continue
        lo, hi = series.min(), series.max()
        if col == "year":
            return f"{int(lo)}-01-01", f"{int(hi)}-12-31"
        if col == "crop_year":  # '2021-22' is July 2021 to June 2022
            return f"{int(str(lo)[:4])}-07-01", f"{int(str(hi)[:4]) + 1}-06-30"
        return str(lo)[:10], str(hi)[:10]
    return None, None


class PostgresPersister:
    """Callable matching :data:`askindia_ingestion.contracts.Persister`, plus audit helpers."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def __call__(
        self, spec: DatasetSpec, frame: pd.DataFrame, version: str, result: LoadResult
    ) -> int:
        schema, table = spec.table_name.split(".", 1)
        columns = [*spec.column_names, "dataset_version"]
        with (
            psycopg.connect(self.dsn, application_name="askindia-ingest") as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            cur.execute(ddl_for(spec))
            cur.execute(
                sql.SQL("DELETE FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
            )
            copy_stmt = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.SQL(", ").join(sql.Identifier(c) for c in columns),
            )
            written = 0
            with cur.copy(copy_stmt) as copy:
                for row in frame.itertuples(index=False, name=None):
                    copy.write_row([*(_cell(v) for v in row), version])
                    written += 1
            self._upsert_catalogue(cur, spec, frame, version)
            self._insert_run(cur, result, version=version, row_count=written)
        return written

    def record(self, result: LoadResult) -> None:
        """Audit a run that did not reach the persister (quarantined or failed)."""
        if result.status is LoadStatus.LOADED:
            return
        with (
            psycopg.connect(self.dsn, application_name="askindia-ingest") as conn,
            conn.cursor() as cur,
        ):
            self._insert_run(cur, result, version=result.dataset_version, row_count=0)

    @staticmethod
    def _insert_run(
        cur: psycopg.Cursor[Any], result: LoadResult, *, version: str, row_count: int
    ) -> None:
        cur.execute(
            """
            INSERT INTO meta.dataset_runs
                (dataset, dataset_version, source_url, fetched_at, raw_sha256, row_count, status,
                 error, validation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result.dataset,
                version,
                result.source_url,
                result.fetched_at or datetime.now(UTC),
                result.raw_sha256,
                row_count,
                result.status.value,
                result.error,
                json.dumps(result.validation.to_dict()) if result.validation else None,
            ),
        )

    @staticmethod
    def _upsert_catalogue(
        cur: psycopg.Cursor[Any], spec: DatasetSpec, frame: pd.DataFrame, version: str
    ) -> None:
        coverage_from, coverage_to = coverage_bounds(spec, frame)
        cur.execute(
            """
            INSERT INTO meta.datasets
                (dataset, table_name, title, source_org, source_url, cadence,
                 coverage_from, coverage_to, current_version, is_seed, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, false, now())
            ON CONFLICT (dataset) DO UPDATE SET
                table_name = EXCLUDED.table_name, title = EXCLUDED.title,
                source_org = EXCLUDED.source_org, source_url = EXCLUDED.source_url,
                cadence = EXCLUDED.cadence, coverage_from = EXCLUDED.coverage_from,
                coverage_to = EXCLUDED.coverage_to, current_version = EXCLUDED.current_version,
                is_seed = false, updated_at = now()
            """,
            (
                spec.key,
                spec.table_name,
                spec.title,
                spec.source_org,
                spec.landing_url or spec.source_url,
                spec.cadence.value,
                coverage_from,
                coverage_to,
                version,
            ),
        )
