"""Tests for the _finalise_after_adjudication helper (Change 1).

The helper must:
- Return ("accepted_by_adjudicator", ResearcherOutput with answer from the
  Adjudicator) for any resolved verdict (researcher_correct / verifier_correct
  / neither), ignoring the last researcher output.
- Return ("abstained_adjudicator", last researcher output) when verdict is
  abstain or the output is None.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.models import AdjudicatorOutput, ResearcherOutput


def _make_researcher_output(answer: str = "inconclusive") -> ResearcherOutput:
    return ResearcherOutput(
        answer=answer,
        answer_explanation="some explanation",
        evidence_quote="some quote from the web page",
        source_url="https://example.com/page",
        retrieval_confidence=0.5,
        answer_confidence=0.5,
    )


def _make_adj_output(
    verdict: str,
    adj_answer: str = "yes",
    reasoning: str = "A" * 55,
    source_url: str = "https://gov.example.com/source",
    evidence_quote: str = "quote text from adjudicator",
    confidence: float = 0.8,
) -> AdjudicatorOutput:
    return AdjudicatorOutput(
        adjudicator_verdict=verdict,  # type: ignore[arg-type]
        adjudicator_answer=adj_answer if verdict != "abstain" else None,
        adjudicator_confidence=confidence,
        adjudicator_reasoning=reasoning,
        chosen_source_url=source_url,
        chosen_evidence_quote=evidence_quote,
    )


# Import the helper under test (does NOT exist yet — test should fail until
# the implementation is added to scripts/run_coordinator.py).

def _import_helper():
    # Lazy import so a missing symbol surfaces as a test failure, not an
    # import-time error that aborts the whole session.
    from scripts.run_coordinator import _finalise_after_adjudication  # type: ignore[attr-defined]
    return _finalise_after_adjudication


# Case 1: researcher_correct — must use adjudicator_answer, not the stale
# last researcher output.

def test_researcher_correct_uses_adjudicator_answer():
    helper = _import_helper()
    adj = _make_adj_output(verdict="researcher_correct", adj_answer="yes")
    last_r = _make_researcher_output(answer="inconclusive")

    status, chosen = helper(adj, [last_r])

    assert status == "accepted_by_adjudicator"
    assert chosen.answer == "yes", (
        "helper must take the adjudicator's authoritative answer, not the "
        "stale last researcher output ('inconclusive')"
    )


# Case 2: verifier_correct — must also use adjudicator_answer.

def test_verifier_correct_uses_adjudicator_answer():
    helper = _import_helper()
    adj = _make_adj_output(verdict="verifier_correct", adj_answer="no")
    last_r = _make_researcher_output(answer="yes")

    status, chosen = helper(adj, [last_r])

    assert status == "accepted_by_adjudicator"
    assert chosen.answer == "no"


# Case 3: neither — must use adjudicator_answer.

def test_neither_uses_adjudicator_answer():
    helper = _import_helper()
    adj = _make_adj_output(verdict="neither", adj_answer="not_applicable")
    last_r = _make_researcher_output(answer="yes")

    status, chosen = helper(adj, [last_r])

    assert status == "accepted_by_adjudicator"
    assert chosen.answer == "not_applicable"


# Case 4: abstain — answer downgrades to inconclusive (D37 abstain floor).

def test_abstain_writes_inconclusive():
    """The Adjudicator could not pick a winner. Don't finalise the last
    Researcher's sub-floor guess as a real commit; abstain honestly. The
    terminal status stays abstained_adjudicator.
    """
    helper = _import_helper()
    adj = AdjudicatorOutput(
        adjudicator_verdict="abstain",
        adjudicator_answer=None,
        adjudicator_confidence=0.0,
        adjudicator_reasoning="B" * 55,
    )
    last_r = _make_researcher_output(answer="no")  # a sub-floor R3 guess

    status, chosen = helper(adj, [last_r])

    assert status == "abstained_adjudicator"
    assert chosen.answer == "inconclusive"
    # Source URL / evidence carry over so the audit trail stays intact.
    assert str(chosen.source_url) == str(last_r.source_url)


# Case 5: adj_output is None — same abstain behaviour, the agent failed.

def test_none_output_writes_inconclusive():
    helper = _import_helper()
    last_r = _make_researcher_output(answer="yes")

    status, chosen = helper(None, [last_r])

    assert status == "abstained_adjudicator"
    assert chosen.answer == "inconclusive"


# Case 6: evidence_quote and source_url come from the adjudicator.

def test_resolved_verdict_copies_adjudicator_urls():
    helper = _import_helper()
    adj = _make_adj_output(
        verdict="neither",
        adj_answer="not_applicable",
        source_url="https://data.gouv.fr/adj-source",
        evidence_quote="adjudicator selected this passage",
    )
    last_r = _make_researcher_output(answer="yes")

    _, chosen = helper(adj, [last_r])

    assert "data.gouv.fr" in str(chosen.source_url)
    assert chosen.evidence_quote == "adjudicator selected this passage"


# Case 7: a sub-floor Adjudicator commit is downgraded to an abstention.
# Under the D37 commit-confidence floor we abstain rather than commit a
# low-confidence label (usually a defensive `no` on sparse evidence).

def test_subfloor_commit_downgraded_to_inconclusive():
    helper = _import_helper()
    adj = _make_adj_output(verdict="verifier_correct", adj_answer="no",
                           confidence=0.45)
    last_r = _make_researcher_output(answer="yes")

    status, chosen = helper(adj, [last_r])

    assert status == "accepted_by_adjudicator"
    assert chosen.answer == "inconclusive", (
        "a sub-0.65 Adjudicator commit must abstain, not finalise the guess"
    )


def test_above_floor_commit_is_kept():
    helper = _import_helper()
    adj = _make_adj_output(verdict="verifier_correct", adj_answer="no",
                           confidence=0.7)
    last_r = _make_researcher_output(answer="yes")

    status, chosen = helper(adj, [last_r])

    assert chosen.answer == "no", "an above-floor commit is unchanged"


# Case 9: a too-short evidence quote must not crash the pair. Evidence is a
# URL plus a quoted passage; a bare token like "yes" is below the
# ResearcherOutput min_length (10) and would otherwise raise a
# ValidationError after the adjudication has already been paid for. It is
# treated as no quote.

def test_short_evidence_quote_falls_back_not_crash():
    helper = _import_helper()
    adj = _make_adj_output(verdict="researcher_correct", adj_answer="yes",
                           evidence_quote="yes")
    last_r = _make_researcher_output(answer="yes")

    status, chosen = helper(adj, [last_r])

    assert status == "accepted_by_adjudicator"
    assert chosen.answer == "yes"
    assert len(chosen.evidence_quote) >= 10
    assert "did not provide quote" in chosen.evidence_quote


def test_empty_evidence_quote_falls_back():
    helper = _import_helper()
    adj = _make_adj_output(verdict="researcher_correct", adj_answer="yes",
                           evidence_quote="")
    last_r = _make_researcher_output(answer="yes")

    _, chosen = helper(adj, [last_r])

    assert "did not provide quote" in chosen.evidence_quote
