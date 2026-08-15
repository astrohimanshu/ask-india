"""Text embeddings for retrieval. One real backend (fastembed, CPU, ONNX) and one for tests."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

EMBEDDING_DIM = 384
MODEL_NAME = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """bge-small via fastembed; same model in every environment so retrieval is reproducible."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(list(texts))]


_TOKEN = re.compile(r"[a-z0-9_]+")


class HashEmbedder:
    """Deterministic bag-of-tokens embedding: overlapping vocabulary → cosine similarity.

    Used in tests so retrieval behaviour can be checked without downloading a model.
    """

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * EMBEDDING_DIM
            for token in _TOKEN.findall(text.lower()):
                h = int(hashlib.blake2b(token.encode(), digest_size=4).hexdigest(), 16)
                vec[h % EMBEDDING_DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out
