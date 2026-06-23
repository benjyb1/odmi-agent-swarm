"""Provenance-preserving chunking and LanceDB index build.

Children (the embedded, citable unit) are packed from consecutive Docling
elements up to a token budget; each child keeps its document, bitstream, page
range and licence so a hit can be cited and licence-gated. A parent window
(neighbouring children) is stored for the reading context handed to the LLM.

LanceDB is imported lazily so the chunker is usable without the heavy stack.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from who_speech import config

if TYPE_CHECKING:
    from who_speech.extract import ExtractedDoc
    from who_speech.models import Bitstream, IrisItem

# Rough chars-per-token; good enough to bound child size for a PoC without
# loading a tokenizer. Production can swap in the BGE-M3 tokenizer.
_CHARS_PER_TOKEN = 4
_CHILD_CHARS = config.CHILD_CHUNK_TOKENS * _CHARS_PER_TOKEN
_PARENT_CHARS = config.PARENT_CHUNK_TOKENS * _CHARS_PER_TOKEN


def _split_long(text: str, max_chars: int) -> list[str]:
    """Split an oversized element (e.g. a big table) into word-bounded pieces.

    Without this a single large element becomes one giant chunk, which blows
    up the embedder's attention memory.
    """
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for word in text.split():
        if cur and cur_len + len(word) + 1 > max_chars:
            pieces.append(" ".join(cur))
            cur, cur_len = [], 0
        cur.append(word)
        cur_len += len(word) + 1
    if cur:
        pieces.append(" ".join(cur))
    return pieces


def chunk_document(
    extracted: "ExtractedDoc", item: "IrisItem", bitstream: "Bitstream"
) -> list[dict]:
    """Pack elements into citable child chunks, hard-capped at the child size."""
    children: list[dict] = []
    buf: list[str] = []
    buf_chars = 0
    buf_pages: set[int] = set()

    def flush() -> None:
        nonlocal buf, buf_chars, buf_pages
        if not buf:
            return
        pages = sorted(p for p in buf_pages if p is not None)
        children.append(
            {
                "id": f"{bitstream.uuid}:{len(children)}",
                "text": "\n".join(buf),
                "parent_text": "",
                "doc_uuid": item.uuid,
                "bitstream_uuid": bitstream.uuid,
                "title": item.title,
                "year": item.year or 0,
                "language": item.language or "",
                "rights": item.rights or "",
                "iris_url": item.iris_url or "",
                "page_start": pages[0] if pages else 0,
                "page_end": pages[-1] if pages else 0,
            }
        )
        buf, buf_chars, buf_pages = [], 0, set()

    for el in extracted.elements:
        for seg in _split_long(el.text, _CHILD_CHARS):
            if buf and buf_chars + len(seg) > _CHILD_CHARS:
                flush()
            buf.append(seg)
            buf_chars += len(seg)
            buf_pages.add(el.page_no)
    flush()

    # Parent context: this child plus its immediate neighbours, trimmed.
    for i, child in enumerate(children):
        lo = children[i - 1]["text"] if i > 0 else ""
        hi = children[i + 1]["text"] if i + 1 < len(children) else ""
        child["parent_text"] = "\n".join(p for p in (lo, child["text"], hi) if p)[:_PARENT_CHARS]

    return children


def embed_texts(model, texts: list[str]):
    """Dense BGE-M3 embeddings, L2-normalised for cosine/IP search.

    Cap the sequence length (bounds attention memory; children are ~256 tokens
    anyway) and batch modestly so encoding fits on an MPS/CPU device.
    """
    try:
        model.max_seq_length = min(getattr(model, "max_seq_length", 512) or 512, 512)
    except Exception:
        pass
    return model.encode(
        texts, normalize_embeddings=True, show_progress_bar=False, batch_size=16
    )


def build_index(rows: list[dict], model, db_path: str, table_name: str = "passages"):
    """Embed child chunks and (re)build a LanceDB hybrid table over them."""
    import lancedb
    from lancedb.pydantic import LanceModel, Vector

    class ChunkRow(LanceModel):
        id: str
        text: str
        parent_text: str
        vector: Vector(1024)  # BGE-M3 dense dim
        doc_uuid: str
        bitstream_uuid: str
        title: str
        year: int
        language: str
        rights: str
        iris_url: str
        page_start: int
        page_end: int

    vectors = embed_texts(model, [r["text"] for r in rows])
    data = [{**r, "vector": v.tolist()} for r, v in zip(rows, vectors)]

    db = lancedb.connect(db_path)
    if table_name in db.table_names():
        db.drop_table(table_name)
    table = db.create_table(table_name, schema=ChunkRow)
    table.add(data)
    table.create_fts_index("text", replace=True)
    return table
