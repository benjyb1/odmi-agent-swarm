"""Tests for the D44 no-on-absence rule.

D44: the Adjudicator must not commit a negative ('no') label that rests on
absence of evidence (no supporting quote); it abstains ('inconclusive')
instead. The prompt is the primary guard; a structural backstop in
_finalise_after_adjudication catches an unsupported negative commit.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.models import AdjudicatorOutput, ResearcherOutput
from scripts.run_coordinator import _finalise_after_adjudication


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
    # Above the 0.65 floor, so the D37 floor does NOT catch it; the D44
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
