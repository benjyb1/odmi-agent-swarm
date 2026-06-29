"""Integration tests for D28 shape-aware prompt assembly.

Confirms that the allowed-answer list is propagated all the way from
the `questions` table through the input models into the user messages
seen by Researcher, Verifier, and Adjudicator. Catches regressions
where someone wires up the input but forgets to render the block.
"""

from __future__ import annotations

import pytest

from agents.models import (
    AdjudicatorInput,
    ResearcherInput,
    ResearcherOutput,
    VerifierInput,
    VerifierOutput,
)
from agents.prompts import adjudicator as adj_prompt
from agents.prompts import researcher as r_prompt
from agents.prompts import verifier as v_prompt
from agents.tools.search import SearchResult


def _researcher_input(shape: str, allowed: list[str]) -> ResearcherInput:
    return ResearcherInput(
        question_id="Qtest",
        question_text="A question",
        dimension="Quality",
        indicator="X",
        response_scoring="(rubric)",
        country_code="FR",
        country_name="France",
        country_language="fr",
        answer_shape=shape,
        allowed_answers=allowed,
    )


def _researcher_output(answer: str) -> ResearcherOutput:
    return ResearcherOutput(
        answer=answer,
        answer_explanation="because evidence",
        evidence_quote="a literal quote from the source",
        source_url="https://example.org/page",
        retrieval_confidence=0.7,
        answer_confidence=0.7,
    )


def _verifier_output(answer: str, verdict: str = "pass") -> VerifierOutput:
    return VerifierOutput(
        verdict=verdict,
        verifier_answer=answer,
        verifier_confidence=0.7,
        substring_check_result="pass",
        rejection_reason="reason" if verdict == "fail" else None,
        counter_evidence_quote="quote" if verdict == "fail" else None,
    )


def _search_result() -> SearchResult:
    return SearchResult(
        url="https://example.org/page",
        title="Example",
        snippet="a snippet",
        provider="tavily",
    )


# ---------------------- Researcher ----------------------


@pytest.mark.parametrize("shape,allowed", [
    ("binary", ["yes", "no"]),
    ("percentage_band", [">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"]),
    ("ordinal_magnitude", ["all", "the majority", "approximately half", "few", "none"]),
    ("count_band", ["yes, >9", "yes, 6-9", "yes, 3-5", "yes, 1-2", "no"]),
    ("categorical", ["top-down", "bottom-up", "hybrid"]),
])
def test_researcher_prompt_carries_allowed_answers(shape, allowed):
    inp = _researcher_input(shape, allowed)
    msg = r_prompt.build_user_message(
        inp,
        search_results=[_search_result()],
        queries_used=["q1"],
    )
    assert f"Answer shape: {shape}" in msg
    for label in allowed:
        # Labels appear as 'label' (repr-quoted) in the bullet list.
        assert repr(label) in msg
    assert "'inconclusive'" in msg
    assert "'not_applicable'" in msg


def test_researcher_system_prompt_references_inconclusive():
    # Stage B turned 'other-as-uncertainty' into a hard 'inconclusive' rule.
    # The phrase spans lines in the source, so collapse whitespace.
    import re
    collapsed = re.sub(r"\s+", " ", r_prompt.SYSTEM.lower())
    assert "inconclusive" in collapsed
    assert "do not collapse to `other` for uncertainty" in collapsed


# ---------------------- Verifier ----------------------


@pytest.mark.parametrize("strategy", [
    "verifier-disprove", "verifier-negation",
    "verifier-steelman", "verifier-blind",
])
def test_verifier_prompt_carries_allowed_answers(strategy):
    msg = v_prompt.build_user_message(
        question_text="A question",
        country_name="France",
        country_code="FR",
        researcher_output=_researcher_output("71-90%"),
        substring_result="pass",
        substring_notes=None,
        independent_queries=["q1"],
        independent_snippets=["snippet"],
        strategy=strategy,
        answer_shape="percentage_band",
        allowed_answers=[">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"],
    )
    assert "Answer space" in msg
    assert "Answer shape: percentage_band" in msg
    assert "'>90%'" in msg and "'<10%'" in msg
    assert "'inconclusive'" in msg
    # Band questions get the ordered-shape note.
    assert "ORDERED answer space" in msg


def test_verifier_blind_omits_researcher_answer():
    msg = v_prompt.build_user_message(
        question_text="A question",
        country_name="France",
        country_code="FR",
        researcher_output=_researcher_output("yes"),
        substring_result="pass",
        substring_notes=None,
        independent_queries=[],
        independent_snippets=[],
        strategy="verifier-blind",
        answer_shape="binary",
        allowed_answers=["yes", "no"],
    )
    assert "Researcher's answer" not in msg


def test_verifier_categorical_has_no_inherent_order_note():
    msg = v_prompt.build_user_message(
        question_text="A question",
        country_name="France",
        country_code="FR",
        researcher_output=_researcher_output("top-down"),
        substring_result="pass",
        substring_notes=None,
        independent_queries=[],
        independent_snippets=[],
        strategy="verifier-disprove",
        answer_shape="categorical",
        allowed_answers=["top-down", "bottom-up", "hybrid"],
    )
    assert "no inherent order" in msg


# ---------------------- Adjudicator ----------------------


def test_adjudicator_prompt_carries_allowed_answers():
    inp = AdjudicatorInput(
        question_id="Q12",
        question_text="A question",
        country_code="FR",
        country_name="France",
        researcher_outputs=[_researcher_output("71-90%")],
        verifier_outputs=[_verifier_output("51-70%", verdict="fail")],
        answer_shape="percentage_band",
        allowed_answers=[">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"],
    )
    msg = adj_prompt.build_user_message(inp)
    assert "Answer space" in msg
    assert "'>90%'" in msg and "'51-70%'" in msg
    assert "'inconclusive'" in msg
    assert "(only when verdict='abstain')" in msg
