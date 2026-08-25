"""L2 evaluation: verdict accuracy of claim mode on labelled claims.

    uv run python -m askindia_evals.l2 [--limit N] [--out results/evals/l2]

Claims come from three sources: true facts computed live from L1 gold SQL and rendered through
templates (then mutated into Misleading and Contradicted variants), a hand-written Unverifiable
set (statistical but outside the catalogue), and a hand-written non-statistical set. Outputs a
per-claim prediction file, a confusion matrix, per-class precision/recall and a heat-map figure.
The headline metric is Unverifiable recall: a confident verdict on an uncheckable claim is the
catastrophic failure mode.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from askindia_agents.executor import execute_readonly
from askindia_agents.graph import build_graph
from askindia_agents.graph.build import real_deps
from askindia_agents.sqlguard import admit
from askindia_evals.l1 import load_gold

CLAIMS_PATH = Path(__file__).resolve().parent / "gold" / "l2_claims.yaml"
CLASSES = ["Supported", "Misleading", "Contradicted", "Unverifiable"]


def _true_value(sql: str, dsn_ro: str) -> float:
    rows = execute_readonly(admit(sql), dsn=dsn_ro).rows
    for v in rows[0].values():
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    raise ValueError("gold result has no numeric value")


def build_claims(rng: random.Random, dsn_ro: str) -> list[dict[str, Any]]:
    spec = yaml.safe_load(CLAIMS_PATH.read_text())
    gold = {g["id"]: g for g in load_gold()}
    claims: list[dict[str, Any]] = []
    for item in spec["templated"]:
        g = gold[item["gold_id"]]
        truth = _true_value(g["sql"], dsn_ro)
        supported = truth * rng.uniform(0.97, 1.03)
        misleading = truth * rng.choice([rng.uniform(1.4, 1.7), rng.uniform(0.55, 0.7)])
        contradicted = truth * rng.choice([rng.uniform(3.2, 5.0), rng.uniform(0.1, 0.3)])
        for label, value in (
            ("Supported", supported),
            ("Misleading", misleading),
            ("Contradicted", contradicted),
        ):
            claims.append(
                {
                    "claim": item["template"].format(value=value),
                    "label": label,
                    "source": "templated",
                    "gold_id": item["gold_id"],
                    "dataset": g["dataset"],
                    "true_value": truth,
                    "claimed_value": value,
                }
            )
    for text in spec["unverifiable"]:
        claims.append(
            {
                "claim": text,
                "label": "Unverifiable",
                "source": "unverifiable",
                "gold_id": None,
                "dataset": None,
                "true_value": None,
                "claimed_value": None,
            }
        )
    for text in spec["non_statistical"]:
        claims.append(
            {
                "claim": text,
                "label": "Unverifiable",
                "source": "non_statistical",
                "gold_id": None,
                "dataset": None,
                "true_value": None,
                "claimed_value": None,
            }
        )
    return claims


def predicted_verdict(final: dict[str, Any]) -> str:
    verdict = final.get("verdict") or {}
    if final.get("mode") == "claim" and verdict.get("verdict"):
        return str(verdict["verdict"])
    if final.get("status") in ("out_of_scope", "failed", "unverifiable"):
        return "Unverifiable"
    return "Unverifiable"  # answered as a question: no verdict was issued


def evaluate(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    graph = build_graph(real_deps())
    records = []
    for i, c in enumerate(claims, 1):
        started = time.perf_counter()
        final = graph.invoke({"question": c["claim"]})["final"]
        pred = predicted_verdict(final)
        rec = {
            **c,
            "predicted": pred,
            "correct": pred == c["label"],
            "status": final["status"],
            "intent_as_claim": final.get("mode") == "claim",
            "sql": final.get("sql"),
            "actual": (final.get("verdict") or {}).get("actual"),
            "seconds": round(time.perf_counter() - started, 1),
        }
        records.append(rec)
        mark = "✔" if rec["correct"] else "✘"
        print(
            f"{i:3d}/{len(claims)} {mark} {c['label']:13s} -> {pred:13s} "
            f"{rec['seconds']:5.1f}s  {c['claim'][:70]}",
            flush=True,
        )
    return records


def confusion(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    m: dict[str, dict[str, int]] = {t: dict.fromkeys(CLASSES, 0) for t in CLASSES}
    for r in records:
        m[r["label"]][r["predicted"]] += 1
    return m


def class_metrics(m: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    rows = []
    for c in CLASSES:
        tp = m[c][c]
        support = sum(m[c].values())
        predicted = sum(m[t][c] for t in CLASSES)
        rows.append(
            {
                "class": c,
                "support": support,
                "recall_pct": round(100.0 * tp / support, 1) if support else None,
                "precision_pct": round(100.0 * tp / predicted, 1) if predicted else None,
            }
        )
    return rows


def write_figure(
    path: Path, m: dict[str, dict[str, int]], stamp: str, unverifiable_recall: float | None
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
    grid = [[m[t][p] for p in CLASSES] for t in CLASSES]
    fig, ax = plt.subplots(figsize=(7.5, 6))
    im = ax.imshow(grid, cmap="Oranges")
    ax.set_xticks(range(len(CLASSES)), CLASSES, rotation=20, ha="right")
    ax.set_yticks(range(len(CLASSES)), CLASSES)
    ax.set_xlabel("Predicted verdict")
    ax.set_ylabel("True label (claim class)")
    ax.set_title(f"L2 verdict confusion matrix (claims) — {stamp}")
    vmax = max(max(row) for row in grid) or 1
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            ax.text(
                j,
                i,
                str(v),
                ha="center",
                va="center",
                color="white" if v > vmax * 0.6 else "black",
                fontsize=12,
            )
    fig.colorbar(im, ax=ax, label="Number of claims")
    if unverifiable_recall is not None:
        ax.annotate(
            f"Unverifiable recall: {unverifiable_recall:.1f}% (headline)",
            (0.5, -0.22),
            xycoords="axes fraction",
            ha="center",
            fontsize=11,
            bbox={"facecolor": "white", "edgecolor": "#b00020", "pad": 4},
        )
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--out", default="results/evals/l2")
    args = parser.parse_args()
    rng = random.Random(args.seed)
    claims = build_claims(rng, os.environ["DATABASE_URL_RO"])
    if args.limit:
        rng.shuffle(claims)
        claims = claims[: args.limit]
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records = evaluate(claims)
    m = confusion(records)
    metrics = class_metrics(m)
    unv = next(r for r in metrics if r["class"] == "Unverifiable")
    overall = round(100.0 * sum(r["correct"] for r in records) / len(records), 1)

    (out / f"eval03_l2-predictions_{stamp}.json").write_text(
        json.dumps(records, indent=2, default=str)
    )
    with (out / f"eval03_l2-confusion-matrix_{stamp}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["true\\predicted", *CLASSES])
        for t in CLASSES:
            w.writerow([t, *(m[t][p] for p in CLASSES)])
    with (out / f"eval04_l2-class-metrics_{stamp}.csv").open("w", newline="") as f:
        dw = csv.DictWriter(f, fieldnames=list(metrics[0].keys()))
        dw.writeheader()
        dw.writerows(metrics)
    fig_dir = out.parent.parent / "figures" / "l2"
    fig_dir.mkdir(parents=True, exist_ok=True)
    write_figure(fig_dir / f"fig02_l2-confusion-matrix_{stamp}.png", m, stamp, unv["recall_pct"])

    by_source: dict[str, list[bool]] = defaultdict(list)
    for r in records:
        by_source[r["source"]].append(r["correct"])
    lines = [
        f"L2 verdict accuracy — {stamp}",
        f"models: {os.environ.get('SQL_MODEL')} / {os.environ.get('CHAT_MODEL')}",
        f"claims: {len(records)}  overall accuracy: {overall}%",
        f"HEADLINE Unverifiable recall: {unv['recall_pct']}%  (precision {unv['precision_pct']}%)",
        "",
        "per class:",
        *(
            f"  {r['class']:13s} n={r['support']:3d}  recall {r['recall_pct']}%  "
            f"precision {r['precision_pct']}%"
            for r in metrics
        ),
        "",
        "by source:",
        *(f"  {s:15s} {sum(v)}/{len(v)}" for s, v in by_source.items()),
        "",
        "confusion (rows=true, cols=predicted): " + ", ".join(CLASSES),
        *(f"  {t:13s} " + " ".join(f"{m[t][p]:3d}" for p in CLASSES) for t in CLASSES),
        "",
        "intent misses (claim not routed to claim mode): "
        + str(
            Counter(
                r["label"]
                for r in records
                if not r["intent_as_claim"] and r["source"] == "templated"
            )
        ),
    ]
    (out / f"summary_l2_{stamp}.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
