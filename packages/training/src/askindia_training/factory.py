"""Training-data factory: templated (question, SQL) pairs, filled with real values sampled from
the database, execution-verified as the read-only role, and split with held-out stratification.

A template is a question pattern and a SQL pattern sharing placeholders. Each placeholder is
bound to a sampler: distinct values of a column, a year inside the dataset's coverage, or a fixed
list. Every rendered SQL must be admitted by the guard and return rows, or the pair is dropped;
nothing reaches the training set that the database did not confirm.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from askindia_agents.executor import QueryResult, SQLError, execute_readonly
from askindia_agents.sqlguard import SQLRejectedError, admit

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


@dataclass(frozen=True)
class Sampler:
    kind: str  # column | years | list
    source: str | None = None  # "table.column" for column
    values: tuple[str, ...] = ()
    start: int = 0
    end: int = 0
    where: str | None = None


@dataclass(frozen=True)
class Template:
    id: str
    dataset: str
    complexity: str
    questions: tuple[str, ...]
    sql: str
    params: dict[str, Sampler]


@dataclass
class Pair:
    id: str
    dataset: str
    complexity: str
    template_id: str
    question: str
    sql: str
    params: dict[str, str]
    row_count: int
    split: str = "train"
    source: str = "template"

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


def load_templates(directory: Path = TEMPLATE_DIR) -> list[Template]:
    out: list[Template] = []
    for path in sorted(directory.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        for t in doc["templates"]:
            params = {
                name: Sampler(
                    kind=spec["kind"],
                    source=spec.get("source"),
                    values=tuple(str(v) for v in spec.get("values", [])),
                    start=int(spec.get("start", 0)),
                    end=int(spec.get("end", 0)),
                    where=spec.get("where"),
                )
                for name, spec in (t.get("params") or {}).items()
            }
            questions = tuple(
                t["questions"] if isinstance(t["questions"], list) else [t["questions"]]
            )
            tmpl = Template(
                id=f"{doc['dataset']}:{t['id']}",
                dataset=doc["dataset"],
                complexity=t["complexity"],
                questions=questions,
                sql=t["sql"].strip(),
                params=params,
            )
            missing = set(_PLACEHOLDER.findall(tmpl.sql)) | {
                p for q in questions for p in _PLACEHOLDER.findall(q)
            }
            missing -= set(params)
            if missing:
                raise ValueError(f"{tmpl.id}: placeholders without samplers: {sorted(missing)}")
            out.append(tmpl)
    return out


ValueFetcher = Callable[[str, str | None], list[str]]  # (table.column, where) -> distinct values


def db_value_fetcher(dsn_ro: str, *, limit: int = 200) -> ValueFetcher:
    def fetch(source: str, where: str | None) -> list[str]:
        table, column = source.rsplit(".", 1)
        sql = f"SELECT DISTINCT {column} AS v FROM {table}"
        if where:
            sql += f" WHERE {where}"
        sql += f" ORDER BY v LIMIT {limit}"
        result = execute_readonly(admit(sql, row_limit=limit), dsn=dsn_ro)
        return [str(r["v"]) for r in result.rows if r["v"] is not None]

    return fetch


def sample_values(sampler: Sampler, fetch: ValueFetcher, rng: random.Random, n: int) -> list[str]:
    if sampler.kind == "list":
        pool = list(sampler.values)
    elif sampler.kind == "years":
        pool = [str(y) for y in range(sampler.start, sampler.end + 1)]
    elif sampler.kind == "column":
        assert sampler.source
        pool = fetch(sampler.source, sampler.where)
    else:
        raise ValueError(f"unknown sampler kind {sampler.kind}")
    if not pool:
        return []
    rng.shuffle(pool)
    return pool[:n]


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def render(template: Template, params: dict[str, str], rng: random.Random) -> tuple[str, str]:
    question = rng.choice(template.questions)
    sql = template.sql
    for name, value in params.items():
        # The SQL keeps the value exactly as stored; the question reads like a person wrote it.
        shown = value.title() if value.isupper() and len(value) > 3 else value
        question = question.replace("{" + name + "}", shown)
        sql = sql.replace("{" + name + "}", _sql_literal(value))
    return question, sql


def generate(
    templates: Iterable[Template],
    *,
    fetch: ValueFetcher,
    execute: Callable[[str], QueryResult],
    per_template: int = 12,
    seed: int = 0,
) -> tuple[list[Pair], dict[str, int]]:
    """Render up to ``per_template`` verified pairs per template; returns pairs and drop counts."""
    rng = random.Random(seed)
    pairs: list[Pair] = []
    dropped = {"rejected": 0, "error": 0, "empty": 0, "no_values": 0}
    for t in templates:
        combos = _combinations(t, fetch, rng, per_template * 3)
        if not combos:
            dropped["no_values"] += 1
            continue
        kept = 0
        for params in combos:
            if kept >= per_template:
                break
            question, sql = render(t, params, rng)
            try:
                admitted = admit(sql)
                result = execute(admitted.sql)
            except SQLRejectedError:
                dropped["rejected"] += 1
                continue
            except SQLError as e:
                dropped["empty" if e.kind.value == "empty_result" else "error"] += 1
                continue
            pid = hashlib.sha1(f"{t.id}|{sql}".encode()).hexdigest()[:12]
            pairs.append(
                Pair(
                    pid,
                    t.dataset,
                    t.complexity,
                    t.id,
                    question,
                    admitted.sql,
                    params,
                    result.row_count,
                )
            )
            kept += 1
    return pairs, dropped


def _combinations(
    t: Template, fetch: ValueFetcher, rng: random.Random, n: int
) -> list[dict[str, str]]:
    if not t.params:
        return [{}]
    pools = {name: sample_values(s, fetch, rng, n) for name, s in t.params.items()}
    if any(not v for v in pools.values()):
        return []
    combos: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for _ in range(n * 4):
        combo = {name: rng.choice(pool) for name, pool in pools.items()}
        key = tuple(combo[k] for k in sorted(combo))
        if key in seen:
            continue
        seen.add(key)
        combos.append(combo)
        if len(combos) >= n:
            break
    return combos


def assign_splits(
    pairs: list[Pair], *, dev: float = 0.1, test: float = 0.15, seed: int = 0
) -> None:
    """Held-out by template: a template's pairs all land in one split, stratified per dataset."""
    rng = random.Random(seed)
    by_dataset: dict[str, list[str]] = {}
    for p in pairs:
        by_dataset.setdefault(p.dataset, [])
        if p.template_id not in by_dataset[p.dataset]:
            by_dataset[p.dataset].append(p.template_id)
    split_of: dict[str, str] = {}
    for templates in by_dataset.values():
        rng.shuffle(templates)
        n = len(templates)
        n_test = max(1, round(n * test)) if n >= 3 else 0
        n_dev = max(1, round(n * dev)) if n >= 4 else 0
        for i, tid in enumerate(templates):
            split_of[tid] = "test" if i < n_test else "dev" if i < n_test + n_dev else "train"
    for p in pairs:
        p.split = split_of[p.template_id]


def write_jsonl(pairs: list[Pair], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for p in pairs:
            f.write(p.to_json() + "\n")


def summary(pairs: list[Pair]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "total": len(pairs),
        "by_dataset": {},
        "by_complexity": {},
        "by_split": {},
    }
    for p in pairs:
        for key, val in (
            ("by_dataset", p.dataset),
            ("by_complexity", p.complexity),
            ("by_split", p.split),
        ):
            out[key][val] = out[key].get(val, 0) + 1
    return out


__all__ = [
    "Pair",
    "Sampler",
    "Template",
    "assign_splits",
    "db_value_fetcher",
    "field",
    "generate",
    "load_templates",
    "render",
    "summary",
    "write_jsonl",
]
