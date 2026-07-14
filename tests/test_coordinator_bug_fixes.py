"""Regression tests for two coordinator data-integrity bugs (EXP-36 freeze).

B1: an `invalid_answer_shape` Researcher result must be retried, not carried
    forward to the Verifier and committed as a junk `differ`.
B2: a Verifier `schema_invalid` failure on the final attempt must not throw the
    pair away as `agent_failure` when a Researcher answer is in hand; it must
    fall through to the Adjudicator, which weighs any valid prior Verifier
    verdicts (or abstains honestly if there are none).

All agent calls are faked and `dry_run=True` keeps the DB untouched, mirroring
tests/test_pipeline_mode.py.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.run_coordinator as rc
from agents.adjudicator import AdjudicatorRunResult
from agents.models import AdjudicatorOutput, ResearcherOutput, VerifierOutput
from agents.researcher import ResearcherRunResult
from agents.verifier import VerifierRunResult


def _researcher_output(answer: str = "yes", confidence: float = 0.9) -> ResearcherOutput:
    return ResearcherOutput(
        answer=answer,
        answer_explanation="Fake explanation long enough to validate.",
        evidence_quote="A fake evidence passage long enough to validate.",
        source_url="https://www.data.gouv.fr/fake",
        retrieval_confidence=0.8,
        answer_confidence=confidence,
    )


def _researcher_result(
    answer: str = "yes", confidence: float = 0.9, failure_mode=None
) -> ResearcherRunResult:
    return ResearcherRunResult(
        output=_researcher_output(answer, confidence),
        failure_mode=failure_mode,
        query_gen_usage=None,
        main_usage=None,
        search_queries_used=["fake query"],
        fetched_urls=["https://www.data.gouv.fr/fake"],
        search_results=[],
    )


def _verifier_pass() -> VerifierRunResult:
    return VerifierRunResult(
        output=VerifierOutput(
            verdict="pass", verifier_answer="yes",
            verifier_confidence=0.8, substring_check_result="pass",
        ),
        failure_mode=None, query_gen_usage=None, main_usage=None,
    )


def _verifier_fail() -> VerifierRunResult:
    return VerifierRunResult(
        output=VerifierOutput(
            verdict="fail", verifier_answer="yes", verifier_confidence=0.8,
            substring_check_result="pass",
            rejection_reason="fake rejection for the bug-fix test",
            counter_evidence_quote="fake counter evidence passage",
        ),
        failure_mode=None, query_gen_usage=None, main_usage=None,
    )


def _verifier_schema_invalid() -> VerifierRunResult:
    """What run_verifier returns when the Verifier output fails its schema."""
    return VerifierRunResult(
        output=None, failure_mode="schema_invalid",
        query_gen_usage=None, main_usage=None,
    )


def _adjudicator_commit() -> AdjudicatorRunResult:
    return AdjudicatorRunResult(
        output=AdjudicatorOutput(
            adjudicator_verdict="researcher_correct",
            adjudicator_answer="no",
            adjudicator_confidence=0.9,
            adjudicator_reasoning=(
                "Fake adjudication reasoning long enough to satisfy the "
                "fifty character minimum length requirement."
            ),
        ),
        failure_mode=None, usage=None,
    )


class _Calls:
    def __init__(self):
        self.researcher = 0
        self.verifier = 0
        self.adjudicator = 0


@pytest.fixture()
def calls(monkeypatch):
    c = _Calls()

    def fake_researcher(inp, **kwargs):
        c.researcher += 1
        return c.researcher_factory()

    def fake_verifier(inp, **kwargs):
        c.verifier += 1
        return c.verifier_factory()

    def fake_adjudicator(inp, **kwargs):
        c.adjudicator += 1
        return c.adjudicator_factory()

    c.researcher_factory = lambda: _researcher_result()
    c.verifier_factory = lambda: _verifier_pass()
    c.adjudicator_factory = lambda: _adjudicator_commit()
    monkeypatch.setattr(rc, "run_researcher", fake_researcher)
    monkeypatch.setattr(rc, "run_verifier", fake_verifier)
    monkeypatch.setattr(rc, "run_adjudicator", fake_adjudicator)
    return c


def _coordinate(max_retries: int = 1):
    return rc.coordinate(
        question_id="P1",
        country_code="FR",
        pipeline_mode="trio",
        max_retries=max_retries,
        experiment_id=f"test-{uuid.uuid4()}",
        condition_label=f"test-{uuid.uuid4()}",
        dry_run=True,
    )


def test_invalid_answer_shape_retries_and_never_commits(calls):
    """B1: a shape-invalid Researcher answer must retry, never reach the Verifier,
    and never commit as a junk result."""
    calls.researcher_factory = lambda: _researcher_result(
        failure_mode="invalid_answer_shape"
    )
    status, _output = _coordinate(max_retries=1)
    assert calls.verifier == 0, "shape-invalid answer must not reach the Verifier"
    assert status == "agent_failure", (
        f"shape-invalid answer must not commit; got status={status!r}"
    )


def test_verifier_schema_invalid_final_attempt_adjudicates(calls):
    """B2: a final-attempt Verifier schema failure must adjudicate on the answer
    already in hand, not drop the pair as agent_failure."""
    seq = iter([_verifier_fail(), _verifier_schema_invalid()])
    calls.verifier_factory = lambda: next(seq)
    status, _output = _coordinate(max_retries=1)
    assert calls.adjudicator == 1, (
        "a Researcher answer was in hand; the Adjudicator must run"
    )
    assert status != "agent_failure", (
        f"pair must not be dropped as agent_failure; got status={status!r}"
    )
