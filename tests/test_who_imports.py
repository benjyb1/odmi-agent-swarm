"""Importing any who_speech module must not pull a heavy optional dependency
(docling, lancedb, sentence-transformers, mcp, openai). Those load lazily at
use, so the package imports cleanly in an environment that has only the light
deps. This guards against an accidental top-level import creeping back in.
"""
from __future__ import annotations

import importlib

import pytest

LIGHT_MODULES = [
    "who_speech.config",
    "who_speech.countries",
    "who_speech.models",
    "who_speech.render",
    "who_speech.llm",
    "who_speech.faithfulness",
    "who_speech.build",
    "who_speech.server",
    "who_speech.swarm",
    "who_speech.search",
    "who_speech.index",
    "who_speech.extract",
]

HEAVY = ("docling", "lancedb", "sentence_transformers", "mcp", "openai")


@pytest.mark.parametrize("name", LIGHT_MODULES)
def test_module_imports_without_heavy_dependencies(name):
    import sys

    before = set(sys.modules)
    importlib.import_module(name)
    newly = set(sys.modules) - before
    leaked = [h for h in HEAVY if any(m == h or m.startswith(h + ".") for m in newly)]
    assert not leaked, f"{name} imported heavy dependency at module load: {leaked}"
