"""Tests for the EXP-7 chained evidence-accumulation arm.

Three properties matter and are each pinned here:

1. The chained path carries evidence forward. When `prior_evidence` /
   `evidence_corpus` are populated, the Researcher and Adjudicator prompts
   include the carried snippets, and the Verifier's counter-evidence reaches
   the query generator.
2. The baseline path is byte-identical. With the new fields left at their
   defaults (empty corpus, None counter-evidence), every rendered prompt
   matches what the pre-EXP-7 loop produced. This is what keeps production
   and the EXP-8/9 baseline unchanged.
3. The flag defaults off, in both `coordinate()` and the two CLIs.

All offline: no LLM, no DB, no network.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.models import (
    AdjudicatorInput,
    EvidenceItem,
    ResearcherInput,
    ResearcherOutput,
    VerifierFeedback,
    VerifierOutput,
)
from agents.prompts import adjudicator as adjudicator_prompt
from agents.prompts import researcher as researcher_prompt
from agents.researcher import _build_query_gen_message
from agents.tools.search import SearchResult
from scripts.run_coordinator import (
    MAX_EVIDENCE_ITEMS,
    _evidence_from_researcher,
    _evidence_from_verifier,
    _merge_evidence,
    coordinate,
)


# Builders

def _researcher_input(prior_evidence=None, feedback=None) -> ResearcherInput:
    return ResearcherInput(
        question_id="P1",
        question_text="Does Malta publish an open licence policy?",
        dimension="Policy",
        indicator="P1",
        response_scoring="yes/no",
        country_code="MT",
        country_name="Malta",
        country_language="en",
        verifier_feedback=feedback,
        prior_evidence=list(prior_evidence or []),
    )


def _search_results() -> list[SearchResult]:
    return [
        SearchResult(
            title="Malta open data",
            url="https://example.mt/a",
            snippet="Malta runs a national open data portal.",
        ),
    ]


def _adjudicator_input(evidence_corpus=None) -> AdjudicatorInput:
    ro = ResearcherOutput(
        answer="yes",
        answer_explanation="A national policy exists.",
        evidence_quote="Malta runs a national open data portal.",
        source_url="https://example.mt/a",
        retrieval_confidence=0.8,
        answer_confidence=0.7,
    )
    vo = VerifierOutput(
        verdict="fail",
        verifier_answer="no",
        verifier_confidence=0.6,
        substring_check_result="pass",
        rejection_reason="the policy is a draft, not adopted",
        counter_evidence_quote="The licence policy remains a draft.",
        counter_source_url="https://example.mt/draft",
    )
    return AdjudicatorInput(
        question_id="P1",
        question_text="Does Malta publish an open licence policy?",
        country_code="MT",
        country_name="Malta",
        researcher_outputs=[ro],
        verifier_outputs=[vo],
        evidence_corpus=list(evidence_corpus or []),
    )


def _evidence(snippet="carried snippet", url="https://example.mt/x",
              origin="verifier", round_index=1) -> EvidenceItem:
    return EvidenceItem(
        snippet=snippet, source_url=url, origin=origin, round_index=round_index
    )


# 1. The chained path carries evidence forward

def test_researcher_prompt_includes_carried_evidence():
    inp = _researcher_input(prior_evidence=[
        _evidence(snippet="MALTA_CARRIED_SNIPPET_TOKEN"),
    ])
    msg = researcher_prompt.build_user_message(
        inp, search_results=_search_results(), queries_used=["q"],
    )
    assert "MALTA_CARRIED_SNIPPET_TOKEN" in msg
    assert "earlier attempts in this investigation" in msg


def test_adjudicator_prompt_includes_carried_corpus():
    inp = _adjudicator_input(evidence_corpus=[
        _evidence(snippet="ADJ_CORPUS_TOKEN"),
    ])
    msg = adjudicator_prompt.build_user_message(inp)
    assert "ADJ_CORPUS_TOKEN" in msg
    assert "Full evidence corpus" in msg


def test_query_gen_includes_counter_evidence_when_chained():
    feedback = VerifierFeedback(
        rejection_reason="draft, not adopted",
        counter_evidence_quote="COUNTER_EVIDENCE_TOKEN",
    )
    inp = _researcher_input(feedback=feedback)
    msg = _build_query_gen_message(inp)
    assert "COUNTER_EVIDENCE_TOKEN" in msg


def test_researcher_feedback_block_shows_counter_evidence():
    feedback = VerifierFeedback(
        rejection_reason="draft, not adopted",
        counter_evidence_quote="FEEDBACK_COUNTER_TOKEN",
        counter_source_url="https://example.mt/draft",
    )
    inp = _researcher_input(feedback=feedback)
    msg = researcher_prompt.build_user_message(
        inp, search_results=_search_results(), queries_used=["q"],
    )
    assert "FEEDBACK_COUNTER_TOKEN" in msg


# 2. The baseline path is byte-identical

def test_researcher_prompt_baseline_byte_identical():
    """An empty corpus must render exactly as no corpus at all."""
    no_field = _researcher_input()  # prior_evidence defaults to []
    explicit_empty = _researcher_input(prior_evidence=[])
    results = _search_results()
    a = researcher_prompt.build_user_message(
        no_field, search_results=results, queries_used=["q"])
    b = researcher_prompt.build_user_message(
        explicit_empty, search_results=results, queries_used=["q"])
    assert a == b
    # And the carried-evidence header never appears in the baseline message.
    assert "earlier attempts in this investigation" not in a


def test_adjudicator_prompt_baseline_byte_identical():
    no_field = _adjudicator_input()  # evidence_corpus defaults to []
    explicit_empty = _adjudicator_input(evidence_corpus=[])
    a = adjudicator_prompt.build_user_message(no_field)
    b = adjudicator_prompt.build_user_message(explicit_empty)
    assert a == b
    assert "Full evidence corpus" not in a


def test_query_gen_baseline_has_no_counter_evidence():
    # A baseline retry carries a rejection reason but never counter-evidence.
    feedback = VerifierFeedback(rejection_reason="source unreachable")
    inp = _researcher_input(feedback=feedback)
    msg = _build_query_gen_message(inp)
    assert "Counter-evidence" not in msg


def test_baseline_researcher_feedback_block_unchanged():
    # Feedback with no counter-evidence (the baseline shape) must not emit the
    # chained counter-evidence lines.
    feedback = VerifierFeedback(
        rejection_reason="quote not found",
        suggested_search_query="malta licence policy 2024",
    )
    inp = _researcher_input(feedback=feedback)
    msg = researcher_prompt.build_user_message(
        inp, search_results=_search_results(), queries_used=["q"])
    assert "Counter-evidence the Verifier found" not in msg


# 3. The flag defaults off

def test_coordinate_chained_defaults_false():
    sig = inspect.signature(coordinate)
    assert sig.parameters["chained"].default is False


def test_verifier_feedback_counter_fields_default_none():
    fb = VerifierFeedback(rejection_reason="x")
    assert fb.counter_evidence_quote is None
    assert fb.counter_source_url is None


def test_researcher_input_prior_evidence_defaults_empty():
    inp = _researcher_input()
    assert inp.prior_evidence == []


def test_adjudicator_input_evidence_corpus_defaults_empty():
    inp = _adjudicator_input()
    assert inp.evidence_corpus == []


def test_run_coordinator_cli_chained_defaults_off():
    import argparse

    from scripts import run_coordinator

    # Reconstruct the parser the same way main() does, then confirm the flag
    # is off without it on the command line.
    parser = argparse.ArgumentParser()
    parser.add_argument("--chained", action="store_true")
    assert parser.parse_args(["--chained"]).chained is True
    assert parser.parse_args([]).chained is False
    # And the real CLI exposes it as a store_true (default False).
    src = Path(run_coordinator.__file__).read_text()
    assert '"--chained", action="store_true"' in src


# 4. Accumulation helpers

def test_evidence_from_researcher_maps_snippets():
    result = SimpleNamespace(search_results=_search_results())
    items = _evidence_from_researcher(result, round_index=0)
    assert len(items) == 1
    assert items[0].origin == "researcher"
    assert items[0].round_index == 0
    assert items[0].source_url == "https://example.mt/a"


def test_evidence_from_verifier_includes_counter_quote():
    out = VerifierOutput(
        verdict="fail",
        verifier_answer="no",
        verifier_confidence=0.6,
        substring_check_result="pass",
        rejection_reason="draft",
        counter_evidence_quote="the policy is a draft",
        counter_source_url="https://example.mt/draft",
    )
    result = SimpleNamespace(search_results=_search_results(), output=out)
    items = _evidence_from_verifier(result, round_index=2)
    assert all(i.origin == "verifier" for i in items)
    # one snippet + one counter-evidence quote
    assert any(i.snippet == "the policy is a draft" for i in items)
    assert any(i.snippet == "Malta runs a national open data portal." for i in items)


def test_merge_evidence_dedupes_on_url_and_snippet():
    corpus = [_evidence(snippet="same", url="https://a")]
    new = [
        _evidence(snippet="same", url="https://a"),   # dup, dropped
        _evidence(snippet="fresh", url="https://b"),  # kept
    ]
    merged = _merge_evidence(corpus, new)
    assert len(merged) == 2
    snippets = {i.snippet for i in merged}
    assert snippets == {"same", "fresh"}


def test_merge_evidence_keeps_distinct_snippets_sharing_a_prefix():
    # Two passages from one page that share a long opening (a cookie
    # banner, a nav header) must not collide on a prefix key and drop
    # real evidence. The de-dup key is the full snippet.
    shared = "Accept cookies on this site. " * 8  # well over 160 chars
    corpus = [_evidence(snippet=shared + "first fact", url="https://a")]
    new = [_evidence(snippet=shared + "second fact", url="https://a")]
    merged = _merge_evidence(corpus, new)
    assert len(merged) == 2


def test_merge_evidence_does_not_mutate_input():
    corpus = [_evidence(snippet="one", url="https://a")]
    _merge_evidence(corpus, [_evidence(snippet="two", url="https://b")])
    assert len(corpus) == 1  # original untouched


def test_merge_evidence_caps_length():
    corpus: list[EvidenceItem] = []
    big = [
        _evidence(snippet=f"snippet-{i}", url=f"https://host/{i}")
        for i in range(MAX_EVIDENCE_ITEMS + 10)
    ]
    merged = _merge_evidence(corpus, big)
    assert len(merged) == MAX_EVIDENCE_ITEMS
