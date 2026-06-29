"""Two post-verifier watertightness gates, both drop-only.

- ``numbers_supported`` (FM-06): a deterministic check that every number a
  point asserts is present in its quote. Cheap, model-free, and it turns
  figure-hallucination from a prompt-tunable risk into a caught one.
- ``check_context`` (FM-02): an LLM judgement of whether the point is misleading
  once the surrounding passage is read, not just the isolated quote.

Both are wired into the swarm behind config flags so they can be ablated, which
is how we measure whether they actually improve the output.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from who_speech import llm, prompts

# A number token: an integer or decimal, with optional thousands separators.
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """Normalised numeric tokens in the text (thousands separators removed)."""
    out: set[str] = set()
    for m in _NUM_RE.findall(text or ""):
        out.add(m.replace(",", ""))
    return out


def numbers_supported(point: str, quote: str) -> tuple[bool, list[str]]:
    """True iff every number the point asserts also appears in the quote.

    Returns (ok, missing). A point with no numbers is trivially supported. The
    check errs conservative: a number present in a different surface form
    (spelled out, different units) counts as missing, so the gate drops rather
    than waves through. The ablation measures how often that costs a good point.
    """
    missing = sorted(_numbers(point) - _numbers(quote))
    return (not missing, missing)


class ContextJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    misleading: bool
    reason: str = ""


def check_context(point: str, quote: str, context: str) -> ContextJudgement | None:
    """Judge whether the point is misleading given the surrounding passage."""
    user = (
        f"Point: {point}\n\n"
        f'Cited verbatim quote:\n"{quote}"\n\n'
        f"Surrounding passage:\n{context}"
    )
    try:
        judgement, _ = llm.structured(
            system=prompts.CONTEXT_SYSTEM,
            user_message=user,
            output_schema=ContextJudgement,
            usage_context="who_speech:context",
            max_tokens=300,
        )
    except llm.StructuredOutputError:
        return None
    return judgement
