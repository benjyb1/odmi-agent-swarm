"""The speech-writer swarm: researcher -> verifier -> adjudicator.

Forked from the ODMI swarm's shape and reusing its LLM plumbing
(`agents.tools.llm.call_for_structured`, which logs receipts to
claude_usage_log), but with speech-specific schemas and prompts and a closed
corpus instead of web search.

The defensibility spine is a deterministic quote-gate: the researcher must
return a verbatim quote, and a point is dropped unless that quote is found,
character for character (whitespace-normalised), in the passage the researcher
actually read. The verifier then judges whether the point overreaches the
quote, and the adjudicator dedupes and curates, abstaining when nothing solid
survives.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict, Field

from who_speech import config, prompts

if TYPE_CHECKING:
    from who_speech.search import Passage, Retriever

# The five demo queries (breadth across countries and activities).
QUERIES: dict[str, str] = {
    "ukraine_emergency": "What has WHO done to support Ukraine's health system and refugees during the war?",
    "kazakhstan_phc": "What has WHO done with Kazakhstan to strengthen primary health care?",
    "kyrgyzstan_financing": "What has WHO done on hospital payment and health financing reform in Kyrgyzstan?",
    "north_macedonia_protection": "What does WHO's evidence say about out-of-pocket health spending and financial protection in North Macedonia?",
    "tajikistan_rehab": "What has WHO done to support rehabilitation and assistive technology in Tajikistan?",
}


# --- structured-output schemas ----------------------------------------------

class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aspects: list[str] = Field(default_factory=list)


class DraftedPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: bool
    point: str = ""
    verbatim_quote: str = ""
    passage_index: int = -1
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class VerifierJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: bool
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Adjudication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keep_indices: list[int] = Field(default_factory=list)
    abstain: bool = False
    reason: str = ""


@dataclass
class BriefingPoint:
    point: str
    quote: str
    citation: str
    iris_url: str
    page: int
    confidence: float
    verifier_reason: str = ""


@dataclass
class BriefingPack:
    query: str
    points: list[BriefingPoint]
    abstained: bool
    note: str = ""


# --- quote-gate (deterministic, the anti-hallucination spine) ----------------

def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def quote_in_passage(quote: str, passage: str, min_len: int = 15) -> bool:
    """True iff the verbatim quote appears in the passage the researcher read.

    Whitespace-normalised and case-folded so a real quote is not failed on
    trivial reflow, but a paraphrase (different words) still fails.
    """
    if len(quote.strip()) < min_len:
        return False
    return _norm(quote) in _norm(passage)


# --- agents (each a thin call_for_structured wrapper) ------------------------

def _passage_block(passages: list["Passage"]) -> str:
    lines = []
    for i, p in enumerate(passages):
        lines.append(f"[{i}] (p.{p.page_start}, {p.citation})\n{p.text}")
    return "\n\n".join(lines)


def plan_research(query: str) -> list[str]:
    from agents.tools.llm import call_for_structured

    plan, _ = call_for_structured(
        system=prompts.PLANNER_SYSTEM,
        user_message=f"Question: {query}",
        output_schema=ResearchPlan,
        usage_context="who_speech:plan",
        max_tokens=500,
    )
    return [a.strip() for a in plan.aspects if a.strip()]


def draft_point(query: str, aspect: str, passages: list["Passage"]) -> Optional[DraftedPoint]:
    from agents.tools.llm import StructuredOutputError, call_for_structured

    if not passages:
        return None
    user = (
        f"Question: {query}\nSub-topic: {aspect}\n\n"
        f"Candidate passages:\n{_passage_block(passages)}"
    )
    try:
        draft, _ = call_for_structured(
            system=prompts.RESEARCHER_SYSTEM,
            user_message=user,
            output_schema=DraftedPoint,
            usage_context="who_speech:researcher",
            max_tokens=700,
        )
    except StructuredOutputError:
        return None
    return draft


def verify_point(point: str, quote: str) -> Optional[VerifierJudgement]:
    from agents.tools.llm import StructuredOutputError, call_for_structured

    user = f"Speaking point: {point}\n\nCited verbatim quote:\n\"{quote}\""
    try:
        judgement, _ = call_for_structured(
            system=prompts.VERIFIER_SYSTEM,
            user_message=user,
            output_schema=VerifierJudgement,
            usage_context="who_speech:verifier",
            max_tokens=400,
        )
    except StructuredOutputError:
        return None
    return judgement


def adjudicate(query: str, candidates: list[BriefingPoint]) -> Adjudication:
    from agents.tools.llm import StructuredOutputError, call_for_structured

    if not candidates:
        return Adjudication(keep_indices=[], abstain=True, reason="no verified points")
    listed = "\n\n".join(
        f"[{i}] {c.point}\n    quote: \"{c.quote[:200]}\"\n    source: {c.citation}"
        for i, c in enumerate(candidates)
    )
    user = f"Question: {query}\n\nVerified points:\n{listed}"
    try:
        result, _ = call_for_structured(
            system=prompts.ADJUDICATOR_SYSTEM,
            user_message=user,
            output_schema=Adjudication,
            usage_context="who_speech:adjudicator",
            max_tokens=500,
        )
    except StructuredOutputError:
        # On adjudicator failure, fall back to keeping all (verified) points.
        return Adjudication(keep_indices=list(range(len(candidates))), abstain=False,
                            reason="adjudicator parse failure; kept all verified")
    return result


# --- orchestration -----------------------------------------------------------

def orchestrate(query: str, retriever: "Retriever", *, verbose: bool = True) -> BriefingPack:
    aspects = plan_research(query)
    if verbose:
        print(f"plan: {len(aspects)} aspects")
        for a in aspects:
            print(f"  - {a}")

    verified: list[BriefingPoint] = []
    for aspect in aspects:
        passages = retriever.retrieve(aspect, k=config.PASS_TO_LLM)
        draft = draft_point(query, aspect, passages)
        if not draft or not draft.supported:
            if verbose:
                print(f"[abstain] {aspect[:60]}")
            continue
        if not (0 <= draft.passage_index < len(passages)):
            continue
        source = passages[draft.passage_index]

        # Deterministic quote-gate against the passage actually read.
        if not quote_in_passage(draft.verbatim_quote, source.text):
            if verbose:
                print(f"[quote-gate FAIL] {aspect[:50]} (quote not verbatim)")
            continue

        judgement = verify_point(draft.point, draft.verbatim_quote)
        if not judgement or not judgement.supported:
            if verbose:
                reason = judgement.reason[:60] if judgement else "verifier error"
                print(f"[verifier reject] {aspect[:40]}: {reason}")
            continue
        if judgement.confidence < config.ABSTAIN_SCORE_FLOOR:
            continue

        verified.append(
            BriefingPoint(
                point=draft.point,
                quote=draft.verbatim_quote,
                citation=source.citation,
                iris_url=source.iris_url,
                page=source.page_start,
                confidence=min(draft.confidence, judgement.confidence),
                verifier_reason=judgement.reason,
            )
        )

    decision = adjudicate(query, verified)
    if decision.abstain:
        return BriefingPack(query=query, points=[], abstained=True, note=decision.reason)
    kept = [verified[i] for i in decision.keep_indices if 0 <= i < len(verified)]
    return BriefingPack(query=query, points=kept, abstained=not kept, note=decision.reason)


def print_pack(pack: BriefingPack) -> None:
    print(f"\n{'=' * 78}\nQUERY: {pack.query}\n{'=' * 78}")
    if pack.abstained or not pack.points:
        print(f"\n(abstained — {pack.note or 'no defensible points found'})\n")
        return
    for i, p in enumerate(pack.points, 1):
        print(f"\n{i}. {p.point}  [{p.confidence:.2f}]")
        print(f'   "{p.quote}"')
        print(f"   {p.citation}")
        print(f"   {p.iris_url} (p.{p.page})")


if __name__ == "__main__":
    import sys

    from who_speech.search import Retriever

    key = sys.argv[1] if len(sys.argv) > 1 else "kyrgyzstan_financing"
    query = QUERIES.get(key, key)
    db_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/who_lancedb"

    retriever = Retriever(db_path)
    pack = orchestrate(query, retriever)
    print_pack(pack)
