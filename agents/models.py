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
# D53: `unsupported` (renamed from `human_required`) is the route when
# neither native Claude reading nor DeepL can handle the language. There
# is no human-translation stage; such a pair abstains. Never set in any
# logged run to date (every row is `native`).
LanguageRoute = Literal["native", "deepl", "unsupported"]
VerifierStrategy = Literal[
    "verifier-disprove",
    "verifier-negation",
    "verifier-steelman",
    "verifier-blind",
    # EXP-11 tristate arms. Additive: production runs the four above; the
    # two below are exercised only by evaluation/verifier_redesign.py and
    # write no phase2_verifier_runs rows, so the DB CHECK is untouched.
    "verifier-tristate",
    "verifier-tristate-probes",
]
VerifierVerdict = Literal["pass", "fail"]
# EXP-11 P1: a verdict that separates "found counter-evidence" (refute)
# from "searched, found nothing decisive" (inconclusive) from "found
# corroboration" (confirm). Only the extremes carry a consequence, and
# only when their quote clears the deterministic gate.
TristateVerdict = Literal["refute", "inconclusive", "confirm"]
SubstringCheckResult = Literal["pass", "fail", "not_attempted"]
AdjudicatorVerdict = Literal[
    "researcher_correct",
    "verifier_correct",
    "neither",
    # D51: the Adjudicator declines to commit a label because the case is
    # too uncertain to settle on the evidence gathered. Renamed from the
    # old `escalate_human`: no human is ever in the loop in this automated
    # swarm, so the verdict is an abstention, not an escalation. Legacy
    # rows keep `escalate_human` and the DB CHECK still accepts it, but no
    # new run emits it.
    "abstain",
    # EXP-16 free-selection arm only. `researcher_correct` is pinned to the
    # Researcher's FINAL attempt, so it cannot commit an earlier attempt that
    # happened to be right. `attempt_correct` lets the Adjudicator name ANY of
    # the up-to-four attempts by index (`chosen_attempt`). Never emitted in the
    # standard arm: the standard system prompt does not mention it, so the
    # registered phase2_adjudicator prompt is unchanged for production.
    "attempt_correct",
]
TerminalStatus = Literal[
    "accepted_by_verifier",
    "accepted_by_adjudicator",
    # D52: the swarm has no human-review stage. A pair that cannot be
    # settled abstains; these are the abstention dispositions, renamed
    # from the old `escalated_*` (which implied a handoff to a human that
    # never existed). Legacy rows keep `escalated_*` and the DB CHECK
    # still accepts them.
    "abstained_captcha",
    "abstained_adjudicator",
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


class EvidenceItem(BaseModel):
    """One piece of evidence gathered during a pair's investigation.

    Used only by the EXP-7 chained retry arm to accumulate everything the
    Researcher and Verifier turned up across rounds and carry it forward.
    The baseline (independent-retry) loop never builds these, so the
    corpus is empty and every prompt is byte-identical to the pre-EXP-7
    behaviour. See `docs/EXPERIMENTS_CHAINING.md`.
    """

    model_config = ConfigDict(extra="forbid")

    snippet: str
    source_url: Optional[str] = None
    # Which agent surfaced this evidence, and on which retry round.
    origin: Literal["researcher", "verifier"] = "researcher"
    round_index: int = 0


class VerifierFeedback(BaseModel):
    """Carried from a previous Verifier rejection back into the next
    Researcher attempt. Empty on the first attempt.
    """

    model_config = ConfigDict(extra="forbid")

    rejection_reason: str
    suggested_search_query: Optional[str] = None
    failed_source_url: Optional[AnyHttpUrl] = None

    # EXP-7 (chained arm only): the Verifier's own counter-evidence handed
    # back to the Researcher, not just the verdict and a suggested query.
    # Both default None, so the baseline loop never sets them and the
    # Researcher prompt blocks below render nothing extra.
    counter_evidence_quote: Optional[str] = None
    counter_source_url: Optional[AnyHttpUrl] = None


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

    # EXP-7 (chained arm only): every piece of evidence gathered on prior
    # rounds by both the Researcher and the Verifier, carried forward so a
    # later round sees everything found so far. Empty in the baseline loop,
    # so the Researcher prompt renders no extra block and behaviour is
    # byte-identical. See `docs/EXPERIMENTS_CHAINING.md`.
    prior_evidence: List["EvidenceItem"] = Field(default_factory=list)


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

    # The search-result snippets the Researcher actually read. Persisted
    # for reproducibility and threaded to the Verifier so the substring
    # check can verify the evidence_quote against what the Researcher saw
    # rather than re-fetching the live page (which 403s ~67% of the time).
    researcher_snippets: List[str] = Field(default_factory=list)


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
# EXP-11 tristate verifier (P1/P2). Additive: evaluation-only.
# ============================================================


class ProbeFinding(BaseModel):
    """One confirmation-probe result the tristate-probes verifier reports
    for an absence claim. `found` is the model's judgement that the probe
    surfaced the positive thing (the feature, API, instrument); `quote`
    is the supporting passage when found."""

    model_config = ConfigDict(extra="forbid")

    query: str
    found: bool
    quote: Optional[str] = None


class VerifierOutputTristate(BaseModel):
    """Tristate verdict output (EXP-11 P1).

    Mirrors VerifierOutput but replaces the binary verdict with
    refute / inconclusive / confirm. The required-field rules encode the
    burden of proof: a refute must carry counter-evidence, a confirm must
    carry corroboration. `inconclusive` is the unpenalised default and
    needs nothing. The deterministic gate (the harness, not this model)
    later downgrades a refute or confirm whose quote does not verify.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: TristateVerdict
    verifier_answer: str = Field(..., min_length=1, max_length=200)
    verifier_confidence: float = Field(..., ge=0.0, le=1.0)

    substring_check_result: SubstringCheckResult
    substring_check_notes: Optional[str] = None

    independent_search_queries: List[str] = Field(default_factory=list)
    independent_evidence_snippets: List[str] = Field(default_factory=list)

    # refute fields
    rejection_reason: Optional[str] = None
    counter_evidence_quote: Optional[str] = None
    counter_source_url: Optional[AnyHttpUrl] = None
    suggested_search_query: Optional[str] = None

    # confirm fields
    corroborating_quote: Optional[str] = None
    corroborating_url: Optional[AnyHttpUrl] = None

    # absence protocol (tristate-probes only)
    probe_findings: Optional[List[ProbeFinding]] = None

    @model_validator(mode="after")
    def _enforce_verdict_fields(self) -> "VerifierOutputTristate":
        if self.verdict == "refute":
            if not self.rejection_reason:
                raise ValueError("rejection_reason is required when verdict='refute'")
            if not self.counter_evidence_quote and not self.counter_source_url:
                raise ValueError(
                    "counter_evidence_quote or counter_source_url is required "
                    "when verdict='refute'"
                )
        if self.verdict == "confirm":
            if not self.corroborating_quote and not self.corroborating_url:
                raise ValueError(
                    "corroborating_quote or corroborating_url is required "
                    "when verdict='confirm'"
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

    # EXP-7 (chained arm only): the accumulated evidence corpus from every
    # round, so the Adjudicator synthesises over the whole investigation
    # rather than just the per-attempt summaries. Empty in the baseline
    # loop, so the Adjudicator prompt renders no extra block.
    evidence_corpus: List["EvidenceItem"] = Field(default_factory=list)


class AdjudicatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adjudicator_verdict: AdjudicatorVerdict
    adjudicator_answer: Optional[str] = Field(default=None, max_length=200)
    adjudicator_confidence: float = Field(..., ge=0.0, le=1.0)
    adjudicator_reasoning: str = Field(..., min_length=50)
    chosen_source_url: Optional[AnyHttpUrl] = None
    chosen_evidence_quote: Optional[str] = None

    # EXP-16 free-selection arm only. 1-based index of the Researcher attempt
    # whose answer the Adjudicator commits when the verdict is
    # `attempt_correct`. None in every standard-arm run, so the default-mode
    # schema and finalisation are unchanged.
    chosen_attempt: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _enforce_winner_fields(self) -> "AdjudicatorOutput":
        # If we pick a winner, we need an answer to record.
        picks_winner = self.adjudicator_verdict in (
            "researcher_correct",
            "verifier_correct",
            "neither",
            "attempt_correct",
        )
        if picks_winner and self.adjudicator_answer is None:
            raise ValueError(
                "adjudicator_answer is required when adjudicator_verdict "
                "is not 'abstain'"
            )
        # EXP-16: an attempt_correct verdict must name which attempt.
        if (
            self.adjudicator_verdict == "attempt_correct"
            and self.chosen_attempt is None
        ):
            raise ValueError(
                "chosen_attempt (1-based) is required when adjudicator_verdict "
                "is 'attempt_correct'"
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
