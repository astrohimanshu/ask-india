"""HTTP fetching shared by every network loader. Government hosts are slow and picky."""

# Bundling helpers for sources that publish many files per dataset live in bundle.py.

from __future__ import annotations

import httpx

from askindia_ingestion.contracts import RawArtifact

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AskIndia/0.1 (+https://github.com/astrohimanshu/ask-india)"
)


def fetch(
    dataset: str, url: str, *, timeout: float = 120.0, verify_tls: bool = True
) -> RawArtifact:
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
        verify=verify_tls,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return RawArtifact.from_bytes(
            dataset, str(response.url), response.content, response.headers.get("content-type")
        )
