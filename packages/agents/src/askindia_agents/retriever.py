"""Hybrid schema retrieval over rag.chunks: vector similarity fused with keyword rank.

Reads as the read-only role. Returns the dictionary material the SQL generator needs for the
datasets most likely to answer the question, ranked by reciprocal rank fusion of the two
searches so that an exact table or column name wins even when the embedding is unsure.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from askindia_agents.embedder import Embedder

RRF_K = 60
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


@dataclass(frozen=True)
class RetrievedChunk:
    id: int
    dataset: str
    kind: str
    title: str
    content: str
    metadata: dict[str, Any]
    score: float
    vector_rank: int | None
    keyword_rank: int | None


@dataclass
class RetrievalResult:
    question: str
    chunks: list[RetrievedChunk]
    datasets: list[str] = field(default_factory=list)  # ranked, best first

    def for_dataset(self, dataset: str) -> list[RetrievedChunk]:
        return [c for c in self.chunks if c.dataset == dataset]

    def context_text(self, *, max_datasets: int = 2) -> str:
        """Render the retrieved material as prompt context, grouped by dataset."""
        parts: list[str] = []
        for ds in self.datasets[:max_datasets]:
            table = [c for c in self.for_dataset(ds) if c.kind == "table"]
            columns = [c for c in self.for_dataset(ds) if c.kind == "column"]
            caveats = [c for c in self.for_dataset(ds) if c.kind == "caveat"]
            exemplars = [c for c in self.for_dataset(ds) if c.kind == "exemplar"]
            parts.append(f"### Dataset {ds}")
            parts.extend(c.content for c in table)
            if columns:
                parts.append(
                    "Relevant column notes:\n" + "\n".join(f"- {c.content}" for c in columns)
                )
            if caveats:
                parts.append("Caveats:\n" + "\n".join(f"- {c.content}" for c in caveats))
            if exemplars:
                parts.append("Examples:\n" + "\n\n".join(c.content for c in exemplars))
        return "\n\n".join(parts)


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (k + rank)
    return dict(scores)


def keyword_terms(question: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(question) if len(w) > 2]


class SchemaRetriever:
    def __init__(
        self, dsn_ro: str, embedder: Embedder, *, k_vector: int = 20, k_keyword: int = 20
    ) -> None:
        self.dsn_ro = dsn_ro
        self.embedder = embedder
        self.k_vector = k_vector
        self.k_keyword = k_keyword

    def retrieve(
        self,
        question: str,
        *,
        top_chunks: int = 12,
        top_datasets: int = 3,
        only_dataset: str | None = None,
    ) -> RetrievalResult:
        """``only_dataset`` restricts both searches to one dataset (used when triage has already
        decided which dataset settles a claim)."""
        vector = self.embedder.embed([question])[0]
        terms = keyword_terms(question)
        ds_filter = "" if only_dataset is None else " AND dataset = %(only)s"
        with psycopg.connect(
            self.dsn_ro, application_name="askindia-retriever", row_factory=dict_row
        ) as conn:
            register_vector(conn)
            conn.read_only = True
            vec_rows = conn.execute(
                "SELECT id FROM rag.chunks WHERE true"
                + ds_filter
                + " ORDER BY embedding <=> %(vec)s::vector LIMIT %(k)s",
                {"vec": vector, "k": self.k_vector, "only": only_dataset},
            ).fetchall()
            kw_rows = conn.execute(
                """
                SELECT id,
                       ts_rank(tsv, plainto_tsquery('english', %(q)s))
                       + 0.5 * (SELECT count(*) FROM unnest(%(terms)s::text[]) t
                                WHERE title ILIKE '%%' || t || '%%')
                       AS rank
                FROM rag.chunks
                WHERE (tsv @@ plainto_tsquery('english', %(q)s)
                   OR EXISTS (SELECT 1 FROM unnest(%(terms)s::text[]) t
                              WHERE title ILIKE '%%' || t || '%%'))"""
                + ds_filter
                + """
                ORDER BY rank DESC
                LIMIT %(k)s
                """,
                {"q": question, "terms": terms, "k": self.k_keyword, "only": only_dataset},
            ).fetchall()
            vec_ids = [int(r["id"]) for r in vec_rows]
            kw_ids = [int(r["id"]) for r in kw_rows]
            fused = rrf([vec_ids, kw_ids])
            if not fused:
                return RetrievalResult(question=question, chunks=[])
            ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_chunks]
            ids = [cid for cid, _ in ordered]
            rows = conn.execute(
                "SELECT id, dataset, kind, title, content, metadata FROM rag.chunks"
                " WHERE id = ANY(%s)",
                (ids,),
            ).fetchall()
        by_id = {int(r["id"]): r for r in rows}
        chunks = [
            RetrievedChunk(
                id=cid,
                dataset=by_id[cid]["dataset"],
                kind=by_id[cid]["kind"],
                title=by_id[cid]["title"],
                content=by_id[cid]["content"],
                metadata=by_id[cid]["metadata"],
                score=score,
                vector_rank=(vec_ids.index(cid) + 1) if cid in vec_ids else None,
                keyword_rank=(kw_ids.index(cid) + 1) if cid in kw_ids else None,
            )
            for cid, score in ordered
            if cid in by_id
        ]
        ds_scores: dict[str, float] = defaultdict(float)
        for c in chunks:
            ds_scores[c.dataset] += c.score
        datasets = [d for d, _ in sorted(ds_scores.items(), key=lambda kv: kv[1], reverse=True)][
            :top_datasets
        ]
        # Always carry the table chunk of every ranked dataset so the generator sees full DDL.
        with psycopg.connect(
            self.dsn_ro, application_name="askindia-retriever", row_factory=dict_row
        ) as conn:
            have = {(c.dataset, c.kind) for c in chunks}
            missing = [d for d in datasets if (d, "table") not in have]
            if missing:
                extra = conn.execute(
                    "SELECT id, dataset, kind, title, content, metadata FROM rag.chunks"
                    " WHERE kind = 'table' AND dataset = ANY(%s)",
                    (missing,),
                ).fetchall()
                chunks.extend(
                    RetrievedChunk(
                        int(r["id"]),
                        r["dataset"],
                        r["kind"],
                        r["title"],
                        r["content"],
                        r["metadata"],
                        0.0,
                        None,
                        None,
                    )
                    for r in extra
                )
        return RetrievalResult(question=question, chunks=chunks, datasets=datasets)
