"""Admission control for model SQL: only a single SELECT over queryable schemas gets through."""

import pytest

from askindia_agents.sqlguard import SQLRejectedError, admit


def test_plain_select_is_admitted_with_limit() -> None:
    out = admit("SELECT airline, passengers_carried FROM dgca_airline_traffic")
    assert out.limit_injected
    assert out.sql.endswith("LIMIT 500")
    assert out.tables == ("data.dgca_airline_traffic",)


def test_explicit_data_schema_and_small_limit_kept() -> None:
    out = admit("SELECT * FROM data.dgca_airline_traffic LIMIT 10", row_limit=500)
    assert not out.limit_injected
    assert out.sql.endswith("LIMIT 10")


def test_oversized_limit_is_clamped() -> None:
    out = admit("SELECT * FROM dgca_airline_traffic LIMIT 100000", row_limit=500)
    assert out.limit_injected
    assert out.sql.endswith("LIMIT 500")


def test_cte_and_union_are_admitted() -> None:
    out = admit(
        "WITH q AS (SELECT airline, SUM(passengers_carried) AS pax FROM dgca_airline_traffic "
        "GROUP BY airline) SELECT * FROM q UNION ALL SELECT 'total', SUM(pax) FROM q"
    )
    assert out.tables == ("data.dgca_airline_traffic",)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE dgca_airline_traffic",
        "INSERT INTO dgca_airline_traffic (airline) VALUES ('x')",
        "UPDATE dgca_airline_traffic SET airline = 'x'",
        "DELETE FROM dgca_airline_traffic",
        "TRUNCATE dgca_airline_traffic",
        "CREATE TABLE t (x int)",
        "ALTER TABLE dgca_airline_traffic ADD COLUMN x int",
        "GRANT ALL ON dgca_airline_traffic TO public",
        "EXPLAIN SELECT * FROM dgca_airline_traffic",
        "COPY dgca_airline_traffic TO '/tmp/x'",
        "SET statement_timeout = 0",
        "SELECT * FROM dgca_airline_traffic; DROP TABLE dgca_airline_traffic",
        "SELECT * INTO stolen FROM dgca_airline_traffic",
        "WITH d AS (DELETE FROM dgca_airline_traffic RETURNING *) SELECT * FROM d",
        "SELECT * FROM dgca_airline_traffic FOR UPDATE",
    ],
)
def test_non_select_and_writes_are_rejected(sql: str) -> None:
    with pytest.raises(SQLRejectedError):
        admit(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM meta.dataset_runs",
        "SELECT * FROM app.checkpoints",
        "SELECT * FROM pg_catalog.pg_roles",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM otherdb.data.dgca_airline_traffic",
    ],
)
def test_only_queryable_schemas(sql: str) -> None:
    with pytest.raises(SQLRejectedError, match=r"schema|cross-database"):
        admit(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(30), airline FROM dgca_airline_traffic",
        "SELECT current_setting('is_superuser'), airline FROM dgca_airline_traffic",
        "SELECT pg_read_file('/etc/passwd'), airline FROM dgca_airline_traffic",
    ],
)
def test_forbidden_functions(sql: str) -> None:
    with pytest.raises(SQLRejectedError, match="not allowed"):
        admit(sql)


@pytest.mark.parametrize("sql", ["", "   ", "SELECT 1", "SELEC * FROM x", "not sql at all"])
def test_garbage_and_tableless(sql: str) -> None:
    with pytest.raises(SQLRejectedError):
        admit(sql)
