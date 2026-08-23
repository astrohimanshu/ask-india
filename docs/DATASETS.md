# Dataset catalogue

Six official sources survived the source spike ([spike_report.json](spike_report.json) is the
run that decided it: fetch, parse and validate against the live source, no hand-fixing). Two
planned sources did not make v1 and are recorded as such rather than approximated:

| Dataset | Source | Coverage at last load | Rows |
|---|---|---|---|
| `census_2011_pca` | ORGI, Census 2011 Primary Census Abstract (state/district) | 1 March 2011 | 2,028 |
| `imd_subdivision_rainfall` | IMD Pune, monthly rainfall by meteorological subdivision | 1901 – 2025 | 58,136 |
| `fuel_prices_metro` | PPAC (MoPNG), daily petrol/diesel price in four metros | 16 Jun 2017 – Aug 2026 | 26,864 |
| `crop_production` | DA&FW, five-year area/production/yield estimates | crop years 2021-22 – 2025-26 | 7,189 |
| `dgca_airline_traffic` | DGCA, carrier-wise monthly traffic statistics | Jan 2019 – Jul 2026 | 2,770 |
| `aai_airport_traffic` | AAI, airport-wise monthly passengers (Annexure-III) | Jan 2023 – Jun 2026 | 13,807 |

Not in v1:

- **CPI inflation (MoSPI)** — published only as monthly press-release PDFs with a four-row header
  grid; parseable but high effort, deferred.
- **Road accidents (MoRTH)** — source discovery did not complete; not attempted.
- **data.gov.in API** — `api.data.gov.in` timed out or rate-limited from both build machines; every
  dataset above is fetched from its publishing ministry's own site instead.

Every loaded row carries `dataset_version` (fetch date + content hash); each load is recorded in
`meta.dataset_runs`, and a validation failure quarantines the batch instead of loading it.
