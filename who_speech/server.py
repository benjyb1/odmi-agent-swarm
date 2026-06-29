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
) -> dict:
    """Produce a briefing for a country, in the requested format.

    Returns a JSON-serialisable dict with status (ok / abstained / no_index),
    the rendered text, and the structured verified points with their sources.
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
    text = render_fn(pack, fmt)
    status = "abstained" if (pack.abstained or not pack.points) else "ok"
    return {
        "status": status, "country": country, "mesh": mesh, "format": fmt,
        "question": question, "rendered": text, "note": pack.note,
        "points": [_point_dict(p) for p in pack.points],
    }


def _real_brief(country: str, question: str, fmt: str = "bullets") -> dict:
    """run_brief wired to the real retrieval stack and swarm."""
    from who_speech.search import Retriever
    from who_speech.swarm import orchestrate

    return run_brief(
        country, question, fmt,
        retriever_factory=lambda db: Retriever(db),
        orchestrate_fn=lambda q, r: orchestrate(q, r, verbose=False),
        render_fn=lambda pack, f: render.render(pack, f),
        index_exists=_default_index_exists,
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
