"""Build and refresh the persistent per-country index.

The PoC built indexes into /tmp and capped at a handful of English documents.
For a deployable service the index must live somewhere durable and cover more
of each country's record. ``build_country_index`` holds the orchestration
(which documents to fetch, how many, dedup across language slices, where to
write) with every heavy dependency injected, so it is unit-tested without live
IRIS or a model. ``refresh_country`` wires the real dependencies and is the
entry point for the scheduled refresh job.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from who_speech import config


def index_slug(mesh: str) -> str:
    """Filesystem-safe slug for a MeSH heading (the index subdirectory name)."""
    return re.sub(r"[^a-z0-9]+", "_", mesh.casefold()).strip("_")


def index_path_for(mesh: str, root: Optional[str] = None) -> str:
    return str(Path(root or config.index_root()) / index_slug(mesh))


def build_country_index(
    mesh: str,
    *,
    db_path: str,
    model,
    iris,
    extract_document: Callable,
    chunk_document: Callable,
    build_index: Callable,
    pdf_cache: str,
    languages=("en",),
    max_docs: Optional[int] = None,
    max_pdf_bytes: int = 8_000_000,
    log: Callable = print,
) -> dict:
    """Fetch a bounded country slice, extract and chunk it, and build the index.

    Returns a summary dict. Documents are deduplicated across language slices,
    items without a PDF (or with an oversized one) are skipped, and a document
    that fails extraction is skipped rather than failing the whole build.
    """
    max_docs = max_docs or config.max_docs()
    Path(pdf_cache).mkdir(parents=True, exist_ok=True)

    items = []
    seen: set[str] = set()
    for lang in languages:
        for it in iris.search(filters={"mesh": mesh, "language": lang}, max_items=max_docs * 3):
            if it.uuid not in seen:
                seen.add(it.uuid)
                items.append(it)

    rows: list[dict] = []
    used = 0
    for item in items:
        if used >= max_docs:
            break
        streams = iris.pdf_bitstreams(item.uuid)
        if not streams:
            continue
        stream = min(streams, key=lambda b: b.size_bytes or 1 << 60)
        if (stream.size_bytes or 0) > max_pdf_bytes:
            continue
        path = str(Path(pdf_cache) / f"{stream.uuid}.pdf")
        pdf = Path(path)
        try:
            if not pdf.exists() or pdf.stat().st_size == 0:
                pdf.write_bytes(iris.download(stream))
            extracted = extract_document(path)
        except Exception as exc:  # noqa: BLE001 - skip a bad document, keep the slice
            log(f"skip {item.title[:40]}: {exc}")
            continue
        rows.extend(chunk_document(extracted, item, stream))
        used += 1
        log(f"indexed [{item.year}] {item.title[:50]} ({len(rows)} chunks total)")

    if rows:
        build_index(rows, model, db_path)
    return {"mesh": mesh, "docs": used, "chunks": len(rows), "db_path": db_path}


def refresh_country(country: str, *, model=None) -> dict:
    """Wire the real dependencies and (re)build the durable index for a country."""
    from sentence_transformers import SentenceTransformer

    from who_speech.countries import resolve_country
    from who_speech.extract import extract_document
    from who_speech.index import build_index, chunk_document
    from who_speech.iris import IrisClient

    mesh = resolve_country(country)
    db_path = index_path_for(mesh)
    model = model or SentenceTransformer(config.EMBED_MODEL)
    pdf_cache = str(Path(config.index_root()) / "_pdf_cache")
    with IrisClient() as iris:
        return build_country_index(
            mesh, db_path=db_path, model=model, iris=iris,
            extract_document=extract_document, chunk_document=chunk_document,
            build_index=build_index, pdf_cache=pdf_cache,
            languages=tuple(config.index_languages()), max_docs=config.max_docs(),
        )


if __name__ == "__main__":
    import sys

    from sentence_transformers import SentenceTransformer

    countries = sys.argv[1:] or ["Kyrgyzstan"]
    shared_model = SentenceTransformer(config.EMBED_MODEL)
    for c in countries:
        print(refresh_country(c, model=shared_model))
