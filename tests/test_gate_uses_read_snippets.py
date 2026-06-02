"""Tests for the snippet-based substring gate (Change 3).

TDD: these tests were written BEFORE the implementation to pin the
required behaviour:

1. When researcher_snippets is non-empty, _run_substring_check must
   match against those snippets and NEVER fetch the live URL.
2. The anti-hallucination property is preserved: a quote absent from
   the snippets still fails.
3. Back-compat: with researcher_snippets=None or [], the function falls
   back to the original live-fetch path.
4. VerifierInput accepts the researcher_snippets field and defaults to [].
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from agents.models import ResearcherOutput, VerifierInput


# ============================================================
# Helper: build a minimal ResearcherOutput so VerifierInput
# validates without real data.
# ============================================================

def _minimal_researcher_output() -> ResearcherOutput:
    return ResearcherOutput(
        answer="yes",
        answer_explanation="Test explanation for the research output",
        evidence_quote="loi pour une republique numerique",
        source_url="https://example.invalid/404",  # type: ignore[arg-type]
        retrieval_confidence=0.9,
        answer_confidence=0.8,
    )


# ============================================================
# Test 1: snippet path — pass when quote is in the snippets
# ============================================================

def test_substring_check_pass_from_snippets_no_network() -> None:
    """Pass when the quote is present in the researcher snippets.

    The URL is unreachable (example.invalid/404). If the live-fetch path
    were taken the function would error or return 'not_attempted'. A
    'pass' result proves the snippet path was used.

    The Researcher's evidence_quote carries the same accented characters
    as the snippet it was drawn from, so the quote here uses the same
    Unicode form as the snippet text. substring.contains applies NFKC
    normalisation (handles non-breaking spaces, smart quotes) but does
    not strip diacritics — both sides need the same casing/accent form.
    """
    from agents.verifier import _run_substring_check

    snippet_text = "... Loi pour une République numérique ...other text ..."
    # The evidence_quote the Researcher would have extracted from this snippet.
    quote = "Loi pour une République numérique"

    # Patch both fetch functions so any call is detected.
    with patch("agents.verifier.fetch_text") as mock_ft, \
         patch("agents.verifier.fetch_rendered_text") as mock_frt:

        result, notes, fetch_obj = _run_substring_check(
            "https://example.invalid/404",
            quote,
            researcher_snippets=[snippet_text],
        )

    assert result == "pass", f"expected 'pass', got {result!r} (notes: {notes})"
    # Fetch must not have been called when snippets are supplied.
    mock_ft.assert_not_called()
    mock_frt.assert_not_called()
    # fetch_obj should be None for the snippet path.
    assert fetch_obj is None


# ============================================================
# Test 2: snippet path — fail when quote is absent from snippets
# ============================================================

def test_substring_check_fail_quote_absent_from_snippets() -> None:
    """Fail when the evidence quote is not in the researcher snippets.

    Anti-hallucination: a fabricated quote that never appeared in any
    snippet must fail even if the snippets are non-empty.
    """
    from agents.verifier import _run_substring_check

    with patch("agents.verifier.fetch_text") as mock_ft, \
         patch("agents.verifier.fetch_rendered_text") as mock_frt:

        result, notes, fetch_obj = _run_substring_check(
            "https://example.com/some-page",
            "Loi pour une République numérique",
            researcher_snippets=["completely unrelated text about something else"],
        )

    assert result == "fail", f"expected 'fail', got {result!r}"
    mock_ft.assert_not_called()
    mock_frt.assert_not_called()
    assert fetch_obj is None


# ============================================================
# Test 3a: back-compat with researcher_snippets=None — uses fetch path
# ============================================================

def test_substring_check_backcompat_none_uses_fetch_pass() -> None:
    """With researcher_snippets=None the live-fetch path runs as before.

    Monkeypatches fetch_text to return content that contains the quote.
    """
    from agents.tools.fetch import FetchResult
    from agents.verifier import _run_substring_check

    stub = FetchResult(
        url="https://example.com/page",
        backend="httpx",
        status_code=200,
        content="The Loi pour une republique numerique was adopted in 2016.",
        truncated=False,
        failure_mode=None,
    )

    with patch("agents.verifier.fetch_text", return_value=stub) as mock_ft:
        result, notes, fetch_obj = _run_substring_check(
            "https://example.com/page",
            "loi pour une republique numerique",
            researcher_snippets=None,
        )

    assert result == "pass", f"expected 'pass', got {result!r}"
    mock_ft.assert_called_once()


# ============================================================
# Test 3b: back-compat with researcher_snippets=[] — uses fetch path
# ============================================================

def test_substring_check_backcompat_empty_list_uses_fetch_pass() -> None:
    """With researcher_snippets=[] the live-fetch path runs as before."""
    from agents.tools.fetch import FetchResult
    from agents.verifier import _run_substring_check

    stub = FetchResult(
        url="https://example.com/page",
        backend="httpx",
        status_code=200,
        content="loi pour une republique numerique was adopted in 2016.",
        truncated=False,
        failure_mode=None,
    )

    with patch("agents.verifier.fetch_text", return_value=stub):
        result, notes, fetch_obj = _run_substring_check(
            "https://example.com/page",
            "loi pour une republique numerique",
            researcher_snippets=[],
        )

    assert result == "pass", f"expected 'pass', got {result!r}"


# ============================================================
# Test 3c: back-compat — fetch failure → not_attempted
# ============================================================

def test_substring_check_backcompat_fetch_failure_not_attempted() -> None:
    """With researcher_snippets=None and a failing fetch, return not_attempted."""
    from agents.tools.fetch import FetchResult
    from agents.verifier import _run_substring_check

    failed_stub = FetchResult(
        url="https://example.invalid/404",
        backend="httpx",
        status_code=0,
        content="",
        truncated=False,
        failure_mode="connection_error",
    )

    with patch("agents.verifier.fetch_text", return_value=failed_stub), \
         patch("agents.verifier.fetch_rendered_text", return_value=failed_stub):
        result, notes, fetch_obj = _run_substring_check(
            "https://example.invalid/404",
            "some evidence quote here and there",
            researcher_snippets=None,
        )

    assert result == "not_attempted", f"expected 'not_attempted', got {result!r}"
    assert notes is not None


# ============================================================
# Test 4: VerifierInput accepts researcher_snippets, defaults to []
# ============================================================

def test_verifier_input_researcher_snippets_field() -> None:
    """VerifierInput has researcher_snippets and it defaults to []."""
    ro = _minimal_researcher_output()
    v_inp = VerifierInput(
        question_id="P1",
        question_text="Does the country have an open data policy?",
        country_code="FR",
        country_name="France",
        researcher_output=ro,
    )
    # Default should be an empty list.
    assert hasattr(v_inp, "researcher_snippets"), (
        "VerifierInput missing 'researcher_snippets' field"
    )
    assert v_inp.researcher_snippets == []


def test_verifier_input_researcher_snippets_populated() -> None:
    """VerifierInput stores supplied researcher_snippets correctly."""
    ro = _minimal_researcher_output()
    snippets = ["snippet one about open data", "snippet two about policy"]
    v_inp = VerifierInput(
        question_id="P1",
        question_text="Does the country have an open data policy?",
        country_code="FR",
        country_name="France",
        researcher_output=ro,
        researcher_snippets=snippets,
    )
    assert v_inp.researcher_snippets == snippets
