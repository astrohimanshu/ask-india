"""Print which dataset the retriever ranks first for a set of probe questions (manual check)."""

from __future__ import annotations

import os
import sys

from askindia_agents.embedder import FastEmbedEmbedder
from askindia_agents.retriever import SchemaRetriever

PROBES = [
    "How many people live in Bihar?",
    "Which state has the lowest literacy rate?",
    "sex ratio of Punjab",
    "How much rain did Mumbai get last monsoon?",
    "Was 2023 a drought year for Marathwada?",
    "petrol price today in Delhi",
    "how much has diesel become costlier since 2017",
    "What is the urban population share of Tamil Nadu?",
    "wettest year in Assam",
    "average fuel price in Kolkata in 2021",
]


def main() -> int:
    retriever = SchemaRetriever(os.environ["DATABASE_URL_RO"], FastEmbedEmbedder())
    for q in [*PROBES, *sys.argv[1:]]:
        r = retriever.retrieve(q)
        kinds = ",".join(f"{c.kind[0]}" for c in r.chunks[:6])
        print(f"{r.datasets[0] if r.datasets else '-':26s} {kinds:8s} {q}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
