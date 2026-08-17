"""Census of India 2011 — Primary Census Abstract for India, states and districts.

Source: ORGI NADA catalog 6191 (PCA SD).
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from askindia_ingestion.contracts import (
    BaseLoader,
    Cadence,
    ColumnSpec,
    DatasetSpec,
    RawArtifact,
    SourceFormat,
)
from askindia_ingestion.loaders.http import fetch

SOURCE_URL = (
    "https://censusindia.gov.in/nada/index.php/catalog/6191/download/9268/"
    "DDW_PCA0000_2011_Indiastatedist.xlsx"
)

RENAME = {
    "State": "state_code",
    "District": "district_code",
    "Level": "level",
    "Name": "name",
    "TRU": "tru",
    "No_HH": "households",
    "TOT_P": "population_total",
    "TOT_M": "population_male",
    "TOT_F": "population_female",
    "P_06": "population_0_6",
    "P_LIT": "literates_total",
    "M_LIT": "literates_male",
    "F_LIT": "literates_female",
    "P_SC": "sc_population",
    "P_ST": "st_population",
    "TOT_WORK_P": "workers_total",
    "MAINWORK_P": "workers_main",
    "MARGWORK_P": "workers_marginal",
    "NON_WORK_P": "non_workers",
}

_COUNT = "count of persons"
SPEC = DatasetSpec(
    key="census_2011_pca",
    title="Census 2011 Primary Census Abstract — India, states and districts",
    source_org="Office of the Registrar General & Census Commissioner, India (ORGI)",
    source_url=SOURCE_URL,
    landing_url="https://censusindia.gov.in/nada/index.php/catalog/6191",
    fmt=SourceFormat.XLSX,
    cadence=Cadence.STATIC,
    table_name="data.census_2011_pca",
    columns=(
        ColumnSpec(
            name="state_code",
            pg_type="text",
            description="Two-digit 2011 census state code; '00' is India",
        ),
        ColumnSpec(
            name="district_code",
            pg_type="text",
            description="Three-digit district code within the state; '000' for state/India rows",
        ),
        ColumnSpec(
            name="level",
            pg_type="text",
            description="Geographic level of the row",
            allowed=("INDIA", "STATE", "DISTRICT"),
        ),
        ColumnSpec(
            name="name",
            pg_type="text",
            description="Name of India, the state/UT, or the district as printed in the census",
        ),
        ColumnSpec(
            name="tru",
            pg_type="text",
            description="Total, Rural or Urban part of the area",
            allowed=("Total", "Rural", "Urban"),
        ),
        ColumnSpec(
            name="households",
            pg_type="bigint",
            description="Number of households",
            unit="households",
            min=0,
        ),
        ColumnSpec(
            name="population_total",
            pg_type="bigint",
            description="Total population",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="population_male",
            pg_type="bigint",
            description="Male population",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="population_female",
            pg_type="bigint",
            description="Female population",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="population_0_6",
            pg_type="bigint",
            description="Population aged 0-6 years",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="literates_total",
            pg_type="bigint",
            description="Literates (age 7 and above who can read and write with understanding)",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="literates_male",
            pg_type="bigint",
            description="Male literates",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="literates_female",
            pg_type="bigint",
            description="Female literates",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="sc_population",
            pg_type="bigint",
            description="Scheduled Castes population",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="st_population",
            pg_type="bigint",
            description="Scheduled Tribes population",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="workers_total",
            pg_type="bigint",
            description="Total workers (main + marginal)",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="workers_main",
            pg_type="bigint",
            description="Main workers (worked 6 months or more in the reference year)",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="workers_marginal",
            pg_type="bigint",
            description="Marginal workers (worked less than 6 months)",
            unit=_COUNT,
            min=0,
        ),
        ColumnSpec(
            name="non_workers", pg_type="bigint", description="Non-workers", unit=_COUNT, min=0
        ),
    ),
    unique_key=("state_code", "district_code", "level", "tru"),
    min_rows=1600,
    caveats=(
        "Reference date 1 March 2011; no later census exists, so these figures do not "
        "describe today's population.",
        "Boundaries are as of 2011: Telangana is part of Andhra Pradesh, Ladakh is part of "
        "Jammu & Kashmir, and districts created after 2011 are absent.",
        "Literacy is defined for persons aged 7 and above; literacy rate = literates / "
        "(population_total - population_0_6).",
        "Each area appears three times (Total, Rural, Urban); filter tru = 'Total' unless a "
        "rural/urban split is wanted.",
        "censusindia.gov.in serves an incomplete certificate chain, so the download is fetched "
        "without TLS verification; the file hash is recorded on every load.",
    ),
    difficulty="low",
    verify_tls=False,
)


class CensusLoader(BaseLoader):
    def fetch_raw(self) -> RawArtifact:
        return fetch(self.spec.key, self.spec.source_url, verify_tls=self.spec.verify_tls)

    def parse(self, raw: RawArtifact) -> pd.DataFrame:
        frame = pd.read_excel(io.BytesIO(raw.content), sheet_name=0, dtype=str)
        frame.columns = [str(c).strip() for c in frame.columns]
        missing = [c for c in RENAME if c not in frame.columns]
        if missing:
            raise ValueError(f"census workbook is missing expected columns: {missing}")
        frame = frame.rename(columns=RENAME).loc[:, list(RENAME.values())]
        frame["level"] = frame["level"].str.strip().str.upper()
        frame["tru"] = frame["tru"].str.strip().str.title()
        frame["name"] = frame["name"].str.strip()
        for col in frame.columns[5:]:
            frame[col] = pd.to_numeric(frame[col], errors="raise").astype("int64")
        return frame.reset_index(drop=True)


def build(snapshot_dir: Path | None = None) -> BaseLoader:
    return CensusLoader(SPEC, snapshot_dir=snapshot_dir)
