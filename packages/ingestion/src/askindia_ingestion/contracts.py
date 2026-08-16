"""Ingestion contracts.

Every dataset is described by a :class:`DatasetSpec` and brought in by a :class:`BaseLoader`
that walks four explicit steps — fetch_raw, parse, validate, load — so each step can be tested
and each failure is attributable. A loader never writes partial data: validation failure
quarantines the whole batch and raises.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from askindia_ingestion.validation import ValidationFailedError, ValidationReport, validate_frame


class Cadence(StrEnum):
    MONTHLY = "monthly"
    ANNUAL = "annual"
    STATIC = "static"


class SourceFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    XLS = "xls"
    PDF = "pdf"
    HTML = "html"
    JSON = "json"
    ZIP = "zip"  # several fetched files bundled into one artifact


class ColumnSpec(BaseModel):
    """One output column: its Postgres type, semantics and the checks it must satisfy."""

    model_config = ConfigDict(frozen=True)

    name: str
    pg_type: str = Field(description="Postgres column type, e.g. text, bigint, numeric(6,2), date")
    description: str
    unit: str | None = None
    nullable: bool = False
    min: float | None = None
    max: float | None = None
    allowed: tuple[str, ...] | None = None


class DatasetSpec(BaseModel):
    """Static description of a dataset: source, shape, and the checks it must satisfy."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    title: str
    source_org: str
    source_url: str
    landing_url: str | None = None
    fmt: SourceFormat
    cadence: Cadence
    table_name: str = Field(pattern=r"^data\.[a-z][a-z0-9_]+$")
    columns: tuple[ColumnSpec, ...]
    unique_key: tuple[str, ...]
    min_rows: int = 1
    caveats: tuple[str, ...] = ()
    difficulty: str = Field(default="unknown", pattern=r"^(low|medium|high|unknown)$")
    verify_tls: bool = Field(
        default=True, description="False only for hosts with a broken certificate chain"
    )

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class RawArtifact:
    """Bytes exactly as fetched, plus enough provenance to reproduce the fetch."""

    dataset: str
    url: str
    content: bytes
    content_type: str | None
    fetched_at: datetime
    sha256: str
    path: Path | None = None

    @classmethod
    def from_bytes(
        cls, dataset: str, url: str, content: bytes, content_type: str | None = None
    ) -> RawArtifact:
        return cls(
            dataset=dataset,
            url=url,
            content=content,
            content_type=content_type,
            fetched_at=datetime.now(UTC),
            sha256=hashlib.sha256(content).hexdigest(),
        )


class LoadStatus(StrEnum):
    LOADED = "loaded"
    QUARANTINED = "quarantined"
    FAILED = "failed"


@dataclass(frozen=True)
class LoadResult:
    dataset: str
    dataset_version: str
    status: LoadStatus
    row_count: int
    raw_sha256: str | None
    source_url: str
    fetched_at: datetime | None
    validation: ValidationReport | None
    error: str | None = None
    snapshot_path: Path | None = None


# Persistence is injected so loaders are testable without a database. It receives the validated
# frame and must either commit every row stamped with dataset_version or raise.
Persister = Callable[[DatasetSpec, pd.DataFrame, str, LoadResult], int]


def version_stamp(spec: DatasetSpec, raw: RawArtifact) -> str:
    """Version = fetch date + short content hash: two fetches of identical bytes share a version."""
    return f"{raw.fetched_at:%Y-%m-%d}-{raw.sha256[:8]}"


class BaseLoader(ABC):
    """Fetch → snapshot → parse → validate → load, failing loud at every step."""

    def __init__(self, spec: DatasetSpec, *, snapshot_dir: Path | None = None) -> None:
        self.spec = spec
        self.snapshot_dir = snapshot_dir

    @abstractmethod
    def fetch_raw(self) -> RawArtifact: ...

    @abstractmethod
    def parse(self, raw: RawArtifact) -> pd.DataFrame: ...

    def validate(self, frame: pd.DataFrame) -> ValidationReport:
        return validate_frame(frame, self.spec)

    def snapshot(self, raw: RawArtifact) -> Path | None:
        if self.snapshot_dir is None:
            return None
        ext = self.spec.fmt.value
        target = (
            self.snapshot_dir / self.spec.key / f"{raw.fetched_at:%Y-%m-%d}_{raw.sha256[:12]}.{ext}"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(raw.content)
        return target

    def run(self, persist: Persister | None = None) -> LoadResult:
        """Execute the pipeline. Returns a LoadResult in every case; never raises on bad data."""
        raw: RawArtifact | None = None
        snapshot_path: Path | None = None
        try:
            raw = self.fetch_raw()
            snapshot_path = self.snapshot(raw)
            frame = self.parse(raw)
            frame = _coerce_columns(frame, self.spec)
            report = self.validate(frame)
        except ValidationFailedError as e:
            return LoadResult(
                dataset=self.spec.key,
                dataset_version=version_stamp(self.spec, raw) if raw else "unversioned",
                status=LoadStatus.QUARANTINED,
                row_count=0,
                raw_sha256=raw.sha256 if raw else None,
                source_url=self.spec.source_url,
                fetched_at=raw.fetched_at if raw else None,
                validation=e.report,
                error=str(e),
                snapshot_path=snapshot_path,
            )
        except Exception as e:
            return LoadResult(
                dataset=self.spec.key,
                dataset_version=version_stamp(self.spec, raw) if raw else "unversioned",
                status=LoadStatus.FAILED,
                row_count=0,
                raw_sha256=raw.sha256 if raw else None,
                source_url=self.spec.source_url,
                fetched_at=raw.fetched_at if raw else None,
                validation=None,
                error=f"{type(e).__name__}: {e}",
                snapshot_path=snapshot_path,
            )

        version = version_stamp(self.spec, raw)
        result = LoadResult(
            dataset=self.spec.key,
            dataset_version=version,
            status=LoadStatus.LOADED,
            row_count=len(frame),
            raw_sha256=raw.sha256,
            source_url=self.spec.source_url,
            fetched_at=raw.fetched_at,
            validation=report,
            snapshot_path=snapshot_path,
        )
        if persist is None:
            return result
        try:
            written = persist(self.spec, frame, version, result)
        except Exception as e:
            return LoadResult(
                **{
                    **result.__dict__,
                    "status": LoadStatus.FAILED,
                    "row_count": 0,
                    "error": f"persist: {type(e).__name__}: {e}",
                }
            )
        return LoadResult(**{**result.__dict__, "row_count": written})


def _coerce_columns(frame: pd.DataFrame, spec: DatasetSpec) -> pd.DataFrame:
    """Keep only declared columns, in declared order; missing ones are left for validation."""
    present = [c for c in spec.column_names if c in frame.columns]
    return frame.loc[:, present].reset_index(drop=True)


def frame_from_records(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame.from_records(list(records))


__all__ = [
    "BaseLoader",
    "Cadence",
    "ColumnSpec",
    "DatasetSpec",
    "LoadResult",
    "LoadStatus",
    "Persister",
    "RawArtifact",
    "SourceFormat",
    "ValidationFailedError",
    "ValidationReport",
    "field",
    "frame_from_records",
    "version_stamp",
]
