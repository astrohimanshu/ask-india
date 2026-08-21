"""DGCA monthly traffic and operating statistics of Indian carriers, per airline, 2019 onwards.

Source: DGCA (Air Transport Statistics), one XLSX per carrier per calendar year on DGCA's public
S3 store. The single sheet stacks up to four blocks with identical headers, one per service type
(scheduled/non-scheduled x domestic/international); each block holds JAN..DEC rows and a TOTAL.
Carrier file names vary by year, so the file list is discovered live from the portal's JSON
listing endpoint and mapped onto the S3 host.
"""

from __future__ import annotations

import html
import io
import json
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import openpyxl
import pandas as pd

from askindia_ingestion.contracts import (
    BaseLoader,
    Cadence,
    ColumnSpec,
    DatasetSpec,
    RawArtifact,
    SourceFormat,
)
from askindia_ingestion.loaders.bundle import bundle, unbundle
from askindia_ingestion.loaders.http import USER_AGENT, fetch

LISTING_URL = "https://www.dgca.gov.in/digigov-portal/scan?"
LISTING_FORM = {
    "baseLocale": "",
    "screenId": "10000001",
    "classification": "",
    "actionVal": "viewStaticData",
    "requestType": "ApplicationRH",
    "attachId": "",
    "langType": "2",
    "ruleBookId": "259",
    "contentId": "4751",
    "serviceName": "",
    "attr": "",
}
S3_BASE = "https://public-prd-dgca.s3.ap-south-1.amazonaws.com/"
PORTAL_PREFIX = "jsp/dgca/"
MONTHLY_DIR = "InventoryList/dataReports/aviationDataStatistics/airTransport/domestic/monthly/"
FIRST_YEAR = 2019
# Listed files that S3 refuses (403) are recorded in the bundle manifest and skipped; more than
# this many missing means the source itself has changed and the run must fail.
MAX_UNAVAILABLE = 10
# The listing POST answers with a stub roughly every other call (see listing_is_complete).
LISTING_ATTEMPTS = 8
ALL_AIRLINES = "All Airlines"

SEGMENTS = (
    "scheduled_domestic",
    "scheduled_international",
    "non_scheduled_domestic",
    "non_scheduled_international",
)
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
INTEGER_COLUMNS = ("departures", "passengers_carried")
# Same carrier, different spelling in different years' workbooks (after title-casing).
AIRLINE_ALIASES = {"Fly91": "Fly 91", "Indiaone Air": "India One Air"}

_TITLE = re.compile(r"traffic\s+and\s+operating\s+statistics", re.IGNORECASE)
_TITLE_YEAR = re.compile(r"\b(20\d{2})\b")
_TITLE_AIRLINE = re.compile(r"\)\s*-\s*([A-Za-z0-9 .&']+?)\s*$")
_LISTING_YEAR = re.compile(r"\b(20\d{2})\b")
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_DATA_URL = re.compile(r'data-url="([^"]+)"')
_TAG = re.compile(r"<[^>]+>")

SPEC = DatasetSpec(
    key="dgca_airline_traffic",
    title="DGCA monthly traffic and operating statistics by airline (2019 onwards)",
    source_org="Directorate General of Civil Aviation (DGCA), Ministry of Civil Aviation",
    source_url=LISTING_URL,
    landing_url="https://www.dgca.gov.in/digigov-portal/?page=4751/4751/monthlyStatistics",
    fmt=SourceFormat.ZIP,
    cadence=Cadence.MONTHLY,
    table_name="data.dgca_airline_traffic",
    columns=(
        ColumnSpec(
            name="period",
            pg_type="date",
            description="Calendar month, stored as the first day of the month",
        ),
        ColumnSpec(
            name="airline",
            pg_type="text",
            description=(
                "Carrier name as published by DGCA, title-cased (e.g. 'Indigo', 'Air India', "
                "'Akasa Air'); 'All Airlines' is DGCA's own all-carrier total"
            ),
        ),
        ColumnSpec(
            name="segment",
            pg_type="text",
            description=(
                "Service type block the row comes from: scheduled or non-scheduled services, "
                "domestic or international"
            ),
            allowed=SEGMENTS,
        ),
        ColumnSpec(
            name="departures",
            pg_type="integer",
            description=(
                "Aircraft departures flown in the month; rarely blank when a carrier filed "
                "passengers only"
            ),
            unit="departures",
            min=0,
            max=500_000,
            nullable=True,
        ),
        ColumnSpec(
            name="hours_flown",
            pg_type="numeric(12,2)",
            description="Aircraft hours flown in the month",
            unit="hours",
            min=0,
            max=5_000_000,
            nullable=True,
        ),
        ColumnSpec(
            name="km_flown_thousand",
            pg_type="numeric(14,2)",
            description="Aircraft kilometres flown in the month",
            unit="thousand km",
            min=0,
            max=5_000_000,
            nullable=True,
        ),
        ColumnSpec(
            name="passengers_carried",
            pg_type="bigint",
            description=(
                "Revenue passengers carried in the month; blank for all-cargo carriers "
                "(Bluedart, Quikjet Cargo)"
            ),
            unit="passengers",
            min=0,
            max=100_000_000,
            nullable=True,
        ),
        ColumnSpec(
            name="passenger_km_thousand",
            pg_type="numeric(16,2)",
            description="Revenue passenger-kilometres performed in the month (RPK)",
            unit="thousand passenger-km",
            min=0,
            max=1_000_000_000,
            nullable=True,
        ),
        ColumnSpec(
            name="available_seat_km_thousand",
            pg_type="numeric(16,2)",
            description="Available seat-kilometres offered in the month (ASK)",
            unit="thousand seat-km",
            min=0,
            max=1_000_000_000,
            nullable=True,
        ),
        ColumnSpec(
            name="passenger_load_factor_pct",
            pg_type="numeric(6,2)",
            description="Passenger load factor = RPK / ASK x 100, as published by DGCA",
            unit="%",
            min=0,
            max=100,
            nullable=True,
        ),
    ),
    unique_key=("period", "airline", "segment"),
    # 130 carrier-year files for 2019-2026 parsed to 2,770 rows on 2026-08-26; 80% floor.
    min_rows=2200,
    caveats=(
        "All figures are marked Provisional by DGCA and are compiled from ICAO ATR Form A "
        "returns furnished by each carrier; DGCA's monthly PDF traffic reports for the same "
        "airline-month can differ slightly from these workbooks.",
        "Rows are per service-type block (segment). Domestic scheduled traffic of an airline is "
        "the 'scheduled_domestic' segment; do not sum segments unless the question asks for "
        "all services.",
        "'All Airlines' rows are DGCA's own totals (the totaldom/totalint files), not a sum "
        "computed here; never add them to individual carriers.",
        "Carrier files that DGCA lists but S3 refuses (HTTP 403) are skipped and recorded in "
        "the bundle manifest (as of 2026-08: Go Air 2025-26, Vistara 2025-26, TruJet 2024-26). "
        "Vistara merged into Air India in November 2024; Go First stopped flying in May 2023.",
        "Months with no data in a block are omitted, so a missing (period, airline, segment) "
        "row means no figures were published, not zero traffic. Months published as zero "
        "(e.g. the April-May 2020 domestic suspension) are kept as zero rows.",
        "Airline spelling is normalised only where the same carrier is spelt differently "
        "across years (Fly91 -> Fly 91, Indiaone Air -> India One Air); listing-only names "
        "('Alliance', 'Tru Jet') are used only when the workbook itself carries no name.",
        "The current year's file is partial and refreshed monthly; the load factor is the "
        "published figure rounded to two decimals.",
    ),
    difficulty="medium",
)


@dataclass(frozen=True)
class DiscoveredFile:
    year: int
    name: str  # carrier name as shown in the portal listing
    path: str  # portal-relative path, e.g. 'jsp/dgca/InventoryList/.../indigo25.xlsx'

    @property
    def filename(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def url(self) -> str:
        return S3_BASE + quote(self.path.removeprefix(PORTAL_PREFIX))

    @property
    def is_total(self) -> bool:
        return self.name.lower().startswith("total")

    @property
    def bundle_name(self) -> str:
        return f"{self.year}|{self.name}|{self.filename}"


def parse_listing(payload: bytes, *, first_year: int = FIRST_YEAR) -> list[DiscoveredFile]:
    """Carrier XLSX files from the portal's JSON listing, one table per year, in listing order."""
    data = json.loads(payload)
    found: list[DiscoveredFile] = []
    seen: set[str] = set()
    for item in data.get("ruleBookContentDtlsList", []):
        text = str(item.get("contentText", ""))
        if MONTHLY_DIR not in text:
            continue
        year_match = _LISTING_YEAR.search(str(item.get("contentIdentifier", "")))
        if year_match is None:
            continue
        year = int(year_match.group(1))
        if year < first_year:
            continue
        for row in _ROW.findall(text):
            cells = _CELL.findall(row)
            if len(cells) < 2:
                continue
            name = html.unescape(_TAG.sub("", cells[1])).replace("\xa0", " ")
            name = re.sub(r"\s+", " ", name).strip()
            for path in _DATA_URL.findall(row):
                path = html.unescape(path)
                if not path.lower().endswith(".xlsx") or "CITYPAIR" in path.upper():
                    continue
                if path in seen:
                    continue
                seen.add(path)
                found.append(DiscoveredFile(year=year, name=name, path=path))
    if not found:
        raise ValueError("portal listing contains no carrier XLSX files; format changed?")
    return found


def _segment_from_title(title: str) -> str:
    flat = re.sub(r"[^a-z]", "", title.lower())
    if "international" in flat:
        scope = "international"
    elif "domestic" in flat:
        scope = "domestic"
    else:
        raise ValueError(f"cannot tell domestic from international in block title {title!r}")
    kind = "non_scheduled" if "nonscheduled" in flat else "scheduled"
    return f"{kind}_{scope}"


def _find_title(row: list[Any]) -> tuple[int, str] | None:
    for idx, value in enumerate(row):
        if isinstance(value, str) and _TITLE.search(value):
            return idx, value
    return None


def _block_year(row: list[Any], title: str) -> int | None:
    first = row[0]
    if isinstance(first, int | float) and not isinstance(first, bool):
        return int(first)
    if isinstance(first, str) and first.strip().isdigit():
        return int(first.strip())
    match = _TITLE_YEAR.search(title)
    return int(match.group(1)) if match else None


def _block_airline(row: list[Any], title_idx: int, title: str, fallback: str) -> str:
    raw: str | None = None
    for value in row[title_idx + 1 :]:
        if isinstance(value, str) and value.strip():
            raw = value
            break
    if raw is None:
        match = _TITLE_AIRLINE.search(title)
        raw = match.group(1) if match else fallback
    name = re.sub(r"\s+", " ", raw).strip().title()
    return AIRLINE_ALIASES.get(name, name)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().upper() if value is not None else ""


def _check_header(top: list[Any], sub: list[Any], where: str) -> None:
    """Column meanings are fixed by position; the header must say so or the layout has moved.

    Column 0 is deliberately not checked: one published file has the year typed over 'MONTH',
    and the twelve JAN..DEC labels that follow already pin the row layout.
    """
    expected_top = {
        4: "PASSENGERS CARRIED",
        5: "PASSENGER KMS",
        6: "AVAILABLE SEAT",
        7: "LOAD FACTOR",
    }
    expected_sub = {1: "DEPARTURES", 2: "HOURS", 3: "KILOMETRE"}
    for idx, needle in expected_top.items():
        if needle not in _text(top[idx] if idx < len(top) else None):
            raise ValueError(f"{where}: header column {idx} is not {needle!r}: {top[:8]!r}")
    for idx, needle in expected_sub.items():
        if needle not in _text(sub[idx] if idx < len(sub) else None):
            raise ValueError(f"{where}: sub-header column {idx} is not {needle!r}: {sub[:4]!r}")


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "NA", "N/A", "NIL"}:
        return None
    return float(text)


def _int(value: float | None, where: str) -> int | None:
    if value is None:
        return None
    if abs(value - round(value)) > 1e-6:
        raise ValueError(f"{where}: expected an integer count, got {value!r}")
    return round(value)


def parse_workbook(content: bytes, *, year: int, listing_name: str) -> list[dict[str, object]]:
    """Every published month row of every service-type block in one carrier-year workbook."""
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    sheet = workbook.worksheets[0]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]
    fallback_name = ALL_AIRLINES if listing_name.lower().startswith("total") else listing_name
    records: list[dict[str, object]] = []
    segments_seen: list[str] = []
    i = 0
    while i < len(rows):
        found = _find_title(rows[i])
        if found is None:
            i += 1
            continue
        title_idx, title = found
        where = f"{listing_name} {year} row {i + 1}"
        segment = _segment_from_title(title)
        if segment in segments_seen:
            raise ValueError(f"{where}: duplicate {segment} block")
        segments_seen.append(segment)
        block_year = _block_year(rows[i], title)
        if block_year is not None and block_year != year:
            raise ValueError(f"{where}: workbook says {block_year}, listing says {year}")
        airline = _block_airline(rows[i], title_idx, title, fallback_name)
        if i + 15 >= len(rows):
            raise ValueError(f"{where}: block truncated")
        _check_header(rows[i + 1], rows[i + 2], where)
        for offset, month in enumerate(MONTHS, start=3):
            row = rows[i + offset]
            label = _text(row[0])
            if label[:3] != month:
                raise ValueError(f"{where}: expected {month} at row {i + offset + 1}: {label!r}")
            values = [_num(v) for v in row[1:8]]
            if all(v is None for v in values):
                continue
            dep, hours, km, pax, rpk, ask, plf = values
            records.append(
                {
                    "period": date(year, offset - 2, 1),
                    "airline": airline,
                    "segment": segment,
                    "departures": _int(dep, where),
                    "hours_flown": None if hours is None else round(hours, 2),
                    "km_flown_thousand": None if km is None else round(km, 2),
                    "passengers_carried": _int(pax, where),
                    "passenger_km_thousand": None if rpk is None else round(rpk, 2),
                    "available_seat_km_thousand": None if ask is None else round(ask, 2),
                    "passenger_load_factor_pct": None if plf is None else round(plf, 2),
                }
            )
        if _text(rows[i + 15][0]) != "TOTAL":
            raise ValueError(f"{where}: expected TOTAL after DEC, got {rows[i + 15][0]!r}")
        i += 16
    if not segments_seen:
        raise ValueError(f"{listing_name} {year}: no statistics blocks found in the workbook")
    return records


def listing_is_complete(payload: bytes) -> bool:
    """The portal is load-balanced and about half the time answers with a stub holding only the
    requested content item (no ``ruleBookContentDtlsList``) instead of the full year-wise
    listing. Identical requests get either answer, so completeness is checked, not headers."""
    try:
        data = json.loads(payload)
    except ValueError:
        return False
    tables = data.get("ruleBookContentDtlsList") if isinstance(data, dict) else None
    return isinstance(tables, list) and len(tables) > 1


def fetch_listing(
    *, verify_tls: bool = True, timeout: float = 120.0, attempts: int = LISTING_ATTEMPTS
) -> bytes:
    stubs = 0
    for _ in range(attempts):
        # A new client per attempt: on a kept-alive connection every retry lands on the same
        # backend and gets the same stub, so the retry must be a fresh connection.
        with httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, verify=verify_tls
        ) as client:
            response = client.post(LISTING_URL, data=LISTING_FORM)
            response.raise_for_status()
        if listing_is_complete(response.content):
            return response.content
        stubs += 1
        time.sleep(1.0)
    raise ValueError(
        f"DGCA portal returned the single-content stub instead of the listing {stubs} times "
        f"in a row; listing endpoint or its backend has changed"
    )


def _manifest_entry(item: DiscoveredFile) -> dict[str, object]:
    return {
        "year": item.year,
        "name": item.name,
        "filename": item.filename,
        "path": item.path,
        "url": item.url,
    }


class DgcaLoader(BaseLoader):
    def fetch_raw(self) -> RawArtifact:
        listing = fetch_listing(verify_tls=self.spec.verify_tls)
        discovered = parse_listing(listing)
        files: list[tuple[str, bytes]] = [("listing.json", listing)]
        manifest: list[dict[str, object]] = []
        unavailable: list[str] = []
        years_fetched: set[int] = set()
        for item in discovered:
            try:
                page = fetch(self.spec.key, item.url, verify_tls=self.spec.verify_tls)
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status not in (403, 404):
                    raise
                unavailable.append(f"{item.filename} ({status})")
                manifest.append({**_manifest_entry(item), "status": status})
                continue
            files.append((item.bundle_name, page.content))
            years_fetched.add(item.year)
            manifest.append({**_manifest_entry(item), "status": 200, "sha256": page.sha256})
        if len(unavailable) > MAX_UNAVAILABLE:
            raise ValueError(f"{len(unavailable)} listed files unavailable: {unavailable}")
        years_listed = {item.year for item in discovered}
        if missing_years := years_listed - years_fetched:
            raise ValueError(f"no carrier file could be fetched for {sorted(missing_years)}")
        files.append(("manifest.json", json.dumps(manifest, indent=1).encode()))
        return bundle(self.spec.key, LISTING_URL, files)

    def parse(self, raw: RawArtifact) -> pd.DataFrame:
        records: list[dict[str, object]] = []
        n_files = 0
        for name, content in unbundle(raw).items():
            parts = name.split("|", 2)
            if len(parts) != 3 or not parts[0].isdigit():
                continue
            n_files += 1
            records.extend(parse_workbook(content, year=int(parts[0]), listing_name=parts[1]))
        if n_files == 0:
            raise ValueError("bundle contains no carrier workbooks")
        frame = pd.DataFrame.from_records(records)
        # Keep integer columns as Python int / None (object dtype): a None in a numeric column
        # would otherwise turn the whole column into float64, which COPY rejects for integer.
        for col in INTEGER_COLUMNS:
            frame[col] = pd.Series([r[col] for r in records], dtype=object)
        return frame


def build(snapshot_dir: Path | None = None) -> BaseLoader:
    return DgcaLoader(SPEC, snapshot_dir=snapshot_dir)
