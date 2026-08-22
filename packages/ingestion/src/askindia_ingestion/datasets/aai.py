"""AAI monthly airport-wise passenger traffic: Annexure-III of the AAI "Traffic News".

Source: Airports Authority of India publishes, for every month, a set of PDFs under
https://www.aai.aero/sites/default/files/traffic-news/. Annexure-III (passengers) is a 7-page
bilingual PDF: page 1 is IIIA International passengers, pages 2-4 IIIB Domestic, pages 5-7 IIIC
Total, each one 8-column table (S.No, airport in Hindi + English, this month, same month a year
earlier, % change, April-to-month this FY, April-to-month last FY, % change), grouped by airport
category with sub-total and grand-total rows.

Filenames are irregular (May2K26Annex3.pdf, Jan2k26Annex3_0.pdf, Sep2k25Annex3%20.pdf,
Nov2k25Annex1_3.pdf for November 2025's Annexure-III ...), so they are never constructed: the
listing page is a Drupal view with an exposed Year filter and the Annexure-III link of every month
is taken from its link text. The loader walks years backwards from the current one until at least
MIN_MONTHS months are found and bundles the PDFs into one artifact.

Every PDF also carries the same month of the previous year, which is emitted as rows for that
earlier month unless that month's own PDF is in the bundle (the directly reported figure wins).
Files before ~April 2024 use a different layout (Indian digit grouping "4,79,949", row ids like
"कA1", a 4-row header); both layouts are handled.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

import pandas as pd
import pdfplumber

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

log = logging.getLogger(__name__)

LISTING_URL = "https://www.aai.aero/en/business-opportunities/aai-traffic-news"
YEAR_FILTER = "field_news_date_value[value][year]"
MIN_MONTHS = 24
MAX_YEARS_BACK = 4
TRAFFIC_TYPES = ("international", "domestic", "total")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_ANNEXURE_TYPE = {"A": "international", "B": "domestic", "C": "total"}

_LINK = re.compile(
    r"""<a\s+[^>]*href=["']([^"']*/traffic-news/[^"']+\.pdf)["'][^>]*>([^<]*)</a>""",
    re.IGNORECASE,
)
_ANNEX3_TEXT = re.compile(r"annexure\W*iii\b", re.IGNORECASE)
_ANNEX_LABEL = re.compile(r"ANNEXURE\s*-?\s*III\s*([ABC])\b", re.IGNORECASE)
_TYPE_LABEL = re.compile(r"\b(International|Domestic|Total)\s+Passengers", re.IGNORECASE)
_SNO = re.compile(r"^[A-Z]?\d{1,3}$")
_YEAR = re.compile(r"^\d{4}$")
_MONTH_WORD = re.compile(r"([A-Za-z]{3,9})\s*$")
_INT = re.compile(r"^-?\d+$")
_GRAND_TOTAL = re.compile(r"grand\s*total", re.IGNORECASE)

SPEC = DatasetSpec(
    key="aai_airport_traffic",
    title="AAI monthly airport-wise passenger traffic (Annexure-III of AAI Traffic News)",
    source_org="Airports Authority of India (AAI), Traffic News",
    source_url=LISTING_URL,
    landing_url=LISTING_URL,
    fmt=SourceFormat.ZIP,
    cadence=Cadence.MONTHLY,
    table_name="data.aai_airport_traffic",
    columns=(
        ColumnSpec(
            name="period",
            pg_type="date",
            description="Month the passengers were handled, as the first day of that month",
        ),
        ColumnSpec(
            name="airport",
            pg_type="text",
            description=(
                "Airport name as published in the annexure (English, title-cased), including any "
                "operator or site qualifier in brackets, e.g. 'Delhi (Dial)', 'Goa (Dabolim)'"
            ),
        ),
        ColumnSpec(
            name="traffic_type",
            pg_type="text",
            description=(
                "'international' (Annexure-IIIA), 'domestic' (Annexure-IIIB) or 'total' "
                "(Annexure-IIIC, domestic + international)"
            ),
            allowed=TRAFFIC_TYPES,
        ),
        ColumnSpec(
            name="passengers",
            pg_type="bigint",
            description=(
                "Passengers handled at the airport in the month (arriving plus departing, "
                "including transit as counted by the airport), in number"
            ),
            unit="passengers",
            min=0,
            max=50_000_000,
        ),
    ),
    unique_key=("period", "airport", "traffic_type"),
    # Live run 26-Aug-2026: 30 PDFs (Jan 2024 - Jun 2026) -> 42 months, 13,807 rows (310-344
    # airport rows per month). The smallest window the year walk can return is 24 PDFs (36 months,
    # ~12,000 rows) in early January; floor at ~80% of that.
    min_rows=10000,
    caveats=(
        "Figures are compiled by AAI from data supplied by each airport and cover AAI-operated, "
        "joint-venture (Delhi, Mumbai, Bengaluru, Hyderabad, Kannur ...), customs, state "
        "government and private airports as listed in the annexure; airports that report no "
        "traffic appear with 0.",
        "Passengers are counted as handled at the airport: arriving plus departing (including "
        "transit passengers where the airport counts them), so a domestic trip is counted at "
        "both ends. 'total' is the annexure's own Domestic + International figure.",
        "AAI states the report is provisional and subject to revision; the latest month is the "
        "most likely to be revised. Where a month is present both as its own report and as the "
        "'same month previous year' column of a later report, the direct report is used; the two "
        "differ for a few airports (June 2025: 7 of 325 figures, e.g. Bengaluru international "
        "555,388 in the June 2025 report vs 563,347 a year later).",
        "Airport names are as published for that month and change over time (Bangalore vs "
        "Bengaluru, Bombay vs Mumbai, Calicut vs Kozhikode, Trichy vs Tiruchirappalli, Delhi vs "
        "Delhi (Dial)); the same airport can therefore appear under more than one name across "
        "months.",
        "Category banner rows, sub-totals and grand totals are not loaded; all-India totals must "
        "be computed by summing airports for a period and traffic_type.",
    ),
    difficulty="medium",
)


def discover_annexure3_links(listing_html: str, base_url: str = LISTING_URL) -> list[str]:
    """Absolute URLs of every link whose text names Annexure-III, in page order, deduplicated."""
    seen: dict[str, None] = {}
    for href, text in _LINK.findall(listing_html):
        if _ANNEX3_TEXT.search(text):
            seen.setdefault(urljoin(base_url, href.strip()), None)
    return list(seen)


def year_listing_url(year: int) -> str:
    return f"{LISTING_URL}?{quote(YEAR_FILTER, safe='')}={year}"


def _english(cell: str | None) -> str:
    """The English part of a bilingual cell: from the first ASCII letter on, non-ASCII dropped."""
    if cell is None:
        return ""
    text = cell.replace("\n", " ")
    m = re.search(r"[A-Za-z]", text)
    if m is None:
        return ""
    text = re.sub(r"[^\x20-\x7e]", " ", text[m.start() :])
    text = re.sub(r"\s*\(\s*", " (", text)  # "AIZAWL(LENGPUI)" and "AIZAWL (LENGPUI)" agree
    text = re.sub(r"\s*\)", ")", text)
    return re.sub(r"\s+", " ", text).strip()


def _ascii(cell: str | None) -> str:
    """ASCII characters of a cell with all whitespace removed (row ids, years, numbers)."""
    if cell is None:
        return ""
    return re.sub(r"[^\x21-\x7e]", "", cell)


def _int(cell: str | None, where: str) -> int:
    text = _ascii(cell).replace(",", "")
    if not _INT.match(text):
        raise ValueError(f"{where}: passenger count {cell!r} is not a number")
    return int(text)


def _header_periods(rows: list[list[str | None]]) -> tuple[date, date] | None:
    """(this month, same month previous year) from a table's header rows, if it has them."""
    month: int | None = None
    years: tuple[int, int] | None = None
    for row in rows[:8]:
        if len(row) < 4:
            continue
        if _english(row[1]) and _SNO.match(_ascii(row[0])):
            break  # first airport row: the header is over
        c2, c3 = _ascii(row[2]), _ascii(row[3])
        if _YEAR.match(c2) and _YEAR.match(c3):
            years = (int(c2), int(c3))
            continue
        m2, m3 = _MONTH_WORD.search(_english(row[2])), _MONTH_WORD.search(_english(row[3]))
        if m2 and m3 and m2.group(1)[:3].lower() in _MONTHS:
            if m3.group(1)[:3].lower() != m2.group(1)[:3].lower():
                raise ValueError(f"header months differ: {row[2]!r} vs {row[3]!r}")
            month = _MONTHS[m2.group(1)[:3].lower()]
    if month is None or years is None:
        return None
    if years[0] - years[1] != 1:
        raise ValueError(f"header years {years} are not consecutive")
    return date(years[0], month, 1), date(years[1], month, 1)


def parse_annexure3(content: bytes, label: str = "annexure-III") -> pd.DataFrame:
    """One PDF -> frame (period, airport, traffic_type, passengers, prev_period, prev_passengers).

    Raises if a page cannot be attributed to an annexure, a header cannot be read, a passenger
    cell is not numeric, or the airport rows of an annexure do not add up to its grand total.
    """
    records: list[dict[str, object]] = []
    grand: dict[str, tuple[int, int]] = {}
    traffic_type: str | None = None
    periods: tuple[date, date] | None = None
    with pdfplumber.open(BytesIO(content)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            where = f"{label} page {page_no}"
            text = page.extract_text() or ""
            m_annex = _ANNEX_LABEL.search(text)
            m_type = _TYPE_LABEL.search(text)
            if m_annex:
                traffic_type = _ANNEXURE_TYPE[m_annex.group(1).upper()]
            elif m_type:
                traffic_type = m_type.group(1).lower()
            if traffic_type is None:
                raise ValueError(f"{where}: cannot tell which annexure (IIIA/B/C) it belongs to")
            tables = page.extract_tables()
            if not tables:
                raise ValueError(f"{where}: no table found")
            for table in tables:
                periods = _header_periods(table) or periods
                if periods is None:
                    raise ValueError(f"{where}: month/year header not found")
                for row in table:
                    if len(row) != 8:
                        raise ValueError(f"{where}: expected 8 columns, got {len(row)}: {row}")
                    sno, airport = _ascii(row[0]), _english(row[1])
                    if _GRAND_TOTAL.search(_english(row[0])):
                        if traffic_type in grand:
                            raise ValueError(f"{where}: second grand total for {traffic_type}")
                        grand[traffic_type] = (_int(row[2], where), _int(row[3], where))
                        continue
                    if not airport or not _SNO.match(sno):
                        continue  # header, category banner, sub-total or footnote row
                    if all(_ascii(c) in {"", "-"} for c in row[2:]):
                        log.debug("%s: %s published without figures; skipped", where, airport)
                        continue  # e.g. Imphal international, April 2025: every cell blank
                    records.append(
                        {
                            "period": periods[0],
                            "airport": airport.title(),
                            "traffic_type": traffic_type,
                            "passengers": _int(row[2], f"{where} {airport}"),
                            "prev_period": periods[1],
                            "prev_passengers": _int(row[3], f"{where} {airport}"),
                        }
                    )
    if not records:
        raise ValueError(f"{label}: no airport rows parsed")
    frame = pd.DataFrame.from_records(records)
    _check_grand_totals(frame, grand, label)
    return frame


def _check_grand_totals(frame: pd.DataFrame, grand: dict[str, tuple[int, int]], label: str) -> None:
    """Airport rows must sum to the annexure's grand total: proves no page or row was missed."""
    for traffic_type in TRAFFIC_TYPES:
        if traffic_type not in grand:
            raise ValueError(f"{label}: no grand total row for {traffic_type} passengers")
        sel = frame[frame.traffic_type == traffic_type]
        for column, expected in zip(
            ("passengers", "prev_passengers"), grand[traffic_type], strict=True
        ):
            got = int(sel[column].sum())
            if abs(got - expected) > max(1, expected // 1000):
                raise ValueError(
                    f"{label}: {traffic_type} {column} sum {got} != grand total {expected}"
                )


def combine_reports(reports: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    """Merge per-file frames into the output shape, adding previous-year rows for months that no
    file in the bundle reports directly. If two files report the same month, the first (newest
    in listing order) wins."""
    direct: list[pd.DataFrame] = []
    derived: list[pd.DataFrame] = []
    covered: dict[date, str] = {}
    for name, frame in reports:
        period = frame.period.iloc[0]
        if (frame.period != period).any():
            raise ValueError(f"{name}: more than one reporting month in a single file")
        if period in covered:
            log.warning("%s: %s already reported by %s; skipping", name, period, covered[period])
            continue
        covered[period] = name
        direct.append(frame[["period", "airport", "traffic_type", "passengers"]])
        derived.append(
            frame[["prev_period", "airport", "traffic_type", "prev_passengers"]].rename(
                columns={"prev_period": "period", "prev_passengers": "passengers"}
            )
        )
    if not direct:
        raise ValueError("no reports to combine")
    out = pd.concat(direct, ignore_index=True)
    extra = pd.concat(derived, ignore_index=True)
    extra = extra[~extra.period.isin(covered)]
    out = pd.concat([out, extra], ignore_index=True)
    out = out.sort_values(["period", "traffic_type", "airport"], kind="stable")
    out["passengers"] = out["passengers"].astype("int64")
    return out.reset_index(drop=True)


class AaiAirportTrafficLoader(BaseLoader):
    def fetch_raw(self) -> RawArtifact:
        this_year = date.today().year
        files: list[tuple[str, bytes]] = []
        urls: list[str] = []
        for year in range(this_year, this_year - MAX_YEARS_BACK, -1):
            listing = fetch(self.spec.key, year_listing_url(year), verify_tls=self.spec.verify_tls)
            files.append((f"listing_{year}.html", listing.content))
            links = discover_annexure3_links(
                listing.content.decode("utf-8", errors="replace"), listing.url
            )
            log.info("AAI traffic news %s: %d Annexure-III links", year, len(links))
            urls.extend(u for u in links if u not in urls)
            if len(urls) >= MIN_MONTHS:
                break
        if len(urls) < MIN_MONTHS:
            raise ValueError(f"only {len(urls)} Annexure-III links found; need {MIN_MONTHS}")
        for i, url in enumerate(urls, start=1):
            raw = fetch(self.spec.key, url, verify_tls=self.spec.verify_tls)
            if not raw.content.startswith(b"%PDF"):
                raise ValueError(f"{url} did not return a PDF (content-type {raw.content_type})")
            files.append((f"{i:02d}_{unquote(urlsplit(url).path.rsplit('/', 1)[-1])}", raw.content))
        return bundle(self.spec.key, LISTING_URL, files)

    def parse(self, raw: RawArtifact) -> pd.DataFrame:
        reports = [
            (name, parse_annexure3(content, name))
            for name, content in unbundle(raw).items()
            if name.lower().endswith(".pdf")
        ]
        if not reports:
            raise ValueError("bundle contains no Annexure-III PDFs")
        return combine_reports(reports)


def build(snapshot_dir: Path | None = None) -> BaseLoader:
    return AaiAirportTrafficLoader(SPEC, snapshot_dir=snapshot_dir)
