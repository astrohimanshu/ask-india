"""IMD monthly rainfall by meteorological subdivision, 1901 to date, with 1971-2020 normals.

Source: IMD Pune, Climate Research & Services — one static HTML table per subdivision under
https://www.imdpune.gov.in/cmpg/subdivrainfall/. The index page lists the 36 subdivisions.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from askindia_ingestion.contracts import (
    BaseLoader,
    Cadence,
    ColumnSpec,
    DatasetSpec,
    RawArtifact,
    SourceFormat,
)
from askindia_ingestion.loaders.bundle import bundle, unbundle
from askindia_ingestion.loaders.http import fetch

BASE_URL = "https://www.imdpune.gov.in/cmpg/subdivrainfall/"
INDEX_URL = BASE_URL + "subdivisonrainfall.html"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
log = logging.getLogger(__name__)
_OPTION = re.compile(r'<option\s+value=\s*"([^"]+\.html)"[^>]*>\s*([^<]+?)\s*<', re.IGNORECASE)

SPEC = DatasetSpec(
    key="imd_subdivision_rainfall",
    title="IMD monthly rainfall by meteorological subdivision (1901 onwards)",
    source_org="India Meteorological Department, Pune (Climate Research & Services)",
    source_url=INDEX_URL,
    landing_url="https://www.imdpune.gov.in/cmpg/subdivrainfall/subdivisonrainfall.html",
    fmt=SourceFormat.ZIP,
    cadence=Cadence.MONTHLY,
    table_name="data.imd_subdivision_rainfall",
    columns=(
        ColumnSpec(
            name="subdivision",
            pg_type="text",
            description="IMD meteorological subdivision name as published (36 subdivisions)",
        ),
        ColumnSpec(name="year", pg_type="integer", description="Calendar year", min=1901, max=2100),
        ColumnSpec(
            name="month",
            pg_type="text",
            description="Calendar month abbreviation, or 'Annual' for the January-December total",
            allowed=(*MONTHS, "Annual"),
        ),
        ColumnSpec(
            name="rainfall_mm",
            pg_type="numeric(8,1)",
            description="Actual area-weighted rainfall for the subdivision in that month or year",
            unit="mm",
            min=0,
            max=20000,
            nullable=True,
        ),
        ColumnSpec(
            name="normal_mm",
            pg_type="numeric(8,1)",
            description="Long-period average (1971-2020 normal) for the same month or year",
            unit="mm",
            min=0,
            max=20000,
            nullable=True,
        ),
    ),
    unique_key=("subdivision", "year", "month"),
    min_rows=45000,
    caveats=(
        "Subdivisions are IMD meteorological units, not states: several states are split "
        "(e.g. East/West Uttar Pradesh) or grouped (e.g. Assam and Meghalaya).",
        "Values are area-weighted averages in millimetres; 'Annual' is the January-December total.",
        "normal_mm is the 1971-2020 long-period average published alongside the series.",
        "The most recent year may be provisional and incomplete for months not yet published.",
        "Where a page lists the same year twice with different values (Odisha 2023 at the time "
        "of writing) neither row is loaded, because the source does not say which is correct.",
    ),
    difficulty="low",
)


def parse_index(html: str) -> list[tuple[str, str]]:
    """(slug, subdivision name) pairs from the selector page, in page order, deduplicated."""
    seen: dict[str, str] = {}
    for slug, name in _OPTION.findall(html):
        seen.setdefault(slug.strip(), re.sub(r"\s+", " ", name).strip())
    return list(seen.items())


def parse_subdivision_table(html: bytes, subdivision: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if table is None:
        raise ValueError(f"no <table> on page for {subdivision}")
    rows = [
        [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        for tr in table.find_all("tr")
    ]
    header = [h.strip() for h in rows[0]]
    if header[2:] != [*MONTHS, "Annual"]:
        raise ValueError(f"unexpected header for {subdivision}: {header}")
    normals: dict[str, float | None] = dict.fromkeys((*MONTHS, "Annual"))
    records: list[dict[str, object]] = []
    for row in rows[1:]:
        if len(row) < 15:
            continue
        label, kind, values = row[0].strip(), row[1].strip().upper(), row[2:15]
        parsed = [_num(v) for v in values]
        if kind == "NORM":
            normals = dict(zip((*MONTHS, "Annual"), parsed, strict=True))
            continue
        if kind != "ACTL" or not label.isdigit():
            continue
        year = int(label)
        for month, value in zip((*MONTHS, "Annual"), parsed, strict=True):
            records.append(
                {
                    "subdivision": subdivision,
                    "year": year,
                    "month": month,
                    "rainfall_mm": value,
                    "normal_mm": normals.get(month),
                }
            )
    if not records:
        raise ValueError(f"no ACTL rows parsed for {subdivision}")
    frame = pd.DataFrame.from_records(records)
    ambiguous = frame.duplicated(["year", "month"], keep=False)
    if ambiguous.any():
        years = sorted(frame.loc[ambiguous, "year"].unique().tolist())
        log.warning("%s: year(s) %s published more than once; dropping them", subdivision, years)
        frame = frame.loc[~ambiguous]
    return frame.reset_index(drop=True)


def _num(text: str) -> float | None:
    text = text.strip().replace(",", "")
    if text in {"", "-", "--", "NA", "N/A"}:
        return None
    return float(text)


class RainfallLoader(BaseLoader):
    def fetch_raw(self) -> RawArtifact:
        index = fetch(self.spec.key, INDEX_URL, verify_tls=self.spec.verify_tls)
        pairs = parse_index(index.content.decode("utf-8", errors="replace"))
        if len(pairs) < 30:
            raise ValueError(f"index page lists only {len(pairs)} subdivisions; expected 36")
        files: list[tuple[str, bytes]] = [("index.html", index.content)]
        for slug, name in pairs:
            page = fetch(self.spec.key, BASE_URL + slug, verify_tls=self.spec.verify_tls)
            files.append((f"{slug}|{name}", page.content))
        return bundle(self.spec.key, INDEX_URL, files)

    def parse(self, raw: RawArtifact) -> pd.DataFrame:
        frames = []
        for name, content in unbundle(raw).items():
            if "|" not in name:
                continue
            _, subdivision = name.split("|", 1)
            frames.append(parse_subdivision_table(content, subdivision))
        if not frames:
            raise ValueError("bundle contains no subdivision pages")
        return pd.concat(frames, ignore_index=True)


def build(snapshot_dir: Path | None = None) -> BaseLoader:
    return RainfallLoader(SPEC, snapshot_dir=snapshot_dir)
