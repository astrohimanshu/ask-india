"""Build the training set: render, verify against the live database, split, write JSONL.

uv run python -m askindia_training.build_dataset --out results/training/pairs.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from askindia_agents.executor import execute_readonly
from askindia_agents.sqlguard import AdmittedSQL
from askindia_training.factory import (
    assign_splits,
    db_value_fetcher,
    generate,
    load_templates,
    summary,
    write_jsonl,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="results/training/pairs.jsonl")
    parser.add_argument("--per-template", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    dsn_ro = os.environ["DATABASE_URL_RO"]

    def execute(sql: str):  # type: ignore[no-untyped-def]
        return execute_readonly(AdmittedSQL(sql=sql, tables=(), limit_injected=False), dsn=dsn_ro)

    templates = load_templates()
    pairs, dropped = generate(
        templates,
        fetch=db_value_fetcher(dsn_ro),
        execute=execute,
        per_template=args.per_template,
        seed=args.seed,
    )
    assign_splits(pairs, seed=args.seed)
    out = Path(args.out)
    write_jsonl(pairs, out)
    report = {"templates": len(templates), "dropped": dropped, **summary(pairs)}
    out.with_suffix(".summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if pairs else 1


if __name__ == "__main__":
    sys.exit(main())
