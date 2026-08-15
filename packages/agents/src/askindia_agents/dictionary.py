"""Data dictionaries: the human-written description of each dataset that the retriever indexes.

One YAML file per dataset under ``dictionaries/``. The chunker turns a dictionary into
retrieval units — one for the table, one per column, one per caveat, one per exemplar
(question, SQL) pair — so a question can land on the right table by any of those routes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DICTIONARY_DIR = Path(__file__).resolve().parent / "dictionaries"


class ColumnDoc(BaseModel):
    name: str
    type: str
    description: str
    unit: str | None = None
    notes: str | None = None
    values: list[str] | None = Field(default=None, description="notable categorical values")


class Exemplar(BaseModel):
    question: str
    sql: str


class Dictionary(BaseModel):
    dataset: str
    table: str = Field(pattern=r"^data\.[a-z][a-z0-9_]+$")
    title: str
    purpose: str
    source: str
    cadence: str
    coverage: str
    columns: list[ColumnDoc]
    caveats: list[str] = Field(default_factory=list)
    exemplars: list[Exemplar] = Field(default_factory=list)

    def ddl_summary(self) -> str:
        cols = ", ".join(f"{c.name} {c.type}" for c in self.columns)
        return f"{self.table}({cols})"


@dataclass(frozen=True)
class Chunk:
    dataset: str
    kind: str
    title: str
    content: str
    metadata: dict[str, Any]

    @property
    def sha(self) -> str:
        return hashlib.sha256(f"{self.kind}|{self.title}|{self.content}".encode()).hexdigest()


def load_dictionary(path: Path) -> Dictionary:
    return Dictionary.model_validate(yaml.safe_load(path.read_text()))


def load_all(directory: Path = DICTIONARY_DIR) -> list[Dictionary]:
    return [load_dictionary(p) for p in sorted(directory.glob("*.yaml"))]


def chunk_dictionary(d: Dictionary) -> list[Chunk]:
    chunks: list[Chunk] = []
    column_lines = "\n".join(
        f"- {c.name} ({c.type}{', ' + c.unit if c.unit else ''}): {c.description}"
        for c in d.columns
    )
    chunks.append(
        Chunk(
            d.dataset,
            "table",
            d.table,
            f"{d.title}. {d.purpose}\nSource: {d.source}. Cadence: {d.cadence}. "
            f"Coverage: {d.coverage}.\nColumns:\n{column_lines}",
            {"table": d.table, "ddl": d.ddl_summary()},
        )
    )
    for c in d.columns:
        text = f"Column {c.name} of {d.table}: {c.description}"
        if c.unit:
            text += f" Unit: {c.unit}."
        if c.notes:
            text += f" {c.notes}"
        if c.values:
            text += " Values include: " + ", ".join(c.values) + "."
        chunks.append(
            Chunk(
                d.dataset,
                "column",
                f"{d.table}.{c.name}",
                text,
                {"table": d.table, "column": c.name},
            )
        )
    for caveat in d.caveats:
        chunks.append(Chunk(d.dataset, "caveat", d.table, caveat, {"table": d.table}))
    for ex in d.exemplars:
        chunks.append(
            Chunk(
                d.dataset,
                "exemplar",
                ex.question,
                f"Question: {ex.question}\nSQL: {ex.sql}",
                {"table": d.table, "question": ex.question, "sql": ex.sql},
            )
        )
    return chunks


def metadata_json(chunk: Chunk) -> str:
    return json.dumps(chunk.metadata, ensure_ascii=False)
