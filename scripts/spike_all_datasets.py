"""Try every registered dataset against its real source and write an honest spike report.

    uv run scripts/spike_all_datasets.py [--only key,key] [--out spike_report.json]

For each dataset: fetch → parse → validate (no database writes). The report records what
actually happened. A source that fails stays failed in the report; it is not patched over.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from askindia_ingestion.contracts import BaseLoader
from askindia_ingestion.registry import REGISTRY, build_loader
from askindia_ingestion.validation import ValidationFailedError


def spike_one(loader: BaseLoader, snapshot_dir: Path) -> dict[str, object]:
    spec = loader.spec
    row: dict[str, object] = {
        "dataset": spec.key,
        "format": spec.fmt.value,
        "difficulty": spec.difficulty,
        "source_url": spec.source_url,
        "fetch": None,
        "parse": None,
        "validate": None,
        "rows": 0,
        "columns": [],
        "coverage": None,
        "error": None,
        "seconds": 0.0,
    }
    started = time.perf_counter()
    try:
        raw = loader.fetch_raw()
        row["fetch"] = "ok"
        row["bytes"] = len(raw.content)
        row["sha256"] = raw.sha256
        loader.snapshot_dir = snapshot_dir
        loader.snapshot(raw)
    except Exception as e:
        row["fetch"] = "fail"
        row["error"] = f"{type(e).__name__}: {e}"
        row["seconds"] = round(time.perf_counter() - started, 1)
        return row
    try:
        frame = loader.parse(raw)
        row["parse"] = "ok"
        row["rows"] = len(frame)
        row["columns"] = [str(c) for c in frame.columns][:40]
        if "period" in frame.columns:
            row["coverage"] = f"{frame['period'].min()} .. {frame['period'].max()}"
        elif "year" in frame.columns:
            row["coverage"] = f"{frame['year'].min()} .. {frame['year'].max()}"
    except Exception as e:
        row["parse"] = "fail"
        row["error"] = f"{type(e).__name__}: {e}"
        row["seconds"] = round(time.perf_counter() - started, 1)
        return row
    try:
        present = [c for c in spec.column_names if c in frame.columns]
        report = loader.validate(frame.loc[:, present])
        row["validate"] = "ok"
        row["checks"] = len(report.checks)
    except ValidationFailedError as e:
        row["validate"] = "fail"
        row["error"] = str(e)
        row["failures"] = [c.__dict__ for c in e.report.failures]
    except Exception as e:
        row["validate"] = "fail"
        row["error"] = f"{type(e).__name__}: {e}"
    row["seconds"] = round(time.perf_counter() - started, 1)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="", help="comma-separated dataset keys")
    parser.add_argument("--out", default="spike_report.json")
    parser.add_argument("--snapshots", default="data/snapshots")
    args = parser.parse_args()
    keys = [k for k in args.only.split(",") if k] or list(REGISTRY)
    snapshot_dir = Path(args.snapshots)

    rows = []
    for key in keys:
        print(f"== {key}", flush=True)
        row = spike_one(build_loader(REGISTRY[key]), snapshot_dir)
        status = "/".join(str(row[s]) for s in ("fetch", "parse", "validate"))
        print(
            f"   {status}  rows={row['rows']}  {row['coverage'] or ''}  {row['error'] or ''}",
            flush=True,
        )
        rows.append(row)

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "datasets": rows,
        "survivors": [r["dataset"] for r in rows if r["validate"] == "ok"],
    }
    Path(args.out).write_text(json.dumps(report, indent=2, default=str))
    print(f"\nsurvivors: {report['survivors']}\nwritten {args.out}")
    return 0 if report["survivors"] else 1


if __name__ == "__main__":
    sys.exit(main())
