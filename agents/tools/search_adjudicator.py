"""Higher-order judge for the DIY-vs-Tavily search evaluation.

adjudicate() asks an Opus-tier model to compare two blind evidence sets
against an ODMI question's verified answer and pick a winner (or tie /
both_fail). The evaluation harness (evaluation/diy_vs_tavily.py) calls this
twice per pair with positions swapped to control position bias.

This is an evaluation tool, not part of the live swarm.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from agents.models import LLMUsage
from agents.prompts import search_adjudicator as prompt
from agents.tools.db import ensure_prompt_version
from agents.tools.llm import call_for_structured

# The user asked for "a higher-order adjudicator like you": run the judge on
# an Opus-tier model, not the swarm's default Sonnet. Kept in agents.tools.llm
# PRICING so the cost receipt computes.
ADJUDICATOR_MODEL = "claude-opus-4-6"


class AdjudicationResult(BaseModel):
    """One blind pairwise verdict from the search adjudicator."""

    winner: Literal["A", "B", "tie", "both_fail"]
    answer_supported_by_a: str = Field(
        ..., description="What answer System A's evidence supports."
    )
    answer_supported_by_b: str = Field(
        ..., description="What answer System B's evidence supports."
    )
    reasoning: str
    confidence: float = Field(..., ge=0.0, le=1.0)


def _equalise_counts(
    a: List[dict], b: List[dict]
) -> tuple[List[dict], List[dict]]:
    """Truncate both evidence lists to min(len(a), len(b)), top-ranked first.

    A blind judge could guess the provider from one arm simply having more
    passages than the other. Passages arrive already ranked best-first, so we
    keep the top n of each and preserve their order. Returns new lists; the
    inputs are not mutated.
    """
    n = min(len(a), len(b))
    return a[:n], b[:n]


def adjudicate(
    *,
    question_text: str,
    ground_truth: str,
    evidence_a: List[dict],
    evidence_b: List[dict],
    model: str = ADJUDICATOR_MODEL,
    subtrio_id: Optional[str] = None,
) -> tuple[AdjudicationResult, LLMUsage]:
    """Judge which blind evidence set better supports the correct answer.

    evidence_a / evidence_b are lists of {url, snippet, ...} dicts. The
    caller controls which provider occupies A vs B (and should swap them
    across two calls to control position bias).
    """
    prompt_version_id = ensure_prompt_version(
        prompt.NAME, prompt.VERSION, prompt.SYSTEM, prompt.DESCRIPTION,
    )
    # Normalise before formatting so the rendered blocks carry no provider
    # fingerprint: equal passage count here, registrable-domain URLs (and no
    # score) in the renderer.
    evidence_a, evidence_b = _equalise_counts(evidence_a, evidence_b)
    user_message = prompt.build_user_message(
        question_text=question_text,
        ground_truth=ground_truth,
        evidence_a=evidence_a,
        evidence_b=evidence_b,
    )
    return call_for_structured(
        system=prompt.SYSTEM,
        user_message=user_message,
        output_schema=AdjudicationResult,
        model=model,
        max_tokens=1200,
        condition_label="search_adjudication",
        prompt_version_id=prompt_version_id,
        usage_context="search_adjudicate",
        subtrio_id=subtrio_id,
    )
