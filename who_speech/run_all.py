"""Build per-country indexes and run all five demo queries end-to-end.

Each country gets its own LanceDB index over an English-filtered slice of its
EURO documents (English keeps the quotes readable and verifiable for a first
breadth demo; cross-lingual retrieval is a separate capability). Indexes are
cached under /tmp/who_idx/<key> so re-runs skip the build. The embedder and
reranker load once and are shared across all five.
"""
from __future__ import annotations

import pathlib

from who_speech import config
from who_speech.swarm import QUERIES, orchestrate, print_pack

# (query key, MeSH geographic heading — note the non-obvious ones)
SLICES = [
    ("ukraine_emergency", "Ukraine"),
    ("kazakhstan_phc", "Kazakhstan"),
    ("kyrgyzstan_financing", "Kyrgyzstan"),
    ("north_macedonia_protection", "Republic of North Macedonia"),
    ("tajikistan_rehab", "Tajikistan"),
]
MAX_DOCS = 8
MAX_PDF_BYTES = 8_000_000
IDX_ROOT = "/tmp/who_idx"


def _has_passages(db_path: str) -> bool:
    """Robust table-existence probe (list_tables() returns a paginated object,
    not a plain list, so membership tests on it silently fail)."""
    import lancedb

    try:
        lancedb.connect(db_path).open_table("passages")
        return True
    except Exception:
        return False


def build_or_load(mesh, db_path, model, iris, extract_document, chunk_document, build_index):
    if _has_passages(db_path):
        print(f"  [cached] {mesh}")
        return
    items = iris.search(filters={"mesh": mesh, "language": "en"}, max_items=40)
    rows: list[dict] = []
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
        try:
            if not pdf.exists() or pdf.stat().st_size == 0:
                pdf.write_bytes(iris.download(stream))
            extracted = extract_document(path)
        except Exception as exc:  # noqa: BLE001 - skip a bad doc, keep the slice
            print(f"    skip {item.title[:40]}: {exc}")
            continue
        rows.extend(chunk_document(extracted, item, stream))
        used += 1
    print(f"  built {mesh}: {used} docs, {len(rows)} chunks")
    if rows:
        build_index(rows, model, db_path)


def main() -> None:
    from sentence_transformers import CrossEncoder, SentenceTransformer

    from who_speech.extract import extract_document
    from who_speech.index import build_index, chunk_document
    from who_speech.iris import IrisClient
    from who_speech.search import Retriever

    model = SentenceTransformer(config.EMBED_MODEL)
    reranker = CrossEncoder(config.RERANK_MODEL, max_length=512)

    print("# building indexes")
    with IrisClient() as iris:
        for key, mesh in SLICES:
            print(f"\n=== {key} ({mesh}) ===")
            try:
                build_or_load(
                    mesh, f"{IDX_ROOT}/{key}", model, iris,
                    extract_document, chunk_document, build_index,
                )
            except Exception as exc:  # noqa: BLE001 - one country failing is not fatal
                print(f"  build failed for {mesh}: {exc}")

    packs = []
    for key, mesh in SLICES:
        db_path = f"{IDX_ROOT}/{key}"
        if not _has_passages(db_path):
            print(f"\n[skip swarm] {key}: no index built")
            continue
        print(f"\n\n########## RUNNING: {key} ##########")
        retriever = Retriever(db_path, model=model, reranker=reranker)
        pack = orchestrate(QUERIES[key], retriever, verbose=True)
        packs.append(pack)

    print("\n\n" + "#" * 80 + "\n# INPUT / OUTPUT PAIRS\n" + "#" * 80)
    for pack in packs:
        print_pack(pack)


if __name__ == "__main__":
    main()
