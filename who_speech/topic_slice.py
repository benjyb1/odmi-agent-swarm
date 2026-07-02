"""Thematic (non-country) index slices, and the AI-in-health demo runner.

The country slices key on one MeSH geographic heading. A theme spans several
subject headings, so this builder takes a list of MeSH headings, unions the
English-language hits, keeps only quotable (CC-licensed) items, and indexes
the newest ones within the usual politeness and size budgets. If every facet
comes back empty, it falls back to a free-text discovery query over the EURO
subtree.

The __main__ runs the full AI-in-health demo for the 15 July Shaping AI in
Health conference: build (or reuse) the slice, run the swarm on the
`ai_digital_health` query, and render the surviving points with the
dual-format renderer.

    uv run --with docling --with lancedb --with sentence-transformers \
        --with python-docx python -m who_speech.topic_slice
"""
from __future__ import annotations

import pathlib

from who_speech import config
from who_speech.models import IrisItem

# Subject headings for the AI / digital health theme (probed live 2026-07-02:
# 30 / 30 / 58 EURO items respectively; "Machine Learning" has 1, "Telemedicine
# and eHealth" 0, so they are not worth a facet call).
AI_HEALTH_MESH = ["Artificial Intelligence", "Digital Health", "Telemedicine"]
AI_HEALTH_FALLBACK_QUERY = "artificial intelligence digital health"
AI_HEALTH_DB = "/tmp/who_idx/ai_health_d20"

MAX_DOCS = 20
MAX_PDF_BYTES = 8_000_000
PER_HEADING_ITEMS = 40


def collect_topic_items(iris, mesh_headings: list[str], fallback_query: str) -> list[IrisItem]:
    """Union of quotable English items across the theme's MeSH headings.

    Newest first. Falls back to free-text discovery search when the facets
    yield nothing (some themes have no dedicated MeSH heading).
    """
    seen: dict[str, IrisItem] = {}
    for mesh in mesh_headings:
        items = iris.search(
            filters={"mesh": mesh, "language": "en"}, max_items=PER_HEADING_ITEMS
        )
        for item in items:
            if item.quotable and (item.language or "").startswith("en"):
                seen.setdefault(item.uuid, item)
    if not seen:
        items = iris.search(query=fallback_query, max_items=PER_HEADING_ITEMS)
        for item in items:
            if item.quotable and (item.language or "").startswith("en"):
                seen.setdefault(item.uuid, item)
    return sorted(seen.values(), key=lambda it: -(it.year or 0))


def build_topic_index(
    iris,
    mesh_headings: list[str],
    db_path: str,
    model,
    *,
    fallback_query: str = "",
    max_docs: int = MAX_DOCS,
) -> int:
    """Download, extract and index the topic slice. Returns docs indexed."""
    from who_speech.extract import extract_document
    from who_speech.index import build_index, chunk_document

    items = collect_topic_items(iris, mesh_headings, fallback_query)
    print(f"topic slice: {len(items)} quotable English items across {mesh_headings}")

    rows: list[dict] = []
    used = 0
    for item in items:
        if used >= max_docs:
            break
        streams = iris.pdf_bitstreams(item.uuid)
        if not streams:
            continue
        stream = min(streams, key=lambda b: b.size_bytes or 1 << 60)
        if (stream.size_bytes or 0) > MAX_PDF_BYTES:
            continue
        path = f"/tmp/who_{stream.uuid}.pdf"
        pdf = pathlib.Path(path)
        try:
            if not pdf.exists() or pdf.stat().st_size == 0:
                pdf.write_bytes(iris.download(stream))
            extracted = extract_document(path)
        except Exception as exc:  # noqa: BLE001 - skip a bad doc, keep the slice
            print(f"  skip {item.title[:50]}: {exc}")
            continue
        rows.extend(chunk_document(extracted, item, stream))
        used += 1
        print(f"  [{used}/{max_docs}] {item.title[:70]} ({item.year})")
    print(f"built: {used} docs, {len(rows)} chunks")
    if rows:
        build_index(rows, model, db_path)
    return used


def main() -> None:
    from sentence_transformers import CrossEncoder, SentenceTransformer

    from who_speech.iris import IrisClient
    from who_speech.render import render_briefing
    from who_speech.run_all import _has_passages
    from who_speech.search import Retriever
    from who_speech.swarm import QUERIES, orchestrate, print_pack

    model = SentenceTransformer(config.EMBED_MODEL)
    reranker = CrossEncoder(config.RERANK_MODEL, max_length=512)

    if _has_passages(AI_HEALTH_DB):
        print(f"[cached] {AI_HEALTH_DB}")
    else:
        with IrisClient() as iris:
            built = build_topic_index(
                iris, AI_HEALTH_MESH, AI_HEALTH_DB, model,
                fallback_query=AI_HEALTH_FALLBACK_QUERY,
            )
        if not built:
            raise SystemExit("no documents indexed; aborting")

    retriever = Retriever(AI_HEALTH_DB, model=model, reranker=reranker)
    pack = orchestrate(QUERIES["ai_digital_health"], retriever, verbose=True)
    print_pack(pack)

    out_dir = pathlib.Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    out = render_briefing(
        pack,
        str(out_dir / "who_ai_health_briefing.docx"),
        title="WHO/Europe briefing: artificial intelligence and digital health",
    )
    print(f"\nrendered: {out}")


if __name__ == "__main__":
    main()
