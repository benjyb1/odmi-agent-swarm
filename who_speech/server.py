"""MCP server exposing the WHO/Europe speech-writer as one tool.

This is the integration surface for Copilot Studio (which connects to MCP
servers directly) or any other MCP client. The agent in WHO's tenant becomes
the chat front end; this server does the verified work and returns a finished
briefing pack in the requested format.

``run_brief`` is the handler with its dependencies injected, so the contract
(country resolution, the no-index path, point serialisation, format choice) is
unit-tested without an index, a model or an LLM. ``build_server`` does the thin
MCP wiring and lazy-imports the framework, so importing this module for the
tests needs neither the ``mcp`` package nor the heavy retrieval stack.
"""
from __future__ import annotations

from typing import Callable, Optional

from who_speech import render
from who_speech.build import index_path_for
from who_speech.countries import resolve_country


def _default_index_exists(db_path: str) -> bool:
    """Robust probe: open the passages table (list_tables is paginated)."""
    try:
        import lancedb

        lancedb.connect(db_path).open_table("passages")
        return True
    except Exception:
        return False


def _point_dict(p) -> dict:
    return {
        "point": p.point,
        "quote": p.quote,
        "citation": p.citation,
        "iris_url": p.iris_url,
        "page": p.page,
        "confidence": p.confidence,
    }


def run_brief(
    country: str,
    question: str,
    fmt: str = "bullets",
    *,
    retriever_factory: Callable,
    orchestrate_fn: Callable,
    render_fn: Callable,
    index_exists: Callable,
    index_root: Optional[str] = None,
    verify_fn: Optional[Callable] = None,
) -> dict:
    """Produce a briefing for a country, in the requested format.

    Returns a JSON-serialisable dict with status (ok / abstained / no_index),
    the rendered text, and the structured verified points with their sources.
    When ``verify_fn`` is supplied, the pack passes through it before rendering
    (the independent-source quote check), so points whose quotes do not
    reproduce in the cited PDF are dropped.
    """
    if fmt not in render.FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {render.FORMATS}")
    mesh = resolve_country(country)
    db_path = index_path_for(mesh, index_root)
    if not index_exists(db_path):
        return {
            "status": "no_index", "country": country, "mesh": mesh, "format": fmt,
            "question": question, "rendered": "", "points": [],
            "message": f"No index built for {mesh}. Run the refresh job for this country first.",
        }
    retriever = retriever_factory(db_path)
    pack = orchestrate_fn(question, retriever)
    if verify_fn is not None:
        pack = verify_fn(pack)
    text = render_fn(pack, fmt)
    status = "abstained" if (pack.abstained or not pack.points) else "ok"
    return {
        "status": status, "country": country, "mesh": mesh, "format": fmt,
        "question": question, "rendered": text, "note": pack.note,
        "points": [_point_dict(p) for p in pack.points],
    }


def _make_verify_fn(db_path: str):
    """A verify_fn that re-checks each quote against an independent extraction
    of the cited PDF and drops the points that do not reproduce."""
    from who_speech import verify
    from who_speech.iris import IrisClient
    from who_speech.swarm import BriefingPack

    def verify_fn(pack):
        with IrisClient() as iris:
            resolver = verify.make_source_resolver(db_path, iris)
            result = verify.verify_pack(pack, source_text_for=resolver)
        return BriefingPack(
            query=pack.query, points=result.points,
            abstained=not result.points,
            note=pack.note if result.points else "no points reproduced in source",
        )

    return verify_fn


def _real_brief(country: str, question: str, fmt: str = "bullets") -> dict:
    """run_brief wired to the real retrieval stack and swarm."""
    from who_speech import config
    from who_speech.build import index_path_for
    from who_speech.countries import resolve_country
    from who_speech.search import Retriever
    from who_speech.swarm import orchestrate

    verify_fn = None
    if config.verify_source():
        verify_fn = _make_verify_fn(index_path_for(resolve_country(country)))

    return run_brief(
        country, question, fmt,
        retriever_factory=lambda db: Retriever(db),
        orchestrate_fn=lambda q, r: orchestrate(q, r, verbose=False),
        render_fn=lambda pack, f: render.render(pack, f),
        index_exists=_default_index_exists,
        verify_fn=verify_fn,
    )


def build_server():
    """Construct the MCP server. Lazy-imports the framework."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("who-speech")

    @mcp.tool()
    def who_brief(country: str, question: str, format: str = "bullets") -> dict:
        """Produce a verified, cited WHO/Europe briefing for a country.

        country: country name (resolved to its IRIS MeSH heading).
        question: what to brief on, e.g. "What has WHO done on primary health
            care in Kazakhstan?".
        format: "bullets" (one sourced point each) or "paragraphs" (speech-style
            prose plus a sources block). Every point is grounded in a verbatim
            quote from a CC-licensed WHO document; unsupported angles are
            abstained, not invented.
        """
        return _real_brief(country, question, format)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
