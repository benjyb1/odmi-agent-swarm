"""End-to-end PoC run: IRIS -> Docling -> chunk -> LanceDB -> hybrid retrieve.

Builds a small index over a handful of English Kyrgyzstan documents and runs
demo query 3 (health financing reform), printing the retrieved passages with
their citation, page and reranker score. This exercises the whole backend
wiring on real EURO content.

Not the full swarm: the researcher/verifier/adjudicator and the briefing-pack
assembly are the next layer. This proves the retrieval substrate they sit on.
"""
from __future__ import annotations

import pathlib

from who_speech import config

MAX_DOCS = 6
MAX_PDF_BYTES = 8_000_000
DB_PATH = "/tmp/who_lancedb"
DEMO_QUERY = (
    "What has WHO done on hospital payment and health financing reform in Kyrgyzstan?"
)


def main() -> None:
    from sentence_transformers import SentenceTransformer

    from who_speech.extract import extract_document
    from who_speech.index import build_index, chunk_document
    from who_speech.iris import IrisClient
    from who_speech.search import Retriever

    rows: list[dict] = []
    with IrisClient() as iris:
        items = iris.search(
            filters={"mesh": "Kyrgyzstan", "language": "en"}, max_items=30
        )
        used = 0
        for item in items:
            if used >= MAX_DOCS:
                break
            streams = iris.pdf_bitstreams(item.uuid)
            if not streams:
                continue
            stream = min(streams, key=lambda b: b.size_bytes or 1 << 60)
            if (stream.size_bytes or 0) > MAX_PDF_BYTES:
                continue
            path = f"/tmp/who_{stream.uuid}.pdf"
            pdf = pathlib.Path(path)
            if not pdf.exists() or pdf.stat().st_size == 0:
                pdf.write_bytes(iris.download(stream))
            extracted = extract_document(path)
            new = chunk_document(extracted, item, stream)
            rows.extend(new)
            used += 1
            print(f"indexed [{item.year}] {item.title[:58]}  "
                  f"({extracted.num_pages}p, +{len(new)} chunks, {len(rows)} total)")

    print(f"\nembedding + indexing {len(rows)} chunks with {config.EMBED_MODEL} ...")
    model = SentenceTransformer(config.EMBED_MODEL)
    build_index(rows, model, DB_PATH)

    retriever = Retriever(DB_PATH, model=model)
    print(f"\nQUERY: {DEMO_QUERY}\n")
    passages = retriever.retrieve(DEMO_QUERY)
    if not passages:
        print("(abstained: no passage cleared the confidence floor)")
    for p in passages:
        print(f"[{p.score:.2f}] p.{p.page_start}  {p.citation}")
        print(f"    {p.text[:220].strip().replace(chr(10), ' ')}")
        print(f"    {p.iris_url}\n")


if __name__ == "__main__":
    main()
