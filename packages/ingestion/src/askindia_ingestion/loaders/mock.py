"""Offline loaders for tests: serve bytes from memory or a fixture file, no network."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from askindia_ingestion.contracts import BaseLoader, DatasetSpec, RawArtifact, SourceFormat


class MockLoader(BaseLoader):
    """Returns the given bytes from fetch_raw and parses them as CSV/JSON records."""

    def __init__(
        self, spec: DatasetSpec, content: bytes, *, snapshot_dir: Path | None = None
    ) -> None:
        super().__init__(spec, snapshot_dir=snapshot_dir)
        self.content = content

    def fetch_raw(self) -> RawArtifact:
        return RawArtifact.from_bytes(self.spec.key, self.spec.source_url, self.content, "text/csv")

    def parse(self, raw: RawArtifact) -> pd.DataFrame:
        if self.spec.fmt is SourceFormat.JSON:
            return pd.read_json(io.BytesIO(raw.content))
        return pd.read_csv(io.BytesIO(raw.content))


class FixtureLoader(MockLoader):
    """MockLoader whose bytes come from a file on disk."""

    def __init__(self, spec: DatasetSpec, path: Path, *, snapshot_dir: Path | None = None) -> None:
        super().__init__(spec, path.read_bytes(), snapshot_dir=snapshot_dir)


class ExplodingLoader(BaseLoader):
    """Raises at the requested step; used to prove failures become recorded results."""

    def __init__(self, spec: DatasetSpec, *, fail_at: str) -> None:
        super().__init__(spec)
        self.fail_at = fail_at

    def fetch_raw(self) -> RawArtifact:
        if self.fail_at == "fetch":
            raise ConnectionError("simulated network failure")
        return RawArtifact.from_bytes(self.spec.key, self.spec.source_url, b"a,b\n1,2\n")

    def parse(self, raw: RawArtifact) -> pd.DataFrame:
        if self.fail_at == "parse":
            raise ValueError("simulated format change")
        return pd.read_csv(io.BytesIO(raw.content))
