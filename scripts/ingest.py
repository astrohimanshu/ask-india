"""Ingest registered datasets into Postgres: fetch, snapshot, parse, validate, load, audit.

    uv run scripts/ingest.py [--only key,key] [--snapshots data/snapshots] [--report out.json]

Quarantined and failed runs are recorded in meta.dataset_runs and reported; they never load.
Setting ASKINDIA_BREAK_DATASET=<key> corrupts that dataset's parsed frame on purpose (failure
drill): the batch must be quarantined and the previous version must stay queryable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from askindia_ingestion.contracts import LoadStatus
from askindia_ingestion.persistence import PostgresPersister
from askindia_ingestion.registry import REGISTRY, build_loader


def _broken_parse(parse):  # type: ignore[no-untyped-def]
    def wrapped(raw):  # type: ignore[no-untyped-def]
        frame = parse(raw)
        return frame.drop(columns=[frame.columns[0]])  # a missing column must quarantine the batch

    return wrapped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="")
    parser.add_argument("--snapshots", default="data/snapshots")
    parser.add_argument("--report", default="", help="write a JSON summary of every run here")
    args = parser.parse_args()
    report: list[dict[str, object]] = []
    keys = [k for k in args.only.split(",") if k] or list(REGISTRY)
    persister = PostgresPersister(os.environ["DATABASE_URL"])
    drill = os.environ.get("ASKINDIA_BREAK_DATASET", "")
    failures = 0
    for key in keys:
        loader = build_loader(REGISTRY[key])
        loader.snapshot_dir = Path(args.snapshots)
        if drill == key:
            # Failure drill: simulate a source format change so the quarantine path is exercised.
            loader.parse = _broken_parse(loader.parse)  # type: ignore[method-assign]
        result = loader.run(persister)
        if result.status is not LoadStatus.LOADED:
            persister.record(result)
            failures += 1
        report.append(
            {
                "dataset": key,
                "status": result.status.value,
                "rows": result.row_count,
                "version": result.dataset_version,
                "error": result.error,
                "failures": [c.__dict__ for c in result.validation.failures]
                if result.validation
                else [],
            }
        )
        print(
            f"{key:28s} {result.status.value:12s} rows={result.row_count:<7d} "
            f"version={result.dataset_version}"
            + (f"  error={result.error}" if result.error else "")
        )
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
