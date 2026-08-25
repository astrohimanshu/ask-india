"""Static admission control for model-generated SQL.

Model output is untrusted. Before anything reaches the database it must parse as exactly one
statement, that statement must be a SELECT (a WITH ... SELECT is fine), it may only touch the
schemas the read-only role can see, and it gets a LIMIT if it does not carry one. Everything
else is rejected here, before the second line of defence (the read-only database role) is
ever consulted.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

ALLOWED_SCHEMAS: frozenset[str] = frozenset({"data", "rag"})
# Functions that have side effects, sleep, or read files/settings. Rejected regardless of role.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "set_config",
        "current_setting",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "lo_import",
        "lo_export",
        "dblink",
        "dblink_exec",
        "pg_notify",
        "nextval",
        "setval",
        "txid_current",
    }
)


_WRITE_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Create",
    "Drop",
    "Alter",
    "Command",
    "Merge",
    "Transaction",
    "Commit",
    "Rollback",
    "Set",
    "Grant",
    "Copy",
    "Lock",
    "TruncateTable",
    "Use",
    "Cache",
    "Uncache",
    "Refresh",
    "Analyze",
    "Vacuum",
    "Kill",
    "Execute",
    "Prepare",
)
WRITE_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, n) for n in _WRITE_NODE_NAMES if hasattr(exp, n)
)


class SQLRejectedError(ValueError):
    """The statement failed admission control. The message is safe to show to a user."""


@dataclass(frozen=True)
class AdmittedSQL:
    """A statement that passed the guard, re-rendered from the AST with a LIMIT applied."""

    sql: str
    tables: tuple[str, ...]
    limit_injected: bool


def _qualified_name(table: exp.Table) -> str:
    return f"{table.db}.{table.name}" if table.db else table.name


def admit(sql: str, *, row_limit: int = 500) -> AdmittedSQL:
    """Validate ``sql`` and return the sanitised statement, or raise :class:`SQLRejectedError`."""
    if not sql or not sql.strip():
        raise SQLRejectedError("empty statement")

    try:
        statements = sqlglot.parse(sql, read="postgres")
    except ParseError as e:
        raise SQLRejectedError(f"could not parse SQL: {e}") from e

    parsed = [s for s in statements if s is not None]
    if len(parsed) != 1:
        raise SQLRejectedError(f"exactly one statement is allowed, got {len(parsed)}")
    tree = parsed[0]
    assert isinstance(tree, exp.Expression)

    if not isinstance(tree, exp.Select | exp.Union):
        raise SQLRejectedError(f"only SELECT statements are allowed, got {tree.key.upper()}")

    # Reject any write, DDL, or utility node hiding anywhere in the tree (e.g. inside a CTE).
    for node in tree.walk():
        if isinstance(node, WRITE_NODES):
            raise SQLRejectedError(f"{node.key.upper()} is not allowed")
        if isinstance(node, exp.Into):
            raise SQLRejectedError("SELECT INTO is not allowed")
        if isinstance(node, exp.Anonymous | exp.Func):
            name = (node.name or node.sql_name()).lower()
            if name in FORBIDDEN_FUNCTIONS:
                raise SQLRejectedError(f"function {name}() is not allowed")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables: list[str] = []
    for table in tree.find_all(exp.Table):
        if not table.name:
            continue
        if not table.db and table.name.lower() in cte_names:
            continue
        schema = (table.db or "data").lower()
        if schema not in ALLOWED_SCHEMAS:
            raise SQLRejectedError(f"schema {schema!r} is not queryable")
        if table.catalog:
            raise SQLRejectedError("cross-database references are not allowed")
        tables.append(f"{schema}.{table.name}")
    if not tables:
        raise SQLRejectedError("statement does not read from any table")

    limit_injected = False
    outer = tree
    if outer.args.get("limit") is None:
        outer = outer.limit(row_limit)
        limit_injected = True
    else:
        literal = outer.args["limit"].expression
        if isinstance(literal, exp.Literal) and literal.is_int and int(literal.this) > row_limit:
            outer = outer.limit(row_limit)
            limit_injected = True

    return AdmittedSQL(
        sql=outer.sql(dialect="postgres"),
        tables=tuple(dict.fromkeys(tables)),
        limit_injected=limit_injected,
    )
