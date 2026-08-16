"""Loader for sources that publish a single CSV (or one Excel sheet) with a header row."""

from __future__ import annotations

import io
from collections.abc import Callable, Mapping
from pathlib import Path

import pandas as pd

from askindia_ingestion.contracts import BaseLoader, DatasetSpec, RawArtifact, SourceFormat
from askindia_ingestion.loaders.http import fetch

Transform = Callable[[pd.DataFrame], pd.DataFrame]


class CSVLoader(BaseLoader):
    """Fetch one tabular file, rename source columns to the spec's names, apply a transform."""

    def __init__(
        self,
        spec: DatasetSpec,
        *,
        rename: Mapping[str, str] | None = None,
        transform: Transform | None = None,
        sheet: str | int = 0,
        skiprows: int = 0,
        encoding: str = "utf-8",
        snapshot_dir: Path | None = None,
    ) -> None:
        super().__init__(spec, snapshot_dir=snapshot_dir)
        self.rename = dict(rename or {})
        self.transform = transform
        self.sheet = sheet
        self.skiprows = skiprows
        self.encoding = encoding

    def fetch_raw(self) -> RawArtifact:
        return fetch(self.spec.key, self.spec.source_url, verify_tls=self.spec.verify_tls)

    def parse(self, raw: RawArtifact) -> pd.DataFrame:
        buf = io.BytesIO(raw.content)
        if self.spec.fmt is SourceFormat.CSV:
            frame = pd.read_csv(
                buf, skiprows=self.skiprows, encoding=self.encoding, encoding_errors="replace"
            )
        elif self.spec.fmt in (SourceFormat.XLSX, SourceFormat.XLS):
            frame = pd.read_excel(buf, sheet_name=self.sheet, skiprows=self.skiprows)
        else:
            raise ValueError(f"CSVLoader cannot parse {self.spec.fmt}")
        frame.columns = [str(c).strip() for c in frame.columns]
        if self.rename:
            frame = frame.rename(columns=self.rename)
        if self.transform is not None:
            frame = self.transform(frame)
        return frame
