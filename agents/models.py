"""Pydantic contracts for every agent in the ODMI swarm.

One file because the contracts are tightly coupled: the Researcher's
output is the Verifier's input, the Coordinator's state references
both. Split into per-agent modules if this file exceeds 500 lines.

Versioning: any breaking change to these contracts requires a numbered
decision in `docs/SPEC.md` (the schema in `scripts/setup_sqlite.py`
must move with this file). Treat these classes as the source of truth
for what every agent emits.

See `docs/AGENT_DESIGN.md` for the full atomic specification of each
agent that produces these objects.
"""

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

# Type aliases the agents share.

# Per D28, the answer field is no longer a fixed Literal because each
# question has its own answer shape (binary / percentage_band /
# ordinal_magnitude / count_band / categorical) and the band-shape
# rubrics carry per-question allowed values. Pydantic validation on
# `answer` is therefore just a length sanity check; semantic
# validation against the question's `allowed_answers` happens in
# `agents.tools.answer_shapes.is_valid_answer` after the call returns.
#
# `LegacyAnswerLiteral` is retained for documentation / search
# (so old SPEC references resolve) but is no longer enforced.
LegacyAnswerLiteral = Literal[
    "yes", "no", "other", "not_applicable", "inconclusive"
]
RubricTier = Literal["Highly Likely", "Likely", "Unlikely", "Very Unlikely"]
LanguageRoute = Literal["native", "deepl", "human_required"]
VerifierStrategy = Literal[
    "verifier-disprove",
    "verifier-negation",
    "verifier-steelman",
    "verifier-blind",
]
VerifierVerdict = Literal["pass", "fail"]
SubstringCheckResult = Literal["pass", "fail", "not_attempted"]
AdjudicatorVerdict = Literal[
    "researcher_correct",
    "verifier_correct",
    "neither",
    "escalate_human",
]
TerminalStatus = Literal[
    "accepted_by_verifier",
    "accepted_by_adjudicator",
    "escalated_captcha",
    "escalated_adjudicator",
    "agent_failure",
]

# URL string with light validation. The strict HttpUrl is too brittle
# for the messy URLs that come back from search snippets and government
# portals. AnyHttpUrl allows IP-based and unusual TLDs that strict URL
# rejection has tripped on in pilots elsewhere.
UrlStr = Annotated[AnyHttpUrl, Field(...)]


# ============================================================
# LLM call usage record (D12). Every Claude call emits one.
# ============================================================


class LLMUsage(BaseModel):
    """Cost and timing record for a single LLM call.

    Populated by the LLM wrapper and threaded back to the caller so the
    caller can stamp the database row with these fields.
    """

    model_config = ConfigDict(extra="forbid")

    input_tokens: int
    output_tokens: int
    wall_clock_ms: int
    estimated_cost_usd: Optional[float] = None
    model_version: str
    prompt_version_id: Optional[int] = None
    condition_label: Optional[str] = None
    raw_response: Optional[str] = None


# ============================================================
# Researcher (AGENT_DESIGN section 3)
# ============================================================


class VerifierFeedback(BaseModel):
    """Carried from a previous Verifier rejection back into the next
    Researcher attempt. Empty on the first attempt.
    """

    model_config = ConfigDict(extra="forbid")

    rejection_reason: str
    suggested_search_query: Optional[str] = None
    failed_source_url: Optional[AnyHttpUrl] = None


class ResearcherInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    question_text: str
    dimension: str
    indicator: str
    response_scoring: str
    country_code: str
    country_name: str
    country_language: str
    portal_url: Optional[AnyHttpUrl] = None
    verifier_feedback: Optional[VerifierFeedback] = None

    # D28: per-question answer shape and the list of canonical labels
    # the agent may emit. `inconclusive` and `not_applicable` are
    # always permitted on top of this list (see
    # `agents.tools.answer_shapes`).
    answer_shape: str = "binary"
    allowed_answers: List[str] = Field(default_factory=lambda: ["yes", "no"])

    # Queries the Researcher ran on previous attempts for this pair.
    # Carried through on retries so the query generator can diverge
    # from already-tried phrasings (Change 2).
    previous_search_queries: List[str] = Field(default_factory=list)


class ResearcherOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(..., min_length=1, max_length=200)
    answer_explanation: str = Field(..., min_length=1)
    evidence_quote: str = Field(..., min_length=10)
    source_url: AnyHttpUrl
    retrieval_confidence: float = Field(..., ge=0.0, le=1.0)
    answer_confidence: float = Field(..., ge=0.0, le=1.0)
    search_queries_used: List[str] = Field(default_factory=list)
    fetched_urls: List[AnyHttpUrl] = Field(default_factory=list)
    domain_trust_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    language_route_used: LanguageRoute = "native"
    notes: Optional[str] = None


# ============================================================
# Adversarial Verifier (AGENT_DESIGN section 4)
# ============================================================


class VerifierInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    question_text: str
    country_code: str
    country_name: str
    researcher_output: ResearcherOutput
    strategy: VerifierStrategy = "verifier-disprove"

    # D28: shape + allowed labels copied from the question row so the
    # Verifier knows which counter-answers are admissible.
    answer_shape: str = "binary"
    allowed_answers: List[str] = Field(default_factory=lambda: ["yes", "no"])


class VerifierOutput(BaseModel):
    """Verifier returns one of two top-level shapes determined by
    `verdict`. The `model_validator` below enforces the conditional
    required fields so the Coordinator does not have to.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: VerifierVerdict
    verifier_answer: str = Field(..., min_length=1, max_length=200)
    verifier_confidence: float = Field(..., ge=0.0, le=1.0)

    substring_check_result: SubstringCheckResult
    substring_check_notes: Optional[str] = None

    independent_search_queries: List[str] = Field(default_factory=list)
    independent_evidence_snippets: List[str] = Field(default_factory=list)

    rejection_reason: Optional[str] = None
    counter_evidence_quote: Optional[str] = None
    counter_source_url: Optional[AnyHttpUrl] = None
    suggested_search_query: Optional[str] = None

    @model_validator(mode="after")
    def _enforce_rejection_fields(self) -> "VerifierOutput":
        if self.verdict == "fail":
            if not self.rejection_reason:
                raise ValueError(
                    "rejection_reason is required when verdict='fail'"
                )
            if not self.counter_evidence_quote and not self.counter_source_url:
                raise ValueError(
                    "counter_evidence_quote or counter_source_url is required "
                    "when verdict='fail'"
                )
        return self


# ============================================================
# Adjudicator (AGENT_DESIGN section 5.11)
# ============================================================


class AdjudicatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    question_text: str
    country_code: str
    country_name: str
    researcher_outputs: List[ResearcherOutput]
    verifier_outputs: List[VerifierOutput]

    # D28: shape + allowed labels copied from the question row.
    answer_shape: str = "binary"
    allowed_answers: List[str] = Field(default_factory=lambda: ["yes", "no"])


class AdjudicatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adjudicator_verdict: AdjudicatorVerdict
    adjudicator_answer: Optional[str] = Field(default=None, max_length=200)
    adjudicator_confidence: float = Field(..., ge=0.0, le=1.0)
    adjudicator_reasoning: str = Field(..., min_length=50)
    chosen_source_url: Optional[AnyHttpUrl] = None
    chosen_evidence_quote: Optional[str] = None

    @model_validator(mode="after")
    def _enforce_winner_fields(self) -> "AdjudicatorOutput":
        # If we pick a winner, we need an answer to record.
        picks_winner = self.adjudicator_verdict in (
            "researcher_correct",
            "verifier_correct",
            "neither",
        )
        if picks_winner and self.adjudicator_answer is None:
            raise ValueError(
                "adjudicator_answer is required when adjudicator_verdict "
                "is not 'escalate_human'"
            )
        return self


# ============================================================
# Hand-marks (D8/D9 audit-trail). CSV-row equivalent.
# ============================================================


class HandMark(BaseModel):
    """One row in `data/hand_marks/<country>_handmarks.csv`. The
    `data/hand_marks/PROTOCOL.md` document is the human-facing
    specification; this class is the programmatic mirror.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: str
    country_code: str

    evidence_score: int = Field(..., ge=0, le=3)
    evidence_justification: str
    determinism_score: int = Field(..., ge=0, le=3)
    determinism_justification: str
    complexity_score: int = Field(..., ge=0, le=3)
    complexity_justification: str
    composite_score: int = Field(..., ge=0, le=9)
    tier: RubricTier

    search_queries: Optional[str] = None
    sources_found: Optional[str] = None
    answer_obtained: Optional[str] = None

    marker: str
    marked_at: str
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _composite_matches_dimensions(self) -> "HandMark":
        expected = (
            self.evidence_score
            + self.determinism_score
            + self.complexity_score
        )
        if self.composite_score != expected:
            raise ValueError(
                f"composite_score {self.composite_score} does not equal "
                f"sum of dimensions {expected}"
            )
        return self
