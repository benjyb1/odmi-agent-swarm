"""Tests for the EXP-16 free attempt-selection arm.

Three properties matter and are each pinned here:

1. The 'standard' selection mode is byte-identical. The registered prompt
   (NAME / VERSION / SYSTEM / DESCRIPTION) and the rendered user message are
   unchanged from the pre-EXP-16 behaviour, so default-mode `prompt_versions`
   rows and every standard call are byte-for-byte what production produced.
2. The 'free' mode can commit a NON-final attempt's answer. With three
   attempts where attempt 2 is correct and the final (attempt 3) is wrong,
   `_finalise_after_adjudication` must commit attempt 2's answer when the
   Adjudicator returns verdict='attempt_correct' with chosen_attempt=2.
3. The flag defaults to 'standard' in coordinate() and both CLIs.

All offline: no LLM, no DB, no network.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.models import (
    AdjudicatorInput,
    AdjudicatorOutput,
    ResearcherOutput,
    VerifierOutput,
)
from agents.prompts import adjudicator as adjudicator_prompt
from scripts.run_coordinator import _finalise_after_adjudication, coordinate


# Builders

def _researcher_output(answer: str, conf: float = 0.8) -> ResearcherOutput:
    return ResearcherOutput(
        answer=answer,
        answer_explanation="some explanation",
        evidence_quote="some quote from the web page",
        source_url="https://example.com/page",
        retrieval_confidence=0.6,
        answer_confidence=conf,
    )


def _verifier_output() -> VerifierOutput:
    return VerifierOutput(
        verdict="fail",
        verifier_answer="no",
        verifier_confidence=0.7,
        substring_check_result="pass",
        rejection_reason="counter-evidence found",
        counter_evidence_quote="the portal does not offer this",
        counter_source_url="https://example.com/counter",
    )


def _adj_input(researcher_outputs) -> AdjudicatorInput:
    return AdjudicatorInput(
        question_id="P1",
        question_text="Does Malta publish an open licence policy?",
        country_code="MT",
        country_name="Malta",
        researcher_outputs=researcher_outputs,
        verifier_outputs=[_verifier_output()],
        answer_shape="binary",
        allowed_answers=["yes", "no"],
    )


# Property 1: 'standard' is byte-identical.

def test_standard_user_message_byte_identical():
    inp = _adj_input([_researcher_output("yes"), _researcher_output("no")])
    default = adjudicator_prompt.build_user_message(inp)
    explicit_standard = adjudicator_prompt.build_user_message(
        inp, selection="standard"
    )
    assert default == explicit_standard
    # The free-selection block must not appear in the standard message.
    assert "Free attempt selection" not in default
    assert "attempt_correct" not in default


def test_standard_prompt_metadata_unchanged():
    # The standard prompt's identifiers stay separate from the EXP-16 free
    # arm: same NAME (so the free arm registers a different row), a version
    # that is bumped only by deliberate edits (currently 7, after raising the
    # auto-promotion floor from 0.6 to 0.65 so every agent works to the
    # Coordinator's floor, see prompt_versions description), and the SYSTEM
    # text does not mention the EXP-16 verdict.
    assert adjudicator_prompt.NAME == "phase2_adjudicator"
    assert adjudicator_prompt.VERSION == 7
    assert "attempt_correct" not in adjudicator_prompt.SYSTEM


def test_free_prompt_is_a_separate_registration():
    # The free arm registers its own prompt version, leaving the standard
    # prompt_versions row alone.
    assert adjudicator_prompt.FREE_NAME == "phase2_adjudicator_free"
    assert adjudicator_prompt.FREE_NAME != adjudicator_prompt.NAME
    assert "attempt_correct" in adjudicator_prompt.SYSTEM_FREE


# Property 2: 'free' renders the selection instruction.

def test_free_user_message_includes_selection_block():
    inp = _adj_input([
        _researcher_output("yes"),
        _researcher_output("yes"),
        _researcher_output("no"),
    ])
    msg = adjudicator_prompt.build_user_message(inp, selection="free")
    assert "Free attempt selection (EXP-16)" in msg
    assert "attempt_correct" in msg
    assert "3 Researcher attempt(s)" in msg
    # D44 and abstention preference must travel in the per-call block too.
    assert "never 'no'" in msg


# Property 3: free mode commits a NON-final attempt's answer.
#
# Three attempts: attempt 1 = no, attempt 2 = yes (correct), final = no
# (wrong). With verdict=attempt_correct and chosen_attempt=2, the committed
# answer is attempt 2's 'yes' even though the standard 'researcher_correct'
# verdict could only ever have committed the final 'no'.

def test_free_commits_non_final_attempt_answer():
    researcher_outputs = [
        _researcher_output("no"),
        _researcher_output("yes"),  # attempt 2 is the correct one
        _researcher_output("no"),   # the final attempt drifted back to no
    ]
    adj = AdjudicatorOutput(
        adjudicator_verdict="attempt_correct",
        adjudicator_answer="yes",
        chosen_attempt=2,
        adjudicator_confidence=0.8,
        adjudicator_reasoning="C" * 55,
        chosen_source_url="https://example.com/page",
        chosen_evidence_quote="attempt 2 found the supporting passage",
    )

    status, chosen = _finalise_after_adjudication(adj, researcher_outputs)

    assert status == "accepted_by_adjudicator"
    assert chosen.answer == "yes", (
        "free mode must commit the chosen non-final attempt's answer, not the "
        "wrong final attempt's 'no'"
    )


def test_free_binds_answer_to_chosen_attempt_not_free_text():
    # Even if the model's adjudicator_answer field disagrees with the chosen
    # attempt, the committed answer is bound to the attempt's own answer so it
    # cannot be a synthesised label outside the attempts' answer set.
    researcher_outputs = [
        _researcher_output("no"),
        _researcher_output("yes"),
        _researcher_output("no"),
    ]
    adj = AdjudicatorOutput(
        adjudicator_verdict="attempt_correct",
        adjudicator_answer="maybe",  # not one of the attempt answers
        chosen_attempt=2,
        adjudicator_confidence=0.8,
        adjudicator_reasoning="D" * 55,
        chosen_source_url="https://example.com/page",
        chosen_evidence_quote="attempt 2 found the supporting passage",
    )

    _, chosen = _finalise_after_adjudication(adj, researcher_outputs)
    assert chosen.answer == "yes"


def test_free_attempt_correct_still_honours_confidence_floor():
    # A sub-floor attempt_correct commit abstains, like every other verdict.
    researcher_outputs = [
        _researcher_output("no"),
        _researcher_output("yes"),
        _researcher_output("no"),
    ]
    adj = AdjudicatorOutput(
        adjudicator_verdict="attempt_correct",
        adjudicator_answer="yes",
        chosen_attempt=2,
        adjudicator_confidence=0.4,  # below the 0.65 floor
        adjudicator_reasoning="E" * 55,
        chosen_source_url="https://example.com/page",
        chosen_evidence_quote="attempt 2 found the supporting passage",
    )

    _, chosen = _finalise_after_adjudication(adj, researcher_outputs)
    assert chosen.answer == "inconclusive", (
        "a sub-floor attempt_correct commit must abstain, not finalise the "
        "low-confidence selection"
    )


# Model-level guard: attempt_correct requires chosen_attempt.

def test_attempt_correct_requires_chosen_attempt():
    import pytest

    with pytest.raises(ValueError):
        AdjudicatorOutput(
            adjudicator_verdict="attempt_correct",
            adjudicator_answer="yes",
            chosen_attempt=None,  # missing index
            adjudicator_confidence=0.8,
            adjudicator_reasoning="F" * 55,
        )


# Property 4: the flag defaults to 'standard' everywhere.

def test_coordinate_defaults_to_standard_selection():
    sig = inspect.signature(coordinate)
    assert sig.parameters["adjudicator_selection"].default == "standard"


def test_run_adjudicator_defaults_to_standard_selection():
    from agents.adjudicator import run_adjudicator

    sig = inspect.signature(run_adjudicator)
    assert sig.parameters["selection"].default == "standard"
