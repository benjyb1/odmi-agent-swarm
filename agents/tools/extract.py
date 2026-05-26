"""Boilerplate-stripping wrapper around trafilatura.

Used by the DIY-Tavily pipeline (search_diy.py) between Playwright fetch
and the Claude snippet picker. trafilatura strips navigation, footers,
cookie banners, and other boilerplate that would otherwise pollute the
snippet picker's input. PDFs are out of scope for v1 -- only HTML pages
are processed.

The is_html=False path is the cache-hit branch: agents/tools/fetch.py
returns text that has already had tags stripped, so re-running trafilatura
would either be a no-op or (worse) blank the content. When the caller
knows the input is already cleaned text, pass is_html=False to short-circuit.
"""
from __future__ import annotations

from typing import Optional

import trafilatura


def extract_text(content: str, *, url: str, is_html: bool = True) -> str:
    """Return cleaned plain text from a webpage.

    If is_html=False, returns `content` verbatim -- caller already has
    cleaned text and wants to avoid re-extraction.

    On extraction failure (malformed HTML, empty input, trafilatura returns
    None) returns an empty string. Caller can decide whether to drop the URL.
    """
    if not content:
        return ""
    if not is_html:
        return content
    extracted = trafilatura.extract(
        content,
        favor_recall=True,
        include_comments=False,
        include_tables=True,
        url=url,
    )
    return extracted or ""
