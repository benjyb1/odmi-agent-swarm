"""Persistent per-country index build.

The orchestration (which documents to fetch, how many, where to write) is
dependency-injected so it is tested with fakes, no live IRIS and no model.
"""
from __future__ import annotations

from who_speech import build
from who_speech.models import Bitstream, IrisItem


def _item(uuid, language="en", title="A document"):
    return IrisItem(
        uuid=uuid, title=title, handle=f"10665/{uuid}",
        year=2021, language=language, rights="CC BY 3.0 IGO",
    )


def _stream(uuid, size=1000):
    return Bitstream(uuid=f"{uuid}s", name="file.pdf", size_bytes=size, content_url="http://x/content")


class FakeIris:
    def __init__(self, items, streams_for):
        self._items = items
        self._streams_for = streams_for

    def search(self, *, filters, max_items=None):
        lang = filters.get("language")
        hits = [it for it in self._items if it.language == lang]
        return hits[:max_items] if max_items else hits

    def pdf_bitstreams(self, uuid):
        return self._streams_for.get(uuid, [])

    def download(self, stream):
        return b"%PDF-1.4 fake bytes"


def test_index_slug_normalises_heading():
    assert build.index_slug("Republic of North Macedonia") == "republic_of_north_macedonia"
    assert build.index_slug("Georgia (Republic)") == "georgia_republic"


def test_index_path_uses_root():
    assert build.index_path_for("France", root="/idx").endswith("/france")


def test_build_indexes_up_to_max_docs(tmp_path):
    items = [_item("a"), _item("b"), _item("c")]
    streams = {u: [_stream(u)] for u in ("a", "b", "c")}
    built = {}
    summary = build.build_country_index(
        "Kyrgyzstan",
        db_path=str(tmp_path / "idx"), model=None, iris=FakeIris(items, streams),
        extract_document=lambda path: object(),
        chunk_document=lambda extracted, item, stream: [{"id": item.uuid}],
        build_index=lambda rows, model, db_path: built.update(rows=rows, db=db_path),
        pdf_cache=str(tmp_path / "pdf"), languages=("en",), max_docs=2, log=lambda *a: None,
    )
    assert summary["docs"] == 2
    assert len(built["rows"]) == 2
    assert built["db"] == str(tmp_path / "idx")


def test_build_skips_items_without_pdfs(tmp_path):
    items = [_item("a"), _item("b")]
    streams = {"b": [_stream("b")]}  # "a" has no PDF
    built = {}
    summary = build.build_country_index(
        "X",
        db_path=str(tmp_path / "idx"), model=None, iris=FakeIris(items, streams),
        extract_document=lambda path: object(),
        chunk_document=lambda extracted, item, stream: [{"id": item.uuid}],
        build_index=lambda rows, model, db_path: built.update(rows=rows),
        pdf_cache=str(tmp_path / "pdf"), languages=("en",), max_docs=10, log=lambda *a: None,
    )
    assert summary["docs"] == 1


def test_build_dedups_across_languages(tmp_path):
    # Same uuid catalogued under two language slices must be indexed once.
    items = [_item("a", language="en"), _item("a", language="fr"), _item("b", language="fr")]
    streams = {u: [_stream(u)] for u in ("a", "b")}
    built = {}
    summary = build.build_country_index(
        "X",
        db_path=str(tmp_path / "idx"), model=None, iris=FakeIris(items, streams),
        extract_document=lambda path: object(),
        chunk_document=lambda extracted, item, stream: [{"id": item.uuid}],
        build_index=lambda rows, model, db_path: built.update(rows=rows),
        pdf_cache=str(tmp_path / "pdf"), languages=("en", "fr"), max_docs=10, log=lambda *a: None,
    )
    assert summary["docs"] == 2  # a (once) + b
