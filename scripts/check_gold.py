"""Execute every gold SQL as the read-only role; each must be admitted and return rows."""

from __future__ import annotations

import os
import sys

from askindia_agents.executor import SQLError, execute_readonly
from askindia_agents.sqlguard import SQLRejectedError, admit
from askindia_evals.l1 import load_gold


def main() -> int:
    dsn = os.environ["DATABASE_URL_RO"]
    failures = 0
    for item in load_gold():
        try:
            result = execute_readonly(admit(item["sql"]), dsn=dsn)
            first = {k: result.rows[0][k] for k in result.columns}
            print(f"ok    {item['id']:8s} {result.row_count:3d} rows  {first}")
        except (SQLRejectedError, SQLError) as e:
            failures += 1
            print(f"FAIL  {item['id']:8s} {e}")
    print(f"\n{failures} failing gold item(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
