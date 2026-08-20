"""Execution-verify every exemplar SQL in the data dictionaries as the read-only role.

An exemplar that fails to parse, is rejected by the guard, errors, or returns no rows fails the
check, because exemplars are the retrieval corpus the SQL generator learns from.
"""

from __future__ import annotations

import os
import sys

from askindia_agents.dictionary import load_all
from askindia_agents.executor import SQLError, execute_readonly
from askindia_agents.sqlguard import SQLRejectedError, admit


def main() -> int:
    dsn = os.environ["DATABASE_URL_RO"]
    failures = 0
    for d in load_all():
        for ex in d.exemplars:
            try:
                result = execute_readonly(admit(ex.sql), dsn=dsn)
                first = {k: result.rows[0][k] for k in result.columns} if result.rows else {}
                print(f"ok    {d.dataset:26s} {result.row_count:4d} rows  {ex.question[:60]}")
                print(f"      -> {first}")
            except (SQLRejectedError, SQLError) as e:
                failures += 1
                print(f"FAIL  {d.dataset:26s} {ex.question[:60]}  -> {e}")
    print(f"\n{failures} failing exemplar(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
