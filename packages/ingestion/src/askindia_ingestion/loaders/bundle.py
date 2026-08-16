"""Bundle several fetched files into one RawArtifact (a zip in memory) so multi-file sources keep
the single-artifact snapshot and hash semantics of the contract."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable

from askindia_ingestion.contracts import RawArtifact


def bundle(dataset: str, source_url: str, files: Iterable[tuple[str, bytes]]) -> RawArtifact:
    """``files`` are (name, content) pairs; names must be unique and are stored in given order."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))  # deterministic hash
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content)
    return RawArtifact.from_bytes(dataset, source_url, buf.getvalue(), "application/zip")


def unbundle(raw: RawArtifact) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(raw.content)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}
