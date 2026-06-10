"""Tests for the D44 verifier-pass-trust and D45 no-on-absence rules.

D44: a Verifier `pass` is accepted when the Verifier itself is confident,
even if the Researcher under-rated its own answer below the commit floor.
D45: the Adjudicator must not commit a negative ('no') label that rests on
absence of evidence (no supporting quote); it abstains instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.models import AdjudicatorOutput, ResearcherOutput
from scripts.run_coordinator import (
    _finalise_after_adjudication,
    _should_accept_verifier_pass,
)


# --- D44: verifier-pass-trust -------------------------------------------

def test_pass_trusted_when_verifier_confident_even_if_researcher_subfloor():
    # Researcher under-rated (0.62), Verifier passed at 0.72 -> accept (PT26).
    assert _should_accept_verifier_pass("pass", "yes", 0.62, 0.72) is True


def test_pass_rejected_when_both_subfloor():
    assert _should_accept_verifier_pass("pass", "yes", 0.50, 0.50) is False


def test_pass_accepted_on_researcher_confidence_alone():
    assert _should_accept_verifier_pass("pass", "yes", 0.90, None) is True


def test_fail_verdict_never_accepted_even_if_confident():
    assert _should_accept_verifier_pass("fail", "yes", 0.9, 0.9) is False


def test_abstention_never_accepted():
    assert _should_accept_verifier_pass("pass", "inconclusive", 0.9, 0.9) is False


# --- D45: no-on-absence backstop ----------------------------------------

def _r(answer: str = "yes") -> ResearcherOutput:
    return ResearcherOutput(
        answer=answer,
        answer_explanation="a researcher explanation",
        evidence_quote="some web page quote",
        source_url="https://example.com/p",
        retrieval_confidence=0.5,
        answer_confidence=0.5,
    )


def test_no_without_supporting_quote_abstains():
    # Above the 0.65 floor, so the D37 floor does NOT catch it; the D45
    # backstop must downgrade the unsupported 'no' to inconclusive.
    adj = AdjudicatorOutput(
        adjudicator_verdict="verifier_correct",
        adjudicator_answer="no",
        adjudicator_confidence=0.7,
        adjudicator_reasoning="z" * 55,
        chosen_source_url=None,
        chosen_evidence_quote="",
    )
    _, chosen = _finalise_after_adjudication(adj, [_r()])
    assert chosen.answer == "inconclusive"


def test_no_with_supporting_quote_is_kept():
    adj = AdjudicatorOutput(
        adjudicator_verdict="verifier_correct",
        adjudicator_answer="no",
        adjudicator_confidence=0.7,
        adjudicator_reasoning="z" * 55,
        chosen_source_url="https://gov.example/x",
        chosen_evidence_quote="the portal explicitly has no SPARQL endpoint",
    )
    _, chosen = _finalise_after_adjudication(adj, [_r()])
    assert chosen.answer == "no"
