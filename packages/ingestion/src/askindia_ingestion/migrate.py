"""Apply SQL migrations from scripts/db/sql/migrations in filename order, once each."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

DEFAULT_DIR = Path(__file__).resolve().parents[4] / "scripts" / "db" / "sql" / "migrations"


def apply_migrations(dsn: str, directory: Path = DEFAULT_DIR) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(dsn, application_name="askindia-migrate") as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta.schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r[0] for r in conn.execute("SELECT name FROM meta.schema_migrations")}
        for path in sorted(directory.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())  # type: ignore[arg-type,unused-ignore]
                conn.execute("INSERT INTO meta.schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied


if __name__ == "__main__":
    import os

    names = apply_migrations(os.environ["DATABASE_URL"])
    print("applied:", names or "nothing new")
    sys.exit(0)
