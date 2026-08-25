"""apply_sql renders psql variables as safe literals and drops backslash commands."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "apply_sql", Path(__file__).resolve().parents[3] / "scripts" / "db" / "apply_sql.py"
)
assert spec and spec.loader
apply_sql = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apply_sql)


def test_render_substitutes_and_quotes() -> None:
    out = apply_sql.render(
        "\\set ON_ERROR_STOP on\nCREATE ROLE r LOGIN PASSWORD :'pw';", {"pw": "a'b"}
    )
    assert out == "CREATE ROLE r LOGIN PASSWORD 'a''b';"


def test_render_fails_on_missing_variable() -> None:
    try:
        apply_sql.render("SELECT :'missing';", {})
    except KeyError as e:
        assert "missing" in str(e)
    else:
        raise AssertionError("expected KeyError")
