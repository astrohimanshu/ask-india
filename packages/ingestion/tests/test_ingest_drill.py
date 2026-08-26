"""The failure drill corrupts a parsed frame so validation quarantines it, never partially loads."""

import importlib.util
from pathlib import Path

from askindia_ingestion.contracts import DatasetSpec, LoadStatus
from askindia_ingestion.loaders.mock import MockLoader

spec_path = Path(__file__).resolve().parents[3] / "scripts" / "ingest.py"
mod_spec = importlib.util.spec_from_file_location("ingest_script", spec_path)
assert mod_spec and mod_spec.loader
ingest_script = importlib.util.module_from_spec(mod_spec)
mod_spec.loader.exec_module(ingest_script)


def test_broken_parse_is_quarantined(spec: DatasetSpec, good_csv: bytes) -> None:
    loader = MockLoader(spec, good_csv)
    loader.parse = ingest_script._broken_parse(loader.parse)  # type: ignore[method-assign]
    calls: list[str] = []
    result = loader.run(lambda s, f, v, r: calls.append(v) or len(f))
    assert result.status is LoadStatus.QUARANTINED
    assert calls == []
    assert result.validation is not None and result.validation.failures[0].name == "columns_present"
