"""The attribution/relevance gate.

The known failure (HANDOVER, Ukraine): a quote faithfully supports a point, so
the verifier passes it, but the action it describes is the Red Cross's, not
WHO's. A WHO briefing must never put another body's work in WHO's mouth. The
gate runs after the verifier and drops a point unless the action is WHO's and
on-topic.

Each test scripts every swarm stage through the model seam, so only the gate's
decision varies.
"""
from __future__ import annotations

from who_speech import llm, swarm
from who_speech.search import Passage

QUOTE = "WHO supported the financing reform in 2021"
PASSAGE_TEXT = f"In context, {QUOTE}, the report notes further detail."


def _passage(text):
    return Passage(
        text=text, parent_text=text,
        citation="Report. World Health Organization; 2021. Licence: CC BY 3.0 IGO",
        iris_url="https://iris.who.int/handle/10665/9",
        page_start=3, page_end=3, rights="CC BY 3.0 IGO", score=0.9,
    )


class _FakeRetriever:
    def __init__(self, passages):
        self._passages = passages

    def retrieve(self, query, k=5):
        return self._passages


def _scripted(attribution):
    def fake(*, system, user_message, output_schema, usage_context, **kw):
        if usage_context == "who_speech:plan":
            return swarm.ResearchPlan(aspects=["financing reform"]), {}
        if usage_context == "who_speech:researcher":
            return swarm.DraftedPoint(
                supported=True, point="WHO supported a financing reform.",
                verbatim_quote=QUOTE, passage_index=0, confidence=0.9,
            ), {}
        if usage_context == "who_speech:verifier":
            return swarm.VerifierJudgement(supported=True, reason="quote supports point", confidence=0.9), {}
        if usage_context == "who_speech:attribution":
            return attribution, {}
        if usage_context == "who_speech:adjudicator":
            return swarm.Adjudication(keep_indices=[0], abstain=False, reason="kept"), {}
        raise AssertionError(f"unexpected usage_context {usage_context!r}")

    return fake


def test_point_describing_a_non_who_actor_is_dropped(monkeypatch):
    monkeypatch.setattr(
        llm, "structured",
        _scripted(swarm.AttributionJudgement(
            is_who_action=False, on_topic=True, reason="describes the Red Cross, not WHO")),
    )
    pack = swarm.orchestrate("What has WHO done on financing?", _FakeRetriever([_passage(PASSAGE_TEXT)]), verbose=False)
    assert pack.points == []
    assert pack.abstained


def test_who_action_on_topic_point_survives(monkeypatch):
    monkeypatch.setattr(
        llm, "structured",
        _scripted(swarm.AttributionJudgement(is_who_action=True, on_topic=True, reason="WHO action")),
    )
    pack = swarm.orchestrate("What has WHO done on financing?", _FakeRetriever([_passage(PASSAGE_TEXT)]), verbose=False)
    assert len(pack.points) == 1
    assert pack.points[0].point == "WHO supported a financing reform."


def test_off_topic_point_is_dropped(monkeypatch):
    monkeypatch.setattr(
        llm, "structured",
        _scripted(swarm.AttributionJudgement(is_who_action=True, on_topic=False, reason="off topic")),
    )
    pack = swarm.orchestrate("What has WHO done on financing?", _FakeRetriever([_passage(PASSAGE_TEXT)]), verbose=False)
    assert pack.points == []
    assert pack.abstained
