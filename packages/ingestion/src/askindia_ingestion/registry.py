"""The dataset catalogue: one DatasetSpec per proven source and the loader that brings it in.

A dataset is listed here only after scripts/spike_all_datasets.py fetched, parsed and validated
it against the real source. Modules are imported lazily so one broken parser cannot take the
whole catalogue down.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from askindia_ingestion.contracts import BaseLoader, DatasetSpec

# dataset key -> module under askindia_ingestion.datasets exposing SPEC and build()
MODULES: dict[str, str] = {
    "census_2011_pca": "census",
    "imd_subdivision_rainfall": "rainfall",
    "fuel_prices_metro": "fuel",
    "crop_production": "crops",
}


def _module(key: str):  # type: ignore[no-untyped-def]
    return import_module(f"askindia_ingestion.datasets.{MODULES[key]}")


def spec_for(key: str) -> DatasetSpec:
    spec: DatasetSpec = _module(key).SPEC
    return spec


REGISTRY: dict[str, DatasetSpec] = {key: spec_for(key) for key in MODULES}


def build_loader(spec: DatasetSpec, snapshot_dir: Path | None = None) -> BaseLoader:
    loader: BaseLoader = _module(spec.key).build(snapshot_dir)
    return loader
