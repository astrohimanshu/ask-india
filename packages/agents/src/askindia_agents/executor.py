"""Executes admitted SQL as the read-only database role and returns typed results or errors.

This is the only code path that runs model-generated SQL. It never receives a raw string
from the model: callers pass an :class:`AdmittedSQL` produced by :mod:`askindia_agents.sqlguard`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import psycopg
from psycopg import errors as pgerr
from psycopg.rows import dict_row

from askindia_agents.sqlguard import AdmittedSQL


class SQLErrorKind(StrEnum):
    """Error taxonomy that drives targeted retry prompts."""

    BAD_COLUMN = "bad_column"
    BAD_TABLE = "bad_table"
    SYNTAX = "syntax"
    TIMEOUT = "timeout"
    PERMISSION = "permission"
    TOO_EXPENSIVE = "too_expensive"
    EMPTY_RESULT = "empty_result"
    OTHER = "other"


@dataclass(frozen=True)
class SQLError(Exception):
    kind: SQLErrorKind
    message: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"


@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: tuple[str, ...]
    rows: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: float = 0.0
    plan_cost: float | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _classify(e: psycopg.Error) -> SQLError:
    msg = (e.diag.message_primary if e.diag and e.diag.message_primary else str(e)).strip()
    if isinstance(e, pgerr.UndefinedColumn):
        return SQLError(SQLErrorKind.BAD_COLUMN, msg)
    if isinstance(e, pgerr.UndefinedTable):
        return SQLError(SQLErrorKind.BAD_TABLE, msg)
    if isinstance(e, pgerr.SyntaxError | pgerr.UndefinedFunction | pgerr.DatatypeMismatch):
        return SQLError(SQLErrorKind.SYNTAX, msg)
    if isinstance(e, pgerr.QueryCanceled):
        return SQLError(SQLErrorKind.TIMEOUT, "statement timed out")
    if isinstance(e, pgerr.InsufficientPrivilege | pgerr.ReadOnlySqlTransaction):
        return SQLError(SQLErrorKind.PERMISSION, msg)
    return SQLError(SQLErrorKind.OTHER, msg)


def _plan_cost(cur: psycopg.Cursor[Any], sql: str) -> float:
    cur.execute("EXPLAIN (FORMAT JSON) " + sql)
    row = cur.fetchone()
    plan = row["QUERY PLAN"][0]["Plan"] if row else {}
    return float(plan.get("Total Cost", 0.0))


def execute_readonly(
    admitted: AdmittedSQL,
    *,
    dsn: str,
    timeout_seconds: float = 10.0,
    max_cost: float | None = None,
) -> QueryResult:
    """Run an admitted statement as the read-only role.

    ``dsn`` must be the read-only role's connection string. Raises :class:`SQLError` with a
    classified kind on any failure, including an empty result set.
    """
    timeout_ms = int(timeout_seconds * 1000)
    started = time.perf_counter()
    try:
        with psycopg.connect(
            dsn,
            connect_timeout=5,
            options=f"-c statement_timeout={timeout_ms} -c default_transaction_read_only=on",
            row_factory=dict_row,
            application_name="askindia-agent",
        ) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cost = _plan_cost(cur, admitted.sql)
                if max_cost is not None and cost > max_cost:
                    raise SQLError(
                        SQLErrorKind.TOO_EXPENSIVE,
                        f"estimated plan cost {cost:.0f} exceeds ceiling {max_cost:.0f}",
                    )
                cur.execute(admitted.sql)
                columns = tuple(d.name for d in cur.description or ())
                rows = cur.fetchall()
    except psycopg.Error as e:
        raise _classify(e) from e
    elapsed = (time.perf_counter() - started) * 1000
    if not rows:
        raise SQLError(SQLErrorKind.EMPTY_RESULT, "query returned no rows")
    return QueryResult(
        sql=admitted.sql, columns=columns, rows=rows, elapsed_ms=elapsed, plan_cost=cost
    )
