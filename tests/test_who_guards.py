"""Two watertightness gates, both run after the verifier and both drop-only:

- numbers_supported (FM-06): every number/percentage/year asserted in a point
  must appear in the cited quote, else the point is dropped. Deterministic.
- check_context (FM-02): an LLM judges whether the point is misleading once the
  surrounding passage is taken into account (a nearby negation, a conditional,
  another actor's view, a dropped scope).

Both are wired into orchestrate behind config flags so they can be ablated.
"""
from __future__ import annotations

from who_speech import config, guards, llm, swarm
from who_speech.search import Passage

# --- FM-06 numeric/date guard (deterministic) --------------------------------

def test_numbers_supported_when_all_present_in_quote():
    ok, missing = guards.numbers_supported(
        "9% up from 7% in 2018", "in 2024 9% up from 7% in 2018 and 5% impoverished")
    assert ok is True
    assert missing == []


def test_unsupported_when_point_adds_a_figure():
    ok, missing = guards.numbers_supported("10% of households", "9% of households")
    assert ok is False
    assert "10" in missing


def test_percent_and_decimal_are_normalised():
    ok, _ = guards.numbers_supported(
        "46.2% were out of pocket", "almost half (46.2%) was out-of-pocket")
    assert ok is True


def test_thousands_separator_normalised():
    ok, _ = guards.numbers_supported("5,313,552 bytes", "the file was 5313552 bytes")
    assert ok is True


def test_point_without_digits_is_supported():
    ok, missing = guards.numbers_supported("WHO supported the reform", "WHO supported the reform")
    assert ok is True
    assert missing == []


def test_year_must_appear_in_quote():
    ok, missing = guards.numbers_supported("the reform in 2019", "the reform in 2021")
    assert ok is False
    assert "2019" in missing


# --- FM-02 context-faithfulness check (LLM wrapper) --------------------------

def test_context_check_flags_misleading(monkeypatch):
    monkeypatch.setattr(
        llm, "structured",
        lambda **kw: (guards.ContextJudgement(misleading=True, reason="passage negates it"), {}))
    assert guards.check_context("P", "Q", "ctx").misleading is True


def test_context_check_passes_clean(monkeypatch):
    monkeypatch.setattr(
        llm, "structured",
        lambda **kw: (guards.ContextJudgement(misleading=False, reason="fair"), {}))
    assert guards.check_context("P", "Q", "ctx").misleading is False


# --- wiring into orchestrate (behind flags) ----------------------------------

_QUOTE = "spending reached 9% of households in 2024"
_PASSAGE = f"In context, {_QUOTE}, the report notes."


def _passage(text, parent=None):
    return Passage(
        text=text, parent_text=parent or text,
        citation="C. World Health Organization; 2025. Licence: CC BY 3.0 IGO",
        iris_url="u", page_start=1, page_end=1, rights="CC BY 3.0 IGO", score=0.9)


class _Retriever:
    def __init__(self, passages):
        self._passages = passages

    def retrieve(self, query, k=5):
        return self._passages


def _script(point, quote, context_misleading=False):
    def fake(*, system, user_message, output_schema, usage_context, **kw):
        if usage_context == "who_speech:plan":
            return swarm.ResearchPlan(aspects=["a"]), {}
        if usage_context == "who_speech:researcher":
            return swarm.DraftedPoint(
                supported=True, point=point, verbatim_quote=quote,
                passage_index=0, confidence=0.9), {}
        if usage_context == "who_speech:verifier":
            return swarm.VerifierJudgement(supported=True, reason="ok", confidence=0.9), {}
        if usage_context == "who_speech:attribution":
            return swarm.AttributionJudgement(is_who_action=True, on_topic=True, reason="WHO"), {}
        if usage_context == "who_speech:context":
            return guards.ContextJudgement(misleading=context_misleading, reason="x"), {}
        if usage_context == "who_speech:adjudicator":
            return swarm.Adjudication(keep_indices=[0], abstain=False, reason="k"), {}
        raise AssertionError(f"unexpected usage_context {usage_context!r}")

    return fake


def test_numeric_guard_drops_point_with_unsupported_figure(monkeypatch):
    monkeypatch.setattr(config, "numeric_guard", lambda: True)
    monkeypatch.setattr(config, "context_check", lambda: False)
    monkeypatch.setattr(llm, "structured", _script("spending reached 12% in 2024", _QUOTE))
    pack = swarm.orchestrate("q", _Retriever([_passage(_PASSAGE)]), verbose=False)
    assert pack.points == []


def test_numeric_guard_keeps_point_with_supported_figures(monkeypatch):
    monkeypatch.setattr(config, "numeric_guard", lambda: True)
    monkeypatch.setattr(config, "context_check", lambda: False)
    monkeypatch.setattr(llm, "structured", _script("spending reached 9% in 2024", _QUOTE))
    pack = swarm.orchestrate("q", _Retriever([_passage(_PASSAGE)]), verbose=False)
    assert len(pack.points) == 1


def test_context_check_drops_misleading_point(monkeypatch):
    monkeypatch.setattr(config, "numeric_guard", lambda: False)
    monkeypatch.setattr(config, "context_check", lambda: True)
    # Quote >= 15 chars so it clears the quote-gate and the drop is the context
    # gate's doing, not the length floor.
    quote = "WHO supported the national health reform"
    monkeypatch.setattr(llm, "structured", _script(quote, quote, context_misleading=True))
    passage = _passage(f"In 2021 {quote} across several regions.")
    pack = swarm.orchestrate("q", _Retriever([passage]), verbose=False)
    assert pack.points == []
