"""Templates render with sampled values, unverifiable SQL is dropped, splits hold templates out."""

from __future__ import annotations

import random

from askindia_agents.executor import QueryResult, SQLError, SQLErrorKind
from askindia_training.factory import (
    Sampler,
    Template,
    assign_splits,
    generate,
    load_templates,
    render,
    summary,
)


def test_bundled_templates_load_and_declare_all_placeholders() -> None:
    templates = load_templates()
    assert len(templates) >= 10
    assert all(t.questions and t.sql for t in templates)


def test_render_substitutes_and_escapes() -> None:
    t = Template(
        "d:x",
        "d",
        "filter",
        ("Population of {state}?",),
        "SELECT 1 FROM data.t WHERE name = '{state}'",
        {"state": Sampler("list", values=("D'ARCY",))},
    )
    q, sql = render(t, {"state": "D'ARCY"}, random.Random(0))
    assert q == "Population of D'Arcy?" and "name = 'D''ARCY'" in sql


def test_generate_keeps_only_verified_pairs() -> None:
    t = Template(
        "d:x",
        "d",
        "filter",
        ("Q {v}",),
        "SELECT 1 AS one FROM data.t WHERE v = '{v}'",
        {"v": Sampler("list", values=("good", "empty", "bad"))},
    )

    def execute(sql: str) -> QueryResult:
        if "'empty'" in sql:
            raise SQLError(SQLErrorKind.EMPTY_RESULT, "no rows")
        if "'bad'" in sql:
            raise SQLError(SQLErrorKind.BAD_COLUMN, "boom")
        return QueryResult(sql=sql, columns=("one",), rows=[{"one": 1}])

    pairs, dropped = generate([t], fetch=lambda s, w: [], execute=execute, per_template=5, seed=1)
    assert [p.params["v"] for p in pairs] == ["good"]
    assert dropped["empty"] == 1 and dropped["error"] == 1
    assert pairs[0].sql.endswith("LIMIT 500")


def test_splits_hold_out_whole_templates() -> None:
    pairs = []
    for i in range(8):
        t = Template(
            f"d:t{i}",
            "d",
            "filter",
            ("Q {v}",),
            "SELECT 1 AS one FROM data.t WHERE v = '{v}'",
            {"v": Sampler("list", values=("a", "b", "c"))},
        )
        ps, _ = generate(
            [t],
            fetch=lambda s, w: [],
            execute=lambda sql: QueryResult(sql=sql, columns=("one",), rows=[{"one": 1}]),
            per_template=3,
            seed=i,
        )
        pairs.extend(ps)
    assign_splits(pairs, seed=3)
    by_template = {}
    for p in pairs:
        by_template.setdefault(p.template_id, set()).add(p.split)
    assert all(len(s) == 1 for s in by_template.values())
    assert set(summary(pairs)["by_split"]) >= {"train", "test"}
