"""EXP-23 retrieval-strategy knob.

The Researcher's narrow-then-widen behaviour (SRCH-5/6) was hand-wired
and never measured. The `search_strategy` knob lets an experiment hold
one variable - the retrieval strategy - while keeping everything else
frozen. These tests pin three invariants:

1. The default (`narrow_then_wide`) is byte-identical to the
   pre-EXP-23 behaviour: trusted-domain include list on the first
   pass, widen only when the narrow pass returns empty.
2. `wide_only` never sends the include list to the search wrapper
   and never re-runs as a widen pass.
3. `narrow_only` keeps the include list but skips the widen pass even
   on an empty first result, so we can attribute any wide_only gain
   to the widening step specifically.

Network and LLM calls are mocked.
"""
from __future__ import annotations

from agents import researcher
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
        country_code="NL", country_name="Netherlands", country_language="nl",
    )


def _stub_query_gen(monkeypatch):
    monkeypatch.setattr(
        researcher,
        "generate_queries",
        lambda inp, subtrio_id=None, model=None, **kwargs: (["q1", "q2"], _usage()),
    )


def _trusted_list() -> list[str]:
    return ["data.overheid.nl", "overheid.nl"]


# ---------- 1. narrow_then_wide (explicit; the former default) ----------

def test_narrow_then_wide_passes_trusted_and_widens_on_empty(monkeypatch):
    _stub_query_gen(monkeypatch)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: _trusted_list())

    calls: list[dict] = []

    def fake_search_many(queries, **kw):
        calls.append({"include_domains": kw.get("include_domains")})
        return []  # first and second pass both empty -> exercises widen path

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    researcher.run_researcher(_researcher_input(), search_strategy="narrow_then_wide")

    # Two calls: first narrow (trusted), then wide (None).
    assert len(calls) == 2
    assert calls[0]["include_domains"] == _trusted_list()
    assert calls[1]["include_domains"] is None


def test_narrow_then_wide_no_widen_when_results(monkeypatch):
    _stub_query_gen(monkeypatch)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: _trusted_list())

    calls: list[dict] = []

    from types import SimpleNamespace
    fake_result = SimpleNamespace(
        title="stub", url="https://x", snippet="s", provider="diy",
    )

    def fake_search_many(queries, **kw):
        calls.append({"include_domains": kw.get("include_domains")})
        # Non-empty first pass: caller should not widen.
        return [fake_result]

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    # Short-circuit out of the LLM step so the test only exercises search.
    from agents.tools.llm import StructuredOutputError

    def _raise(*a, **kw):
        raise StructuredOutputError("stub")

    monkeypatch.setattr(researcher, "call_for_structured", _raise)

    researcher.run_researcher(_researcher_input(), search_strategy="narrow_then_wide")

    assert len(calls) == 1
    assert calls[0]["include_domains"] == _trusted_list()


def test_narrow_then_wide_no_widen_when_trusted_empty(monkeypatch):
    """Pre-EXP-23 behaviour: an empty trusted list skips both narrow framing
    and the widen branch, because `if not search_results and trusted` is False.
    """
    _stub_query_gen(monkeypatch)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: [])

    calls: list[dict] = []

    def fake_search_many(queries, **kw):
        calls.append({"include_domains": kw.get("include_domains")})
        return []

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    researcher.run_researcher(_researcher_input(), search_strategy="narrow_then_wide")

    assert len(calls) == 1
    assert calls[0]["include_domains"] is None


# ---------- 1b. Default is now wide_only (EXP-34 adoption) ----------

def test_default_strategy_is_wide_only(monkeypatch):
    """After the EXP-34 adoption the production default is wide_only: a call
    with no explicit strategy issues one wide pass and never sends the trusted
    include list, even when one exists."""
    _stub_query_gen(monkeypatch)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: _trusted_list())

    calls: list[dict] = []

    def fake_search_many(queries, **kw):
        calls.append({"include_domains": kw.get("include_domains")})
        return []

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    researcher.run_researcher(_researcher_input())

    assert len(calls) == 1
    assert calls[0]["include_domains"] is None


# ---------- 2. wide_only ----------

def test_wide_only_never_sends_include_domains(monkeypatch):
    _stub_query_gen(monkeypatch)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: _trusted_list())

    calls: list[dict] = []

    def fake_search_many(queries, **kw):
        calls.append({"include_domains": kw.get("include_domains")})
        return []

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    researcher.run_researcher(_researcher_input(), search_strategy="wide_only")

    # Exactly one search, no include list, no widen step.
    assert len(calls) == 1
    assert calls[0]["include_domains"] is None


def test_wide_only_does_not_widen_even_on_empty(monkeypatch):
    """Belt and braces: even with empty results, wide_only never issues a
    second pass (there is nothing to widen to).
    """
    _stub_query_gen(monkeypatch)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: _trusted_list())

    n_calls = {"n": 0}

    def fake_search_many(queries, **kw):
        n_calls["n"] += 1
        return []

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    researcher.run_researcher(_researcher_input(), search_strategy="wide_only")

    assert n_calls["n"] == 1


# ---------- 3. narrow_only ----------

def test_narrow_only_sends_include_domains(monkeypatch):
    _stub_query_gen(monkeypatch)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: _trusted_list())

    calls: list[dict] = []

    def fake_search_many(queries, **kw):
        calls.append({"include_domains": kw.get("include_domains")})
        return []

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    researcher.run_researcher(_researcher_input(), search_strategy="narrow_only")

    # Exactly one search, with the trusted list, no widen.
    assert len(calls) == 1
    assert calls[0]["include_domains"] == _trusted_list()


def test_narrow_only_skips_widen_on_empty(monkeypatch):
    _stub_query_gen(monkeypatch)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: _trusted_list())

    n_calls = {"n": 0}

    def fake_search_many(queries, **kw):
        n_calls["n"] += 1
        return []

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    researcher.run_researcher(_researcher_input(), search_strategy="narrow_only")

    # Critical: narrow_only never widens, so wide_only's gain (if any) is
    # attributable to the widening step, not just to skipping include_domains.
    assert n_calls["n"] == 1


# ---------- 4. Unknown value is rejected ----------

def test_unknown_strategy_raises(monkeypatch):
    _stub_query_gen(monkeypatch)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: [])
    monkeypatch.setattr(researcher, "search_many", lambda *a, **kw: [])

    import pytest
    with pytest.raises(ValueError):
        researcher.run_researcher(_researcher_input(), search_strategy="bogus")
