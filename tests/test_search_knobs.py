"""The search knobs (provider, results-per-query, query count) must be
controllable per run so they can be varied as experiment conditions.

These tests pin the threading: run_researcher / run_verifier must forward the
provider and result cap to search_many, and must cap the generated queries to
num_queries. Network and LLM calls are mocked.
"""
from __future__ import annotations

from agents import researcher, verifier
from agents.models import LLMUsage, ResearcherInput


def _usage() -> LLMUsage:
    return LLMUsage(
        input_tokens=1, output_tokens=1, wall_clock_ms=1, estimated_cost_usd=0.0,
        model_version="t", prompt_version_id=None, condition_label="query_gen",
        raw_response="{}",
    )


def _researcher_input() -> ResearcherInput:
    return ResearcherInput(
        question_id="P1", question_text="Is there a national open data policy?",
        dimension="Policy", indicator="policy_framework", response_scoring="{}",
        country_code="FR", country_name="France", country_language="fr",
    )


def test_run_researcher_threads_provider_and_caps_queries(monkeypatch):
    captured = {}
    monkeypatch.setattr(researcher, "generate_queries",
                        lambda inp, subtrio_id=None, model=None, **kwargs: (["q1", "q2", "q3"], _usage()))
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: [])

    def fake_search_many(queries, **kw):
        captured["queries"] = list(queries)
        captured["provider"] = kw.get("provider")
        captured["max_results_per_query"] = kw.get("max_results_per_query")
        return []  # empty -> run_researcher returns early (no main call needed)

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    researcher.run_researcher(
        _researcher_input(), provider="diy", num_queries=2, max_results_per_query=3,
    )

    assert captured["queries"] == ["q1", "q2"]      # capped to num_queries
    assert captured["provider"] == "diy"
    assert captured["max_results_per_query"] == 3


def test_run_researcher_defaults_unchanged(monkeypatch):
    """Without knobs, behaviour is the old behaviour: all queries, auto provider."""
    captured = {}
    monkeypatch.setattr(researcher, "generate_queries",
                        lambda inp, subtrio_id=None, model=None, **kwargs: (["q1", "q2", "q3"], _usage()))
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: [])
    monkeypatch.setattr(researcher, "search_many",
                        lambda queries, **kw: captured.update(
                            queries=list(queries), provider=kw.get("provider")) or [])

    researcher.run_researcher(_researcher_input())

    assert captured["queries"] == ["q1", "q2", "q3"]  # no cap
    assert captured["provider"] == "auto"
