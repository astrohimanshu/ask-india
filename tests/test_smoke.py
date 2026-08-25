"""Workspace wiring: every package imports and reports a version."""

import importlib

import pytest

PACKAGES = [
    "askindia_api",
    "askindia_agents",
    "askindia_ingestion",
    "askindia_evals",
    "askindia_training",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__version__ == "0.1.0"
