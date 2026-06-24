"""Wire the snippet picker's model down from dispatch.

The snippet picker called `agents.tools.llm.call_for_structured` with no
`model=` arg, so it defaulted to `DEFAULT_MODEL` (Sonnet). When Sonnet's
quota is exhausted, every Researcher and Verifier pair 429s on the
picker even when the agent models themselves are pinned to Opus. EXP-23
needs the picker pinned too, so these tests pin the threading: the new
`picker_model` knob must flow from `run_researcher` / `run_verifier`
through `search_many` and `search_diy` into `pick_snippet`, and into
`call_for_structured` at the leaf. Default `None` keeps production
byte-identical (still falls back to `DEFAULT_MODEL`).

Network and LLM calls are mocked.
"""
from __future__ import annotations

from agents import researcher, verifier
from agents.models import (
    LLMUsage, ResearcherInput, ResearcherOutput, VerifierInput,
)


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


def _verifier_input() -> VerifierInput:
    researcher_output = ResearcherOutput(
        answer="yes", answer_confidence=0.9, retrieval_confidence=0.9,
        source_url="https://data.overheid.nl/policy",
        evidence_quote="The Netherlands has a national open data policy.",
        answer_explanation="NL has a national policy.",
    )
    return VerifierInput(
        question_id="P1", question_text="Is there a national open data policy?",
        country_code="NL", country_name="Netherlands",
        researcher_output=researcher_output,
    )


# ---------- Researcher path ----------

def test_run_researcher_threads_picker_model(monkeypatch):
    captured = {}
    monkeypatch.setattr(researcher, "generate_queries",
                        lambda inp, subtrio_id=None, model=None: (["q1"], _usage()))
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: [])

    def fake_search_many(queries, **kw):
        captured["picker_model"] = kw.get("picker_model")
        return []  # empty -> early exit, no main call

    monkeypatch.setattr(researcher, "search_many", fake_search_many)

    researcher.run_researcher(_researcher_input(), picker_model="claude-opus-4-6")

    assert captured["picker_model"] == "claude-opus-4-6"


def test_run_researcher_default_picker_model_is_none(monkeypatch):
    captured = {}
    monkeypatch.setattr(researcher, "generate_queries",
                        lambda inp, subtrio_id=None, model=None: (["q1"], _usage()))
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: [])
    monkeypatch.setattr(researcher, "search_many",
                        lambda queries, **kw: captured.update(
                            picker_model=kw.get("picker_model")) or [])

    researcher.run_researcher(_researcher_input())

    assert captured["picker_model"] is None


# ---------- Verifier path ----------

def test_run_verifier_threads_picker_model(monkeypatch):
    captured = {}

    def fake_search_many(queries, **kw):
        captured["picker_model"] = kw.get("picker_model")
        return []

    monkeypatch.setattr(verifier, "search_many", fake_search_many)
    monkeypatch.setattr(verifier, "generate_adversarial_queries",
                        lambda inp, model=None, subtrio_id=None: (["q1"], _usage()))
    # Short-circuit the main LLM call so we only exercise the search step.
    from agents.tools.llm import StructuredOutputError
    monkeypatch.setattr(verifier, "call_for_structured",
                        lambda **kw: (_ for _ in ()).throw(StructuredOutputError("stub")))

    verifier.run_verifier(_verifier_input(), picker_model="claude-opus-4-6")

    assert captured["picker_model"] == "claude-opus-4-6"


# ---------- search_many -> search_diy -> pick_snippet ----------

def test_search_many_threads_picker_model_to_diy(monkeypatch):
    from agents.tools import search as search_mod
    from agents.tools import search_diy as search_diy_mod

    captured = {}

    def fake_diy(query, **kw):
        captured.setdefault("calls", []).append(kw.get("picker_model"))
        return []

    # search.search_many imports diy_search lazily inside the function body,
    # so patch the source module.
    monkeypatch.setattr(search_diy_mod, "diy_search", fake_diy)

    search_mod.search_many(
        ["q"], provider="diy", picker_model="claude-opus-4-6",
    )

    assert captured["calls"] == ["claude-opus-4-6"]


# ---------- pick_snippet -> call_for_structured ----------

def test_pick_snippet_passes_model_to_call_for_structured(monkeypatch):
    from agents.tools import snippet_picker

    captured = {}

    class _StubParsed:
        chunks: list = []

    def fake_call(**kw):
        captured["model"] = kw.get("model")
        return _StubParsed(), _usage()

    monkeypatch.setattr(snippet_picker, "call_for_structured", fake_call)

    snippet_picker.pick_snippet(
        query="q", url="https://x", page_text="abc",
        model="claude-opus-4-6",
    )

    assert captured["model"] == "claude-opus-4-6"


def test_pick_snippet_default_model_is_none(monkeypatch):
    """Default is None so production keeps falling back to DEFAULT_MODEL."""
    from agents.tools import snippet_picker

    captured = {}

    class _StubParsed:
        chunks: list = []

    def fake_call(**kw):
        captured["model"] = kw.get("model")
        return _StubParsed(), _usage()

    monkeypatch.setattr(snippet_picker, "call_for_structured", fake_call)

    snippet_picker.pick_snippet(
        query="q", url="https://x", page_text="abc",
    )

    assert captured["model"] is None
