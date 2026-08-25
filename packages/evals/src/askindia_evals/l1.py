"""L1 evaluation: execution accuracy of the agent against the gold question set.

    uv run python -m askindia_evals.l1 [--subset N] [--ids a,b] [--out results/evals/l1]

For every gold item the gold SQL is executed live (as the read-only role) and the agent answers
the question; the two result sets are compared with :mod:`askindia_evals.scoring`. Outputs, all
sharing one timestamp: per-question predictions (JSON), per-dataset and per-complexity accuracy
tables (CSV), a summary digest (TXT) and a figure (PNG).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from askindia_agents.executor import SQLError, execute_readonly
from askindia_agents.graph import build_graph
from askindia_agents.graph.build import real_deps
from askindia_agents.sqlguard import admit
from askindia_evals.scoring import score_result

GOLD_PATH = Path(__file__).resolve().parent / "gold" / "l1_questions.yaml"


def load_gold(path: Path = GOLD_PATH) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = yaml.safe_load(path.read_text())
    return items


def gold_rows(sql: str, dsn_ro: str) -> list[dict[str, Any]]:
    return [dict(r) for r in execute_readonly(admit(sql), dsn=dsn_ro).rows]


def evaluate(items: list[dict[str, Any]], *, verbose: bool = True) -> list[dict[str, Any]]:
    deps = real_deps()
    graph = build_graph(deps)
    dsn_ro = os.environ["DATABASE_URL_RO"]
    records: list[dict[str, Any]] = []
    for i, item in enumerate(items, 1):
        started = time.perf_counter()
        try:
            gold = gold_rows(item["sql"], dsn_ro)
        except SQLError as e:
            raise RuntimeError(f"gold SQL for {item['id']} failed: {e}") from e
        final = graph.invoke({"question": item["question"]})["final"]
        elapsed = time.perf_counter() - started
        score = score_result(gold, final.get("rows", [])) if final["status"] == "answered" else None
        record = {
            "id": item["id"],
            "dataset": item["dataset"],
            "complexity": item["complexity"],
            "question": item["question"],
            "gold_sql": item["sql"],
            "gold_rows": gold[:20],
            "status": final["status"],
            "predicted_sql": final.get("sql"),
            "predicted_rows": final.get("rows", [])[:20],
            "correct": bool(score and score.correct),
            "reason": score.reason if score else f"status={final['status']}",
            "attempts": final.get("attempts", 0),
            "retrieved_dataset": (final.get("citation") or {}).get("dataset"),
            "guard_passed": (final.get("guard") or {}).get("passed"),
            "seconds": round(elapsed, 1),
        }
        records.append(record)
        if verbose:
            mark = "✔" if record["correct"] else "✘"
            reason = record["reason"][:60]
            print(
                f"{i:3d}/{len(items)} {mark} {item['id']:8s} {elapsed:5.1f}s {reason}", flush=True
            )
    return records


def accuracy_table(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[r[key]].append(r)
    rows = []
    for name in sorted(groups):
        rs = groups[name]
        n_correct = sum(r["correct"] for r in rs)
        rows.append(
            {
                key: name,
                "n": len(rs),
                "correct": n_correct,
                "accuracy_pct": round(100.0 * n_correct / len(rs), 1),
                "answered_pct": round(
                    100.0 * sum(r["status"] == "answered" for r in rs) / len(rs), 1
                ),
                "mean_attempts": round(sum(r["attempts"] for r in rs) / len(rs), 2),
                "p50_seconds": sorted(r["seconds"] for r in rs)[len(rs) // 2],
            }
        )
    total = sum(r["correct"] for r in records)
    rows.append(
        {
            key: "ALL",
            "n": len(records),
            "correct": total,
            "accuracy_pct": round(100.0 * total / len(records), 1) if records else 0.0,
            "answered_pct": round(
                100.0 * sum(r["status"] == "answered" for r in records) / len(records), 1
            )
            if records
            else 0.0,
            "mean_attempts": round(sum(r["attempts"] for r in records) / len(records), 2)
            if records
            else 0.0,
            "p50_seconds": sorted(r["seconds"] for r in records)[len(records) // 2]
            if records
            else 0.0,
        }
    )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_figure(
    path: Path, by_dataset: list[dict[str, Any]], threshold: float, stamp: str
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "axes.labelsize": 12,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "axes.titlesize": 13,
        }
    )
    rows = [r for r in by_dataset if r["dataset"] != "ALL"]
    overall = next(r for r in by_dataset if r["dataset"] == "ALL")
    fig, ax = plt.subplots(figsize=(9, 5))
    names = [r["dataset"] for r in rows]
    acc = [r["accuracy_pct"] for r in rows]
    bars = ax.bar(names, acc, color="#e0812f", label="Execution accuracy per dataset")
    for bar, r in zip(bars, rows, strict=True):
        ax.annotate(
            f"{r['correct']}/{r['n']}",
            (bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5),
            ha="center",
            va="bottom",
            fontsize=10,
        )
    ax.axhline(threshold, color="#b00020", linestyle="--", linewidth=1.2)
    ax.annotate(
        f"CI merge gate: {threshold:.0f}%",
        (0.01, threshold + 1.5),
        xycoords=("axes fraction", "data"),
        fontsize=10,
        color="#b00020",
        bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5},
    )
    ax.axhline(overall["accuracy_pct"], color="#333333", linestyle=":", linewidth=1.2)
    ax.annotate(
        f"overall: {overall['accuracy_pct']:.1f}% ({overall['correct']}/{overall['n']})",
        (0.99, overall["accuracy_pct"] + 1.5),
        xycoords=("axes fraction", "data"),
        ha="right",
        fontsize=10,
        bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5},
    )
    ax.set_ylim(0, 112)
    ax.set_ylabel("Execution accuracy (% of gold questions returning equivalent rows)")
    ax.set_xlabel("Dataset")
    ax.set_title(f"L1 execution accuracy by dataset — {stamp}")
    ax.legend(loc="lower right")
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", type=int, default=0, help="random stratified subset size")
    parser.add_argument("--ids", default="", help="comma-separated gold ids")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="results/evals/l1")
    parser.add_argument("--threshold", type=float, default=70.0, help="gate drawn on the figure")
    args = parser.parse_args()

    items = load_gold()
    if args.ids:
        wanted = set(args.ids.split(","))
        items = [i for i in items if i["id"] in wanted]
    elif args.subset:
        rng = random.Random(args.seed)
        by_ds: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for i in items:
            by_ds[i["dataset"]].append(i)
        per = max(1, args.subset // len(by_ds))
        items = [x for ds in sorted(by_ds) for x in rng.sample(by_ds[ds], min(per, len(by_ds[ds])))]

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records = evaluate(items)
    by_dataset = accuracy_table(records, "dataset")
    by_complexity = accuracy_table(records, "complexity")

    (out / f"eval01_l1-predictions_{stamp}.json").write_text(
        json.dumps(records, indent=2, default=str)
    )
    write_csv(out / f"eval01_l1-accuracy-by-dataset_{stamp}.csv", by_dataset)
    write_csv(out / f"eval02_l1-accuracy-by-complexity_{stamp}.csv", by_complexity)
    fig_dir = out.parent.parent / "figures" / "l1"
    fig_dir.mkdir(parents=True, exist_ok=True)
    write_figure(
        fig_dir / f"fig01_l1-accuracy-by-dataset_{stamp}.png", by_dataset, args.threshold, stamp
    )

    overall = by_dataset[-1]
    settings_line = f"models: {os.environ.get('SQL_MODEL')} / {os.environ.get('CHAT_MODEL')}"
    lines = [
        f"L1 execution accuracy — {stamp}",
        settings_line,
        f"questions: {overall['n']}  correct: {overall['correct']}  "
        f"accuracy: {overall['accuracy_pct']}%",
        f"answered: {overall['answered_pct']}%  mean attempts: {overall['mean_attempts']}  "
        f"p50 latency: {overall['p50_seconds']}s",
        "",
        "by dataset:",
        *(
            f"  {r['dataset']:26s} {r['correct']:2d}/{r['n']:<2d} {r['accuracy_pct']:5.1f}%"
            for r in by_dataset
            if r["dataset"] != "ALL"
        ),
        "",
        "by complexity:",
        *(
            f"  {r['complexity']:10s} {r['correct']:2d}/{r['n']:<2d} {r['accuracy_pct']:5.1f}%"
            for r in by_complexity
            if r["complexity"] != "ALL"
        ),
        "",
        "failures:",
        *(f"  {r['id']:8s} {r['reason'][:90]}" for r in records if not r["correct"]),
    ]
    (out / f"summary_l1_{stamp}.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nACCURACY {overall['accuracy_pct']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
