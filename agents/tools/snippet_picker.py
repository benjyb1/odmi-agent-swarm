"""Snippet-picker tool: calls Claude to select relevant passages from a page.

Wraps `agents.prompts.snippet_picker` and `agents.tools.llm.call_for_structured`
to provide a clean interface for the DIY-Tavily pipeline (search_diy.py).

Public interface
----------------
pick_snippet(*, query, url, page_text, subtrio_id) -> (List[PickedChunk], LLMUsage)
    Call Claude to select passages from page_text that answer query.

aggregate_snippet(chunks) -> str
    Join chunks into a single string for downstream consumers.

aggregate_score(chunks) -> float | None
    Return the top chunk's score (the list is already ranked highest-first).
"""

from __future__ import annotations

from typing import Annotated, List, Optional

from pydantic import BaseModel, Field

from agents.models import LLMUsage
from agents.prompts.snippet_picker import (
    DESCRIPTION,
    NAME,
    SYSTEM,
    VERSION,
    build_user_message,
)
from agents.tools.db import ensure_prompt_version
from agents.tools.llm import call_for_structured

TOP_CHUNK_THRESHOLD = 0.7
MULTI_CHUNK_SEPARATOR = " ... "


class PickedChunk(BaseModel):
    """One passage selected from a webpage by the snippet-picker prompt."""

    text: str = Field(..., max_length=500)
    score: float = Field(..., ge=0.0, le=1.0)


class _ChunksOut(BaseModel):
    """Internal schema returned by Claude. Max three chunks per spec."""

    chunks: Annotated[List[PickedChunk], Field(max_length=3)]


def pick_snippet(
    *,
    query: str,
    url: str,
    page_text: str,
    subtrio_id: Optional[str] = None,
) -> tuple[List[PickedChunk], LLMUsage]:
    """Select relevant passages from page_text that answer query.

    Returns
    -------
    (chunks, usage)
        chunks  -- list of PickedChunk, already ranked highest-score-first.
                   May be empty if no relevant passage was found.
        usage   -- LLMUsage record for this call.

    Threshold logic (TOP_CHUNK_THRESHOLD = 0.7)
    --------------------------------------------
    If chunks[0].score >= 0.7, we have a confident top hit; return only
    that single chunk. Otherwise return up to three (the model may have
    returned fewer). An empty list from the model is passed back unchanged.
    """
    prompt_version_id = ensure_prompt_version(NAME, VERSION, SYSTEM, DESCRIPTION)

    user_message = build_user_message(query, url, page_text)

    parsed, usage = call_for_structured(
        system=SYSTEM,
        user_message=user_message,
        output_schema=_ChunksOut,
        max_tokens=1500,
        condition_label="snippet_pick",
        prompt_version_id=prompt_version_id,
        usage_context=f"snippet_pick:{url[:80]}",
        subtrio_id=subtrio_id,
    )

    chunks = parsed.chunks
    if not chunks:
        return [], usage

    if chunks[0].score >= TOP_CHUNK_THRESHOLD:
        return chunks[:1], usage

    return chunks[:3], usage


def aggregate_snippet(chunks: List[PickedChunk]) -> str:
    """Join chunk texts with MULTI_CHUNK_SEPARATOR.

    Returns an empty string for an empty list.
    """
    if not chunks:
        return ""
    return MULTI_CHUNK_SEPARATOR.join(c.text for c in chunks)


def aggregate_score(chunks: List[PickedChunk]) -> Optional[float]:
    """Return the top chunk's score (chunks are ranked highest-first).

    Returns None for an empty list. Does NOT return the max score across
    all chunks; the first element is the highest-scored passage by design.
    """
    if not chunks:
        return None
    return chunks[0].score
