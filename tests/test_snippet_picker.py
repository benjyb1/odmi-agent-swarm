"""Tests for agents/tools/snippet_picker.py (tool module)."""

from __future__ import annotations

from typing import List

import pytest

from agents.models import LLMUsage
from agents.tools.snippet_picker import (
    PickedChunk,
    aggregate_score,
    aggregate_snippet,
    pick_snippet,
)

# Fake LLMUsage for monkeypatching

_FAKE_USAGE = LLMUsage(
    input_tokens=10,
    output_tokens=5,
    wall_clock_ms=123,
    model_version="claude-sonnet-4-6",
    condition_label="snippet_pick",
)


def _make_result(chunks: List[PickedChunk]):
    """Return a fake (parsed_output, usage) tuple matching call_for_structured."""
    from agents.tools.snippet_picker import _ChunksOut  # imported lazily after impl exists

    return _ChunksOut(chunks=chunks), _FAKE_USAGE


# pick_snippet: threshold logic


def test_top_chunk_above_threshold_returns_single(monkeypatch):
    """When chunks[0].score >= 0.7, only the top chunk is returned."""
    chunks = [
        PickedChunk(text="Best passage about open data.", score=0.9),
        PickedChunk(text="Weaker passage.", score=0.4),
    ]

    monkeypatch.setattr(
        "agents.tools.snippet_picker.call_for_structured",
        lambda **_: _make_result(chunks),
    )
    monkeypatch.setattr(
        "agents.tools.snippet_picker.ensure_prompt_version",
        lambda *args, **kwargs: 1,
    )

    result, usage = pick_snippet(
        query="open data policy",
        url="https://example.com",
        page_text="some content",
    )

    assert len(result) == 1
    assert result[0].score == 0.9


def test_top_chunk_below_threshold_returns_up_to_three(monkeypatch):
    """When chunks[0].score < 0.7, return up to three chunks."""
    chunks = [
        PickedChunk(text="Partial answer passage.", score=0.5),
        PickedChunk(text="Another partial passage.", score=0.4),
        PickedChunk(text="Tangential passage.", score=0.2),
    ]

    monkeypatch.setattr(
        "agents.tools.snippet_picker.call_for_structured",
        lambda **_: _make_result(chunks),
    )
    monkeypatch.setattr(
        "agents.tools.snippet_picker.ensure_prompt_version",
        lambda *args, **kwargs: 1,
    )

    result, usage = pick_snippet(
        query="open data portal",
        url="https://example.com",
        page_text="some content",
    )

    assert len(result) == 3
    assert result[0].score == 0.5
    assert result[1].score == 0.4
    assert result[2].score == 0.2


def test_empty_chunks_means_drop(monkeypatch):
    """When the LLM returns no chunks, pick_snippet returns ([], usage)."""
    monkeypatch.setattr(
        "agents.tools.snippet_picker.call_for_structured",
        lambda **_: _make_result([]),
    )
    monkeypatch.setattr(
        "agents.tools.snippet_picker.ensure_prompt_version",
        lambda *args, **kwargs: 1,
    )

    result, usage = pick_snippet(
        query="irrelevant query",
        url="https://example.com",
        page_text="page with no relevant content",
    )

    assert result == []
    assert isinstance(usage, LLMUsage)


# aggregate_snippet


def test_aggregate_snippet_joins_chunks():
    chunks = [
        PickedChunk(text="First passage.", score=0.9),
        PickedChunk(text="Second passage.", score=0.6),
        PickedChunk(text="Third passage.", score=0.3),
    ]
    result = aggregate_snippet(chunks)
    assert result == "First passage. ... Second passage. ... Third passage."


def test_aggregate_snippet_single_chunk():
    chunks = [PickedChunk(text="Only passage.", score=0.8)]
    result = aggregate_snippet(chunks)
    assert result == "Only passage."


def test_aggregate_snippet_empty():
    assert aggregate_snippet([]) == ""


# aggregate_score


def test_aggregate_score_is_top():
    """aggregate_score returns chunks[0].score, not the max."""
    chunks = [
        PickedChunk(text="First passage.", score=0.5),
        PickedChunk(text="Second passage.", score=0.9),  # higher, but not chosen
    ]
    result = aggregate_score(chunks)
    assert result == 0.5


def test_aggregate_score_empty():
    assert aggregate_score([]) is None


# PickedChunk: truncation validator


def test_picked_chunk_text_truncated_at_500():
    """Over-long chunks are silently truncated to MAX_CHUNK_CHARS chars."""
    from agents.tools.snippet_picker import MAX_CHUNK_CHARS

    long_text = "x" * 600
    chunk = PickedChunk(text=long_text, score=0.5)
    assert len(chunk.text) == MAX_CHUNK_CHARS


def test_picked_chunk_text_within_limit_unchanged():
    """Chunks within the limit are returned verbatim."""
    text = "Short passage about open data policy."
    chunk = PickedChunk(text=text, score=0.8)
    assert chunk.text == text
