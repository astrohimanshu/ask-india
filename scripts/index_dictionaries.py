"""Embed every data dictionary under askindia_agents/dictionaries and store it in rag.chunks."""

from __future__ import annotations

import os
import sys

from askindia_agents.embedder import FastEmbedEmbedder
from askindia_agents.indexer import index_all


def main() -> int:
    counts = index_all(os.environ["DATABASE_URL"], FastEmbedEmbedder())
    for dataset, n in counts.items():
        print(f"{dataset}: {n} chunks")
    return 0 if counts else 1


if __name__ == "__main__":
    sys.exit(main())
