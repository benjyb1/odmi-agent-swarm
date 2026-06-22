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

from pydantic import BaseModel, Field, field_validator

from agents.models import LLMUsage
from agents.prompts import snippet_picker as picker_prompt
from agents.tools.db import ensure_prompt_version
from agents.tools.llm import call_for_structured, StructuredOutputError

TOP_CHUNK_THRESHOLD = 0.7
MULTI_CHUNK_SEPARATOR = " ... "
MAX_CHUNK_CHARS = 500


class PickedChunk(BaseModel):
    """One passage selected from a webpage by the snippet-picker prompt."""

    text: str
    score: float = Field(..., ge=0.0, le=1.0)

    @field_validator("text", mode="before")
    @classmethod
    def truncate_text(cls, v: object) -> str:
        """Silently truncate over-long chunks.

        The prompt instructs Claude to stay within MAX_CHUNK_CHARS characters,
        but Claude occasionally overshoots by a few characters. A hard
        validation error here would crash the entire picker call; truncation
        is the safer, production-appropriate behaviour.
        """
        s = str(v)
        return s[:MAX_CHUNK_CHARS] if len(s) > MAX_CHUNK_CHARS else s


class _ChunksOut(BaseModel):
    """Internal schema returned by Claude. Max three chunks per spec."""

    chunks: Annotated[List[PickedChunk], Field(max_length=3)]


def pick_snippet(
    *,
    query: str,
    url: str,
    page_text: str,
    subtrio_id: Optional[str] = None,
    max_chunks: int = 3,
    page_text_cap: int = picker_prompt.PAGE_TEXT_CAP,
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
    that single chunk. Otherwise return up to `max_chunks` (default 3, the
    model may have returned fewer). An empty list from the model is passed
    back unchanged. `max_chunks` is the EXP-17 funnel knob; the default
    keeps the historical three-chunk ceiling byte-identical.
    """
    prompt_version_id = ensure_prompt_version(
        picker_prompt.NAME, picker_prompt.VERSION,
        picker_prompt.SYSTEM, picker_prompt.DESCRIPTION,
    )

    user_message = picker_prompt.build_user_message(
        query, url, page_text, page_text_cap=page_text_cap,
    )

    try:
        parsed, usage = call_for_structured(
            system=picker_prompt.SYSTEM,
            user_message=user_message,
            output_schema=_ChunksOut,
            max_tokens=1500,
            condition_label="snippet_pick",
            prompt_version_id=prompt_version_id,
            usage_context=f"snippet_pick:{url[:80]}",
            subtrio_id=subtrio_id,
        )
    except StructuredOutputError as exc:
        # The model occasionally emits invalid JSON (e.g. unescaped inner
        # quotes inside a quoted passage). Treat that page as yielding no
        # usable passage and drop it, rather than crashing the whole search.
        # The per-call token usage was already logged inside call_for_structured.
        usage = LLMUsage(
            input_tokens=0, output_tokens=0, wall_clock_ms=0,
            estimated_cost_usd=0.0, model_version="unparsed",
            prompt_version_id=prompt_version_id,
            condition_label="snippet_pick_parse_failed",
            raw_response=str(exc)[:500],
        )
        return [], usage

    chunks = parsed.chunks
    if not chunks:
        return [], usage

    if chunks[0].score >= TOP_CHUNK_THRESHOLD:
        return chunks[:1], usage

    return chunks[:max_chunks], usage


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
