"""Embed dictionary chunks and store them in rag.chunks (application role; not agent code)."""

from __future__ import annotations

from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from askindia_agents.dictionary import (
    DICTIONARY_DIR,
    Dictionary,
    chunk_dictionary,
    load_all,
    metadata_json,
)
from askindia_agents.embedder import Embedder


def index_dictionary(conn: psycopg.Connection[object], d: Dictionary, embedder: Embedder) -> int:
    chunks = chunk_dictionary(d)
    vectors = embedder.embed([c.content for c in chunks])
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM rag.chunks WHERE dataset = %s", (d.dataset,))
        for chunk, vec in zip(chunks, vectors, strict=True):
            cur.execute(
                "INSERT INTO rag.chunks"
                " (dataset, kind, title, content, metadata, embedding, content_sha)"
                " VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)",
                (
                    chunk.dataset,
                    chunk.kind,
                    chunk.title,
                    chunk.content,
                    metadata_json(chunk),
                    vec,
                    chunk.sha,
                ),
            )
    return len(chunks)


def index_all(dsn: str, embedder: Embedder, directory: Path = DICTIONARY_DIR) -> dict[str, int]:
    counts: dict[str, int] = {}
    with psycopg.connect(dsn, application_name="askindia-index") as conn:
        register_vector(conn)
        for d in load_all(directory):
            counts[d.dataset] = index_dictionary(conn, d, embedder)
    return counts
