"""Phase 1: ODMI question classifier.

Takes a question + country pair, probes for evidence, and scores it on the
3-dimension rubric (Evidence Accessibility, Answer Determinism, Source Complexity).

This is deliberately simple for Phase A: a single LLM call with structured
output, not a multi-agent graph. We save the graph architecture for Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field


class AnswerabilityTier(str, Enum):
    HIGHLY_LIKELY = "Highly Likely"
    LIKELY = "Likely"
    UNLIKELY = "Unlikely"
    VERY_UNLIKELY = "Very Unlikely"

    @classmethod
    def from_composite(cls, score: int) -> AnswerabilityTier:
        if score >= 7:
            return cls.HIGHLY_LIKELY
        elif score >= 5:
            return cls.LIKELY
        elif score >= 3:
            return cls.UNLIKELY
        else:
            return cls.VERY_UNLIKELY


class RubricScore(BaseModel):
    """Structured output from the classification LLM call."""

    evidence_score: int = Field(ge=0, le=3, description="Evidence Accessibility (0-3)")
    evidence_justification: str = Field(description="Why this score for evidence accessibility")

    determinism_score: int = Field(ge=0, le=3, description="Answer Determinism (0-3)")
    determinism_justification: str = Field(description="Why this score for answer determinism")

    complexity_score: int = Field(ge=0, le=3, description="Source Complexity (0-3)")
    complexity_justification: str = Field(description="Why this score for source complexity")

    @property
    def composite(self) -> int:
        return self.evidence_score + self.determinism_score + self.complexity_score

    @property
    def tier(self) -> AnswerabilityTier:
        return AnswerabilityTier.from_composite(self.composite)


@dataclass
class ClassificationResult:
    """Full result of classifying one question against one country."""

    question_id: str
    question_text: str
    dimension: str
    country: str
    score: RubricScore
    language_used: str
    model_version: str
    prompt_version: int
    raw_response: str
    timestamp: str

    def to_db_row(self) -> dict:
        """Format for insertion into phase1_classifications table."""
        return {
            "question_id": self.question_id,
            "question_text": self.question_text,
            "dimension": self.dimension,
            "country": self.country,
            "evidence_score": self.score.evidence_score,
            "determinism_score": self.score.determinism_score,
            "complexity_score": self.score.complexity_score,
            "tier": self.score.tier.value,
            "evidence_justification": self.score.evidence_justification,
            "determinism_justification": self.score.determinism_justification,
            "complexity_justification": self.score.complexity_justification,
            "language_used": self.language_used,
            "model_version": self.model_version,
            "raw_llm_response": self.raw_response,
            "created_at": self.timestamp,
        }


# ── Prompt template ──────────────────────────────────────────
# Version 1: initial rubric prompt. Will iterate on this.

CLASSIFIER_PROMPT_V1 = """You are an expert evaluator assessing whether an AI agent system could
automatically answer questions from the EU Open Data Maturity Index (ODMI).

You are evaluating this question for the country: {country}

## The Question
{question_text}

## Your Task
Score this question on three dimensions (0-3 each). For each dimension, provide
a score AND a written justification explaining your reasoning with specific evidence.

### Dimension 1: Evidence Accessibility (0-3)
How findable is the evidence needed to answer this question via web search and
public data portals?
- 0: No online evidence exists or is accessible
- 1: Evidence exists but is hard to find (buried in PDFs, behind auth walls)
- 2: Evidence is findable with targeted search queries
- 3: Evidence is prominently published on official portals or government sites

### Dimension 2: Answer Determinism (0-3)
How objectively deterministic is the answer? Could two independent evaluators
reach the same conclusion?
- 0: Entirely subjective — requires expert judgement or insider knowledge
- 1: Mostly subjective — reasonable evaluators would likely disagree
- 2: Mostly objective — clear criteria exist but some interpretation needed
- 3: Fully objective — binary yes/no or directly verifiable from a source

### Dimension 3: Source Complexity (0-3)
How many independent sources need to be consulted and cross-referenced?
- 0: Requires synthesising 4+ sources across different domains
- 1: Requires 2-3 sources that may conflict
- 2: Requires 1-2 clearly authoritative sources
- 3: Single authoritative source provides the complete answer

## Important
- Actually attempt to find evidence for {country} before scoring. Do not guess.
- If you would use a web search, describe what you would search for and what
  you expect to find.
- Be honest about uncertainty. If you cannot determine a score confidently,
  err towards the lower score.
- Write justifications that would make sense to a dissertation examiner who
  has never seen this question before.

Respond with valid JSON matching this schema:
{{
    "evidence_score": <0-3>,
    "evidence_justification": "<your reasoning>",
    "determinism_score": <0-3>,
    "determinism_justification": "<your reasoning>",
    "complexity_score": <0-3>,
    "complexity_justification": "<your reasoning>"
}}
"""

PROMPT_REGISTRY = {
    "phase1_classifier": {
        1: CLASSIFIER_PROMPT_V1,
    }
}
