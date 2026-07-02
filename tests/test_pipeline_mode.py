"""EXP-28 architecture-ablation knob (`pipeline_mode`).

The knob must satisfy three contracts:

1. `trio` (the default) is byte-identical to production: the Verifier runs
   every round and the Adjudicator fires on retry exhaustion.
2. `researcher_only` never calls the Verifier or the Adjudicator. A real
   label at or above the D37 floor commits as `accepted_researcher_only`;
   sub-floor answers retry; exhaustion abstains as
   `abstained_researcher_only` with an `inconclusive` answer.
3. `no_adjudicator` runs the Researcher-Verifier loop unchanged but
   terminates retry exhaustion in `abstained_no_adjudicator` (the EXP-15
   design) without ever calling the Adjudicator.

All agent calls are faked; `dry_run=True` keeps the DB untouched.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.run_coordinator as rc
from agents.models import ResearcherOutput, VerifierOutput
from agents.researcher import ResearcherRunResult
from agents.verifier import VerifierRunResult


def _researcher_output(answer: str = "yes", confidence: float = 0.9) -> ResearcherOutput:
    return ResearcherOutput(
        answer=answer,
        answer_explanation="Fake explanation for the pipeline-mode test.",
        evidence_quote="A fake evidence passage long enough to validate.",
        source_url="https://www.data.gouv.fr/fake",
        retrieval_confidence=0.8,
        answer_confidence=confidence,
    )


def _researcher_result(answer: str = "yes", confidence: float = 0.9) -> ResearcherRunResult:
    return ResearcherRunResult(
        output=_researcher_output(answer, confidence),
        failure_mode=None,
        query_gen_usage=None,
        main_usage=None,
        search_queries_used=["fake query"],
        fetched_urls=["https://www.data.gouv.fr/fake"],
        search_results=[],
    )


def _verifier_result(verdict: str = "pass") -> VerifierRunResult:
    kwargs = dict(
        verdict=verdict,
        verifier_answer="yes",
        verifier_confidence=0.8,
        substring_check_result="pass",
    )
    if verdict == "fail":
        kwargs["rejection_reason"] = "fake rejection for the ablation test"
        kwargs["counter_evidence_quote"] = "fake counter evidence passage"
    return VerifierRunResult(
        output=VerifierOutput(**kwargs),
        failure_mode=None,
        query_gen_usage=None,
        main_usage=None,
    )


class _Calls:
    """Counts how often each fake agent ran."""

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
        raise AssertionError(
            "adjudicator must not run in this test unless the test "
            "replaces fake_adjudicator"
        )

    c.researcher_factory = lambda: _researcher_result()
    c.verifier_factory = lambda: _verifier_result()
    monkeypatch.setattr(rc, "run_researcher", fake_researcher)
    monkeypatch.setattr(rc, "run_verifier", fake_verifier)
    monkeypatch.setattr(rc, "run_adjudicator", fake_adjudicator)
    return c


def _coordinate(mode: str, max_retries: int = 1):
    return rc.coordinate(
        question_id="P1",
        country_code="FR",
        pipeline_mode=mode,
        max_retries=max_retries,
        experiment_id=f"test-{uuid.uuid4()}",
        condition_label=f"test-{uuid.uuid4()}",
        dry_run=True,
    )


class TestTrioDefault:
    def test_verifier_pass_commits(self, calls):
        status, output = _coordinate("trio")
        assert status == "accepted_by_verifier"
        assert output.answer == "yes"
        assert calls.researcher == 1
        assert calls.verifier == 1
        assert calls.adjudicator == 0


class TestResearcherOnly:
    def test_commit_at_floor_without_verifier(self, calls):
        status, output = _coordinate("researcher_only")
        assert status == "accepted_researcher_only"
        assert output.answer == "yes"
        assert calls.researcher == 1
        assert calls.verifier == 0
        assert calls.adjudicator == 0

    def test_sub_floor_retries_then_abstains(self, calls):
        calls.researcher_factory = lambda: _researcher_result(confidence=0.5)
        status, output = _coordinate("researcher_only", max_retries=2)
        assert status == "abstained_researcher_only"
        assert output.answer == "inconclusive"
        # attempt 0 plus max_retries retries, all sub-floor.
        assert calls.researcher == 3
        assert calls.verifier == 0
        assert calls.adjudicator == 0

    def test_inconclusive_retries_then_abstains(self, calls):
        calls.researcher_factory = (
            lambda: _researcher_result(answer="inconclusive", confidence=0.3)
        )
        status, output = _coordinate("researcher_only", max_retries=1)
        assert status == "abstained_researcher_only"
        assert output.answer == "inconclusive"
        assert calls.verifier == 0
        assert calls.adjudicator == 0


class TestNoAdjudicator:
    def test_verifier_pass_commits_normally(self, calls):
        status, output = _coordinate("no_adjudicator")
        assert status == "accepted_by_verifier"
        assert calls.verifier == 1
        assert calls.adjudicator == 0

    def test_exhaustion_abstains_instead_of_adjudicating(self, calls):
        calls.verifier_factory = lambda: _verifier_result(verdict="fail")
        status, output = _coordinate("no_adjudicator", max_retries=1)
        assert status == "abstained_no_adjudicator"
        assert output.answer == "inconclusive"
        # Verifier ran on every attempt; the Adjudicator never fired.
        assert calls.verifier == 2
        assert calls.adjudicator == 0


class TestOrchestratorFlagMap:
    def test_pipeline_mode_forwarded(self):
        from scripts.run_experiments import build_command
        exp = {
            "experiment_id": "exp28_test", "type": "accuracy",
            "baseline_knobs": {},
        }
        arm = {"condition_label": "researcher_only_s5",
               "knobs": {"pipeline_mode": "researcher_only"}}
        cmd = build_command(exp, arm, ["P1:FR"], 4)
        assert "--pipeline-mode" in cmd
        assert cmd[cmd.index("--pipeline-mode") + 1] == "researcher_only"

    def test_default_omits_pipeline_mode(self):
        from scripts.run_experiments import build_command
        exp = {
            "experiment_id": "exp28_test", "type": "accuracy",
            "baseline_knobs": {},
        }
        arm = {"condition_label": "trio_s5", "knobs": {}}
        cmd = build_command(exp, arm, ["P1:FR"], 4)
        assert "--pipeline-mode" not in cmd
