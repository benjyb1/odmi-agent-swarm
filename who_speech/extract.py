"""Docling extraction with quote-level provenance.

Converts a PDF into a frozen, deterministic serialisation plus a flat list of
elements, each carrying page number, bounding box and character span. That
provenance is what lets a later quoted claim be hash-gated back to its source.

Design decisions (from the research pass):
- do_ocr=False: correct for IRIS's born-digital corpus, and it sidesteps the
  RapidOCR init crash in docling 2.105. Scanned pages are detected by a
  per-page character-density gate (Docling has no reliable per-page toggle)
  and flagged for an OCR pass rather than silently emitting empty text.
- The canonical serialisation (export_to_dict) is byte-deterministic under a
  pinned toolchain, so its SHA-256 is a stable content anchor.

docling is imported lazily so the rest of the package (the IRIS client, the
models) works without the heavy dependency installed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from who_speech import config


@dataclass
class ExtractedElement:
    kind: str
    text: str
    page_no: Optional[int]
    bbox: Optional[tuple[float, float, float, float]]
    char_start: Optional[int]
    char_end: Optional[int]


@dataclass
class ExtractedDoc:
    source_name: str
    num_pages: int
    elements: list[ExtractedElement]
    markdown: str
    canonical: dict
    content_sha256: str
    page_char_counts: dict[int, int] = field(default_factory=dict)
    pages_needing_ocr: list[int] = field(default_factory=list)
    docling_version: str = ""


def _docling_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("docling")
    except PackageNotFoundError:
        return "unknown"


def _build_converter():
    """Construct a Docling converter with the locked, OCR-off pipeline."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(
        do_ocr=config.DOCLING_DO_OCR,
        do_table_structure=config.DOCLING_DO_TABLE_STRUCTURE,
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


def _bbox_tuple(bbox) -> Optional[tuple[float, float, float, float]]:
    if bbox is None:
        return None
    try:
        return (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))
    except AttributeError:
        return None


def _charspan(prov) -> tuple[Optional[int], Optional[int]]:
    span = getattr(prov, "charspan", None)
    if span and len(span) == 2:
        return int(span[0]), int(span[1])
    return None, None


def _collect_elements(doc) -> list[ExtractedElement]:
    """Flatten DoclingDocument texts and tables into provenanced elements."""
    elements: list[ExtractedElement] = []

    def add(kind: str, text: str, prov_list) -> None:
        text = (text or "").strip()
        if not text:
            return
        if prov_list:
            prov = prov_list[0]
            start, end = _charspan(prov)
            elements.append(
                ExtractedElement(
                    kind=kind,
                    text=text,
                    page_no=getattr(prov, "page_no", None),
                    bbox=_bbox_tuple(getattr(prov, "bbox", None)),
                    char_start=start,
                    char_end=end,
                )
            )
        else:
            elements.append(ExtractedElement(kind, text, None, None, None, None))

    for item in getattr(doc, "texts", []):
        add(
            getattr(getattr(item, "label", None), "value", "text") or "text",
            getattr(item, "text", ""),
            getattr(item, "prov", None),
        )
    for table in getattr(doc, "tables", []):
        try:
            md = table.export_to_markdown(doc)
        except TypeError:
            md = table.export_to_markdown()
        except Exception:
            md = ""
        add("table", md, getattr(table, "prov", None))

    return elements


def extract_document(pdf_path: str | Path) -> ExtractedDoc:
    """Convert a PDF to an ExtractedDoc with provenance and a content hash."""
    converter = _build_converter()
    result = converter.convert(str(pdf_path))
    doc = result.document

    canonical = doc.export_to_dict()
    canonical_json = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    content_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    elements = _collect_elements(doc)

    page_chars: dict[int, int] = {}
    for el in elements:
        if el.page_no is not None:
            page_chars[el.page_no] = page_chars.get(el.page_no, 0) + len(el.text)

    try:
        num_pages = doc.num_pages()
    except Exception:
        num_pages = max(page_chars) if page_chars else 0

    pages_needing_ocr = [
        p for p in range(1, num_pages + 1)
        if page_chars.get(p, 0) < config.OCR_CHAR_PER_PAGE_THRESHOLD
    ]

    return ExtractedDoc(
        source_name=Path(pdf_path).name,
        num_pages=num_pages,
        elements=elements,
        markdown=doc.export_to_markdown(),
        canonical=canonical,
        content_sha256=content_sha256,
        page_char_counts=page_chars,
        pages_needing_ocr=pages_needing_ocr,
        docling_version=_docling_version(),
    )


def find_quote(extracted: ExtractedDoc, quote: str) -> Optional[ExtractedElement]:
    """Seed of the C4 quote-gate: locate a verbatim quote and its provenance.

    Returns the element (with page and span) whose text contains the quote
    after light whitespace normalisation, or None. A finalised point whose
    quote is not found here must be abstained, never published.
    """
    needle = " ".join(quote.split())
    for el in extracted.elements:
        haystack = " ".join(el.text.split())
        if needle and needle in haystack:
            return el
    return None


if __name__ == "__main__":
    import sys

    from who_speech.iris import IrisClient

    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        # Grab the smallest English Kyrgyzstan PDF and extract that.
        with IrisClient() as iris:
            items = iris.search(
                filters={"mesh": "Kyrgyzstan", "language": "en"}, max_items=12
            )
            chosen = None
            for it in items:
                streams = iris.pdf_bitstreams(it.uuid)
                if streams:
                    smallest = min(streams, key=lambda b: b.size_bytes or 1 << 60)
                    if chosen is None or (smallest.size_bytes or 0) < chosen[1].size_bytes:
                        chosen = (it, smallest)
            if not chosen:
                print("no English PDF found")
                sys.exit(1)
            item, stream = chosen
            path = f"/tmp/who_{stream.uuid}.pdf"
            Path(path).write_bytes(iris.download(stream))
            print(f"Extracting: {item.title[:70]} ({stream.size_bytes} bytes)\n")

    doc = extract_document(path)
    print(f"docling {doc.docling_version}: {doc.num_pages} pages, "
          f"{len(doc.elements)} elements, {len(doc.markdown)} md chars")
    print(f"content sha256: {doc.content_sha256[:16]}...")
    print(f"pages flagged for OCR: {doc.pages_needing_ocr or 'none'}")
    tables = [e for e in doc.elements if e.kind == "table"]
    print(f"tables: {len(tables)}")
    sample = next((e for e in doc.elements if e.kind != "table" and e.page_no), None)
    if sample:
        print(f"\nsample element: page {sample.page_no}, span "
              f"({sample.char_start},{sample.char_end}), bbox {sample.bbox}")
        print(f'  "{sample.text[:120]}"')

    if doc.num_pages <= 20:
        again = extract_document(path)
        print(f"\ndeterminism: {'IDENTICAL' if again.content_sha256 == doc.content_sha256 else 'DIFFERS'} "
              f"hash across two runs")
