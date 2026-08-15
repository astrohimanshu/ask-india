"""Ingest registered datasets into Postgres: fetch, snapshot, parse, validate, load, audit.

    uv run scripts/ingest.py [--only key,key] [--snapshots data/snapshots]

Quarantined and failed runs are recorded in meta.dataset_runs and reported; they never load.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from askindia_ingestion.contracts import LoadStatus
from askindia_ingestion.persistence import PostgresPersister
from askindia_ingestion.registry import REGISTRY, build_loader


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="")
    parser.add_argument("--snapshots", default="data/snapshots")
    args = parser.parse_args()
    keys = [k for k in args.only.split(",") if k] or list(REGISTRY)
    persister = PostgresPersister(os.environ["DATABASE_URL"])
    failures = 0
    for key in keys:
        loader = build_loader(REGISTRY[key])
        loader.snapshot_dir = Path(args.snapshots)
        result = loader.run(persister)
        if result.status is not LoadStatus.LOADED:
            persister.record(result)
            failures += 1
        print(
            f"{key:28s} {result.status.value:12s} rows={result.row_count:<7d} "
            f"version={result.dataset_version}"
            + (f"  error={result.error}" if result.error else "")
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
