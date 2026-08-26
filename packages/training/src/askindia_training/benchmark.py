"""Benchmark SQL-generation models with the same scorer on the same held-out questions.

    uv run python -m askindia_training.benchmark \\
        --models ollama/qwen2.5-coder:7b,ollama/askindia-lora,ollama/qwen2.5-coder:3b

Two held-out sets: the 60 hand-written L1 gold questions (never used for training) and the
template test split (templates held out of training). Only SQL_MODEL varies between runs; intake
and composition use the same chat model throughout, so the comparison isolates SQL generation.
Outputs one table (markdown + CSV) with execution accuracy per set, answered rate, mean attempts,
and p50/p95 latency; cost is reported as GPU-seconds per query because all models run locally.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from askindia_agents.settings import get_settings
from askindia_evals.l1 import accuracy_table, evaluate, load_gold


def template_test_items(pairs_path: Path, limit: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in pairs_path.read_text().splitlines() if line.strip()]
    test = [r for r in rows if r["split"] == "test"]
    # deterministic, dataset-balanced subset
    by_ds: dict[str, list[dict[str, Any]]] = {}
    for r in test:
        by_ds.setdefault(r["dataset"], []).append(r)
    items: list[dict[str, Any]] = []
    per = max(1, limit // max(1, len(by_ds)))
    for ds in sorted(by_ds):
        for r in by_ds[ds][:per]:
            items.append(
                {
                    "id": r["id"],
                    "dataset": ds,
                    "complexity": r["complexity"],
                    "question": r["question"],
                    "sql": r["sql"],
                }
            )
    return items


def run_model(model: str, sets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    os.environ["SQL_MODEL"] = model
    get_settings.cache_clear()
    out: dict[str, Any] = {"model": model}
    for name, items in sets.items():
        records = evaluate(items, verbose=False)
        overall = accuracy_table(records, "dataset")[-1]
        lat = sorted(r["seconds"] for r in records)
        out[name] = {
            "n": overall["n"],
            "accuracy_pct": overall["accuracy_pct"],
            "answered_pct": overall["answered_pct"],
            "mean_attempts": overall["mean_attempts"],
            "p50_s": lat[len(lat) // 2],
            "p95_s": lat[min(len(lat) - 1, int(len(lat) * 0.95))],
            "records": records,
        }
        print(
            f"{model:32s} {name:14s} acc={overall['accuracy_pct']}% p50={out[name]['p50_s']}s",
            flush=True,
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, help="comma-separated LiteLLM model ids")
    parser.add_argument("--pairs", default="results/training/pairs.jsonl")
    parser.add_argument("--template-test-limit", type=int, default=60)
    parser.add_argument("--out", default="results/benchmarks/p17")
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    sets = {
        "gold60": load_gold(),
        "template_test": template_test_items(Path(args.pairs), args.template_test_limit),
    }
    results = [run_model(m.strip(), sets) for m in args.models.split(",") if m.strip()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in results:
        rows.append(
            {
                "model": r["model"],
                "gold60_accuracy_pct": r["gold60"]["accuracy_pct"],
                "template_test_accuracy_pct": r["template_test"]["accuracy_pct"],
                "template_test_n": r["template_test"]["n"],
                "answered_pct_gold60": r["gold60"]["answered_pct"],
                "mean_attempts_gold60": r["gold60"]["mean_attempts"],
                "p50_s": r["gold60"]["p50_s"],
                "p95_s": r["gold60"]["p95_s"],
            }
        )
    with (out / f"bench01_p17-sql-models_{stamp}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (out / f"bench01_p17-predictions_{stamp}.json").write_text(
        json.dumps(results, indent=2, default=str)
    )
    lines = [
        f"P17 SQL-generation benchmark — {stamp} (chat model {os.environ.get('CHAT_MODEL')})",
        "",
        "| model | gold-60 exec acc | template-test exec acc | answered | attempts | p50 s | p95 s |",
        "|---|---|---|---|---|---|---|",
        *(
            f"| {r['model']} | {r['gold60_accuracy_pct']}% | {r['template_test_accuracy_pct']}% (n={r['template_test_n']}) | "
            f"{r['answered_pct_gold60']}% | {r['mean_attempts_gold60']} | {r['p50_s']} | {r['p95_s']} |"
            for r in rows
        ),
        "",
        "Cost: all models run on the same local GPU; per-query cost is the p50 latency in GPU-seconds.",
    ]
    (out / f"summary_p17_{stamp}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
