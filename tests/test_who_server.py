"""The who_brief tool handler that Copilot Studio (or any MCP client) calls.

run_brief holds the contract with dependencies injected; the MCP wiring is a
thin wrapper. Tested with fakes, so no index, model or LLM is touched.
"""
from __future__ import annotations

import pytest

from who_speech import server
from who_speech.swarm import BriefingPack, BriefingPoint


def _pack_with_point():
    return BriefingPack(
        query="q",
        points=[BriefingPoint(
            point="WHO did X.", quote="A verbatim quote.", citation="C",
            iris_url="https://iris.who.int/handle/10665/1", page=2, confidence=0.7)],
        abstained=False, note="",
    )


def test_missing_index_returns_no_index_and_skips_orchestration():
    def must_not_run(question, retriever):
        raise AssertionError("orchestration must not run when the index is missing")

    out = server.run_brief(
        "France", "what has WHO done?", "bullets",
        retriever_factory=lambda db: object(),
        orchestrate_fn=must_not_run,
        render_fn=lambda pack, fmt: "x",
        index_exists=lambda db: False,
    )
    assert out["status"] == "no_index"
    assert out["mesh"] == "France"
    assert out["points"] == []


def test_ok_brief_serialises_points_and_rendered_text():
    seen = {}

    def retriever_factory(db_path):
        seen["db"] = db_path
        return "RETRIEVER"

    def orchestrate_fn(question, retriever):
        assert retriever == "RETRIEVER"
        return _pack_with_point()

    out = server.run_brief(
        "North Macedonia", "what?", "bullets",
        retriever_factory=retriever_factory,
        orchestrate_fn=orchestrate_fn,
        render_fn=lambda pack, fmt: f"[{fmt}] rendered",
        index_exists=lambda db: True,
        index_root="/idx",
    )
    assert out["status"] == "ok"
    assert out["mesh"] == "Republic of North Macedonia"
    assert out["format"] == "bullets"
    assert out["rendered"] == "[bullets] rendered"
    assert out["points"][0]["point"] == "WHO did X."
    assert out["points"][0]["iris_url"].endswith("/10665/1")
    assert "republic_of_north_macedonia" in seen["db"]


def test_abstained_pack_reports_abstained():
    out = server.run_brief(
        "France", "q", "paragraphs",
        retriever_factory=lambda db: object(),
        orchestrate_fn=lambda q, r: BriefingPack(query="q", points=[], abstained=True, note="nothing solid"),
        render_fn=lambda pack, fmt: "no points",
        index_exists=lambda db: True,
    )
    assert out["status"] == "abstained"


def test_invalid_format_raises():
    with pytest.raises(ValueError):
        server.run_brief(
            "France", "q", "haiku",
            retriever_factory=lambda db: object(),
            orchestrate_fn=lambda q, r: _pack_with_point(),
            render_fn=lambda pack, fmt: "x",
            index_exists=lambda db: True,
        )
