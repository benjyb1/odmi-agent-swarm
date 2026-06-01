"""The snippet picker must degrade gracefully when the model emits invalid
JSON (e.g. unescaped inner quotes inside a passage), rather than crash the
whole search. A page we cannot parse a snippet from is dropped, exactly like
a page the picker returns no chunks for.
"""
from __future__ import annotations

from agents.tools import snippet_picker
from agents.tools.llm import StructuredOutputError


def test_pick_snippet_returns_empty_on_parse_failure(monkeypatch):
    def boom(**kwargs):
        raise StructuredOutputError("Invalid JSON: unescaped quote")

    monkeypatch.setattr(snippet_picker, "call_for_structured", boom)
    monkeypatch.setattr(snippet_picker, "ensure_prompt_version", lambda *a, **k: 1)

    chunks, usage = snippet_picker.pick_snippet(
        query="q", url="https://x.example", page_text="some page text",
    )
    assert chunks == []
    # A usage record is still returned so the caller's accounting holds.
    assert usage is not None
