"""Run the init SQL files against a database without psql.

Emulates the two psql features the files rely on: ``\\set`` lines are ignored and ``:'name'``
variables are substituted as properly quoted literals. Used for managed databases from
machines that have psycopg but no psql client.

    uv run scripts/db/apply_sql.py "$ADMIN_DSN" scripts/db/sql/init_db.sql app_pw=... ro_pw=...
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg
from psycopg import sql


def render(text: str, variables: dict[str, str]) -> str:
    lines = [line for line in text.splitlines() if not line.startswith("\\")]
    body = "\n".join(lines)

    def quote(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise KeyError(f"psql variable :{name!r} not provided")
        return sql.Literal(variables[name]).as_string(None)

    return re.sub(r":'([a-zA-Z_][a-zA-Z0-9_]*)'", quote, body)


def main() -> int:
    dsn, path, *pairs = sys.argv[1:]
    variables = dict(p.split("=", 1) for p in pairs)
    statement = render(Path(path).read_text(), variables)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(statement)  # type: ignore[arg-type]
    print(f"applied {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
