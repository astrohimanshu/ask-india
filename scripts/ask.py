"""Ask a question through the full agent graph from the command line.

uv run scripts/ask.py "Which state had the highest literacy rate in 2011?"
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from askindia_agents.graph import run_question


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--json", action="store_true", help="print the full final answer as JSON")
    args = parser.parse_args()
    started = time.perf_counter()
    final = run_question(args.question)
    elapsed = time.perf_counter() - started
    if args.json:
        print(json.dumps(final, indent=2, default=str))
        return 0
    print(f"status   : {final['status']}  ({elapsed:.1f}s, attempts={final.get('attempts')})")
    print(f"answer   : {final['prose']}")
    if final.get("sql"):
        print(f"sql      : {final['sql']}")
    if final.get("citation"):
        c = final["citation"]
        print(f"dataset  : {c['dataset']} version={c['dataset_version']} coverage={c['coverage']}")
    if final.get("rows"):
        cols = final["columns"]
        print("rows     : " + " | ".join(cols))
        for row in final["rows"][:10]:
            print("           " + " | ".join(str(row[c]) for c in cols))
    for a in final.get("assumptions", []):
        print(f"assumes  : {a}")
    for cv in final.get("caveats", []):
        print(f"caveat   : {cv}")
    for e in final.get("errors", []):
        print(f"error    : attempt {e['attempt']} {e['kind']}: {e['message'][:120]}")
    if final.get("guard"):
        print(f"guard    : {final['guard']}")
    return 0 if final["status"] == "answered" else 1


if __name__ == "__main__":
    sys.exit(main())
