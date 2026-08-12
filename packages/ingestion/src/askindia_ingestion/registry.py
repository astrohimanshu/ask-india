"""The dataset catalogue: one DatasetSpec per source, and the loader that brings it in.

Populated as sources are proven by scripts/spike_all_datasets.py; a spec is only here if its
source was fetched and parsed for real.
"""

from __future__ import annotations

from askindia_ingestion.contracts import BaseLoader, DatasetSpec

REGISTRY: dict[str, DatasetSpec] = {}


def build_loader(spec: DatasetSpec) -> BaseLoader:
    raise NotImplementedError(f"no loader registered for {spec.key}")
