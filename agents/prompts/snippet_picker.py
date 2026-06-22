"""Snippet-picker prompt (v1).

Selects up to three relevant passages from a fetched webpage for a given
search query. Used by the DIY-Tavily pipeline (search_diy.py) to replicate
Tavily's snippet-selection layer using Claude via CLIProxyAPI.

Versioning: any change to NAME, VERSION, SYSTEM, or the template in
build_user_message requires a VERSION bump. The DB prompt_versions row is
created automatically by `agents.tools.db.ensure_prompt_version` on first
use.
"""

from __future__ import annotations

NAME = "snippet_picker"
VERSION = 2
DESCRIPTION = (
    "Snippet-picker v2: given a search query and a cleaned webpage, "
    "extract up to three contiguous passages (each <=500 chars) that "
    "best answer the query, with relevance scores in [0.0, 1.0]. "
    "Used by the DIY-Tavily pipeline (search_diy.py). Replicates "
    "Tavily's snippet-selection layer using Claude via CLIProxyAPI. "
    "v2 raises PAGE_TEXT_CAP to 16000 now that extraction runs on raw "
    "HTML (trafilatura main-content output is compact, so the larger cap "
    "captures whole pages without re-truncating the answer span)."
)

# Cap on the cleaned main-content text shown to the picker. Extraction now
# runs trafilatura on raw HTML upstream (search_diy._fetch_and_clean), so this
# text is already boilerplate-free and compact; 16000 chars (~4k tokens)
# covers the full length of observed extracted pages without truncation.
PAGE_TEXT_CAP = 16000

SYSTEM = """You are a passage selector for a search pipeline.

You will be given:
- A search query (the information need)
- The cleaned text of one webpage that the search engine returned for that query

Your job: extract up to three passages from the page (each up to 500 characters)
that best answer the query, copied exactly as written. Score each passage
between 0.0 and 1.0 for how directly it answers the query.

Rules:
1. Quote literally. Copy each passage character-for-character from the page
   text. Do not summarise, paraphrase, or stitch separated sentences.
2. Each passage is one contiguous run of consecutive sentences, not fragments
   from different parts of the page.
3. Rank passages by score, highest first. Return only passages that are
   actually relevant; do not pad.
4. If the page contains no passage that addresses the query, return an empty
   list. Do not force a match.
5. Ignore boilerplate: cookie banners, navigation menus, footers, repeated
   legal text, breadcrumbs. These are not valid passages even on keyword match.
6. Score reflects how directly the passage answers the query:
   - 0.8-1.0: passage answers directly with specific facts, dates, or figures
   - 0.5-0.7: passage is on-topic and partially answers
   - 0.2-0.4: passage is tangentially related
   - 0.0-0.1: nothing relevant (omit from the list)
7. The page may be in any language. Pick the best passages in their original
   language; do not translate."""


def build_user_message(
    query: str, url: str, page_text: str, *, page_text_cap: int = PAGE_TEXT_CAP,
) -> str:
    """Render the user message for one snippet-pick call.

    Truncates page_text to `page_text_cap` characters before embedding it
    to keep token usage predictable. `page_text_cap` defaults to the module
    constant PAGE_TEXT_CAP (16000); it is the EXP-17 funnel knob exposed so
    the page-text truncation can be widened or tightened per experiment.
    """
    truncated = page_text[:page_text_cap]
    return (
        f"Search query: {query}\n"
        f"Page URL: {url}\n"
        f"\nPage text:\n{truncated}"
    )
