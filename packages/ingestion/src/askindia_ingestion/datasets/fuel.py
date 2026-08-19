"""PPAC daily retail selling price of petrol and diesel in the four metros, 16 Jun 2017 onwards.

Source: Petroleum Planning & Analysis Cell (Ministry of Petroleum & Natural Gas) posts one
cumulative PDF — every daily revision since dynamic pricing began on 16 June 2017, newest
first — as ``<unix_ts>_PP_9_a_DailyPriceMSHSD_Metro_DD.MM.YYYY.pdf``. The timestamp prefix is
not predictable, so the latest file is discovered from the listing page at fetch time.

Each page is a two-block table: petrol (date + four cities) on the left, diesel on the right.
pdfplumber renders three-digit prices with a stray space ("1 02.12" for 102.12) because of the
PDF's character spacing, so prices are matched as digit runs that may contain single spaces.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

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
from askindia_ingestion.loaders.http import fetch

LISTING_URL = (
    "https://ppac.gov.in/retail-selling-price-rsp-of-petrol-diesel-and-domestic-lpg/"
    "rsp-of-petrol-and-diesel-in-metro-cities-since-16-6-2017"
)
CITIES = ("Delhi", "Mumbai", "Chennai", "Kolkata")
FUELS = ("petrol", "diesel")

_LINK = re.compile(
    r"""href=["']([^"']*PP_9_a_DailyPriceMSHSD_Metro_(\d{2})\.(\d{2})\.(\d{4})\.pdf)["']""",
    re.IGNORECASE,
)
_DATE = r"(\d{1,2}-[A-Za-z]{3}-\d{2})"
_PRICE = r"(\d(?: ?\d)*\.\d{2})"
_ROW = re.compile(
    rf"^{_DATE}\s+{_PRICE}\s+{_PRICE}\s+{_PRICE}\s+{_PRICE}"
    rf"\s+{_DATE}\s+{_PRICE}\s+{_PRICE}\s+{_PRICE}\s+{_PRICE}\s*$"
)
_HEADER = re.compile(
    r"Retail Selling Price of Petrol\s+Retail Selling Price of Diesel\s+"
    r"Delhi\s+Mumbai\s+Chennai\s+Kolkata\s+Delhi\s+Mumbai\s+Chennai\s+Kolkata"
)

SPEC = DatasetSpec(
    key="fuel_prices_metro",
    title=(
        "Daily retail selling price of petrol and diesel in the four metros (16 Jun 2017 onwards)"
    ),
    source_org="Petroleum Planning & Analysis Cell, Ministry of Petroleum & Natural Gas",
    source_url=LISTING_URL,
    landing_url=LISTING_URL,
    fmt=SourceFormat.PDF,
    cadence=Cadence.MONTHLY,
    table_name="data.fuel_prices_metro",
    columns=(
        ColumnSpec(
            name="price_date",
            pg_type="date",
            description="Date of revision: the day the price applied (revisions take effect 6 AM)",
        ),
        ColumnSpec(
            name="city",
            pg_type="text",
            description="Metro city whose IOCL retail outlet price is reported",
            allowed=CITIES,
        ),
        ColumnSpec(
            name="fuel",
            pg_type="text",
            description="Fuel: 'petrol' (motor spirit, MS) or 'diesel' (high-speed diesel, HSD)",
            allowed=FUELS,
        ),
        ColumnSpec(
            name="price_inr_per_litre",
            pg_type="numeric(8,2)",
            description=(
                "Retail selling price at the pump, inclusive of excise, VAT and dealer commission"
            ),
            unit="INR per litre",
            min=30,
            max=250,
        ),
    ),
    unique_key=("price_date", "city", "fuel"),
    # 25-Aug-2026 file: 3,358 daily revision dates x 4 cities x 2 fuels = 26,864 rows; the file is
    # cumulative so it only grows. Floor at ~80% of that.
    min_rows=21000,
    caveats=(
        "Prices are Indian Oil Corporation (IOC) retail selling prices at the named metro city; "
        "other oil marketing companies and other cities in the same state differ by paise to "
        "rupees.",
        "Prices are inclusive of central excise, state VAT/sales tax and dealer commission, so "
        "differences between cities reflect state taxes more than product cost.",
        "Series starts 16 June 2017 when daily dynamic pricing began; earlier fortnightly "
        "revisions are not in this table. Each row is the price applicable that day (revisions "
        "from 6 AM).",
        "Only four metros (Delhi, Mumbai, Chennai, Kolkata) and only petrol and diesel: no LPG, "
        "ATF, CNG or non-metro cities.",
        "Diesel is usually but not always cheaper than petrol: Delhi diesel briefly exceeded "
        "petrol in June-July 2020 after a state VAT change.",
    ),
    difficulty="medium",
)


def discover_pdf_url(listing_html: str, base_url: str = LISTING_URL) -> str:
    """URL of the newest cumulative PDF linked from the listing page (by date in the filename)."""
    found: list[tuple[date, int, str]] = []
    for href, dd, mm, yyyy in _LINK.findall(listing_html):
        posted = date(int(yyyy), int(mm), int(dd))
        # Prefer the direct upload path over download.php mirrors for the same date.
        rank = 1 if "/uploads/" in href else 0
        found.append((posted, rank, urljoin(base_url, href)))
    if not found:
        raise ValueError("listing page has no PP_9_a_DailyPriceMSHSD_Metro_*.pdf link")
    found.sort()
    return found[-1][2]


def _price(text: str) -> float:
    return float(text.replace(" ", ""))


def _revision_date(text: str) -> date:
    return datetime.strptime(text, "%d-%b-%y").date()


def parse_pdf(content: bytes) -> pd.DataFrame:
    """Long frame (price_date, city, fuel, price_inr_per_litre) from the cumulative PDF."""
    records: list[dict[str, object]] = []
    with pdfplumber.open(BytesIO(content)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            matches = [m for m in (_ROW.match(ln.strip()) for ln in text.splitlines()) if m]
            if not matches:
                continue
            if not _HEADER.search(text):
                raise ValueError(f"page {page_no}: data rows without the expected column header")
            for m in matches:
                g = m.groups()
                petrol_date, diesel_date = _revision_date(g[0]), _revision_date(g[5])
                if petrol_date != diesel_date:
                    raise ValueError(
                        f"page {page_no}: petrol/diesel date mismatch {g[0]} vs {g[5]}"
                    )
                for fuel, offset in (("petrol", 1), ("diesel", 6)):
                    for i, city in enumerate(CITIES):
                        records.append(
                            {
                                "price_date": petrol_date,
                                "city": city,
                                "fuel": fuel,
                                "price_inr_per_litre": _price(g[offset + i]),
                            }
                        )
    if not records:
        raise ValueError("no revision rows parsed from PDF")
    return pd.DataFrame.from_records(records)


class FuelPricesLoader(BaseLoader):
    def fetch_raw(self) -> RawArtifact:
        listing = fetch(self.spec.key, LISTING_URL, verify_tls=self.spec.verify_tls)
        pdf_url = discover_pdf_url(listing.content.decode("utf-8", errors="replace"), listing.url)
        raw = fetch(self.spec.key, pdf_url, verify_tls=self.spec.verify_tls)
        if not raw.content.startswith(b"%PDF"):
            raise ValueError(f"{pdf_url} did not return a PDF (content-type {raw.content_type})")
        return raw

    def parse(self, raw: RawArtifact) -> pd.DataFrame:
        return parse_pdf(raw.content)


def build(snapshot_dir: Path | None = None) -> BaseLoader:
    return FuelPricesLoader(SPEC, snapshot_dir=snapshot_dir)
