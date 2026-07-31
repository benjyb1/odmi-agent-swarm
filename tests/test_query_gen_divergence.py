"""Tests for the query-generation divergence behaviour (Change 2).

When a retry carries verifier_feedback + previous_search_queries, the message
built by _build_query_gen_message must contain:
- the rejection reason
- the suggested search query (when present)
- every query from the prior attempts

When it is the first attempt (no feedback, empty prior queries), the message
must NOT contain "already tried" or "rejection".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.models import ResearcherInput, VerifierFeedback


def _make_input(
    feedback: VerifierFeedback | None = None,
    previous_search_queries: list[str] | None = None,
) -> ResearcherInput:
    return ResearcherInput(
        question_id="P1",
        question_text="Does France publish an open licence policy?",
        dimension="Policy",
        indicator="P1",
        response_scoring="yes/no",
        country_code="FR",
        country_name="France",
        country_language="fr",
        verifier_feedback=feedback,
        previous_search_queries=list(previous_search_queries or []),
    )


# Case 1: retry with feedback + prior queries — message must carry all three.

def test_retry_message_contains_rejection_reason_and_prior_queries():
    from agents.researcher import _build_query_gen_message  # type: ignore[attr-defined]

    feedback = VerifierFeedback(
        rejection_reason="quote not found on page",
        suggested_search_query="france licence coverage 2024",
    )
    inp = _make_input(
        feedback=feedback,
        previous_search_queries=["foo bar", "baz qux"],
    )

    msg = _build_query_gen_message(inp)

    assert "quote not found on page" in msg, "rejection_reason must appear in the message"
    assert "france licence coverage 2024" in msg, "suggested_search_query must appear"
    assert "foo bar" in msg, "first prior query must appear"
    assert "baz qux" in msg, "second prior query must appear"


# Case 2: first attempt — message must NOT contain retry-specific language.

def test_first_attempt_message_unchanged():
    from agents.researcher import _build_query_gen_message  # type: ignore[attr-defined]

    inp = _make_input(feedback=None, previous_search_queries=[])
    msg = _build_query_gen_message(inp)

    assert "already tried" not in msg.lower(), (
        "first-attempt message must not mention 'already tried'"
    )
    assert "rejection" not in msg.lower(), (
        "first-attempt message must not mention 'rejection'"
    )


# Case 3: feedback present but no suggested_search_query — must not error.

def test_feedback_without_suggested_query():
    from agents.researcher import _build_query_gen_message  # type: ignore[attr-defined]

    feedback = VerifierFeedback(
        rejection_reason="source unreachable",
        suggested_search_query=None,
    )
    inp = _make_input(
        feedback=feedback,
        previous_search_queries=["trial query one"],
    )

    msg = _build_query_gen_message(inp)

    assert "source unreachable" in msg
    assert "trial query one" in msg


# Case 4: prior queries present but no feedback — must still list them.

def test_prior_queries_without_feedback():
    from agents.researcher import _build_query_gen_message  # type: ignore[attr-defined]

    inp = _make_input(
        feedback=None,
        previous_search_queries=["alpha query", "beta query"],
    )

    msg = _build_query_gen_message(inp)

    assert "alpha query" in msg
    assert "beta query" in msg
    # Still shouldn't claim there's a rejection reason where there isn't one.
    assert "rejection" not in msg.lower()


# Case 5: ResearcherInput field exists on the model.

def test_researcher_input_has_previous_search_queries_field():
    inp = _make_input(previous_search_queries=["a", "b"])
    assert inp.previous_search_queries == ["a", "b"]


def test_researcher_input_previous_search_queries_default_empty():
    inp = ResearcherInput(
        question_id="P1",
        question_text="Q",
        dimension="Policy",
        indicator="P1",
        response_scoring="yes/no",
        country_code="FR",
        country_name="France",
        country_language="fr",
    )
    assert inp.previous_search_queries == []
