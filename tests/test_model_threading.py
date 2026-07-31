"""Per-agent model overrides must reach the LLM (EXP-9), and the
model-fallback escalation must pick the right model per attempt (EXP-8).

The receipts standard (CLAUDE.md) requires the resolved model version ID
to land in `claude_usage_log`. EXP-9 only means anything if the
Researcher and Verifier actually call the model they are handed, not just
record it in `subtrio_status`. Before this apparatus only the Adjudicator
threaded its model, so `model-haiku` / `model-opus` / `model-tiered`
would have silently run Sonnet everywhere except adjudication.

These tests pin:
1. `run_researcher(model=...)` forwards the model to both the query-gen
   and the main call.
2. `run_verifier(model=...)` does the same.
3. `call_for_structured` logs the model the API actually served
   (`response.model`), not the alias requested, so a tiered run's
   receipts are honest.
4. `_model_for_attempt` (the model-fallback selector) returns the base
   model on attempt 0 and escalates only on a retry, only when an
   escalation model is set.
5. `dispatch()` forwards every model flag to the spawned subprocess.

No network, Serper, Playwright, or real Claude calls are made.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents import researcher, verifier
from agents.models import LLMUsage, ResearcherInput, ResearcherOutput, VerifierInput
from agents.tools.search import SearchResult
from scripts.run_coordinator import _model_for_attempt

HAIKU = "claude-haiku-4-5-20251001"
OPUS = "claude-opus-4-6"
SONNET = "claude-sonnet-4-6"


class _Stop(Exception):
    """Sentinel raised by the fake main call to short-circuit the agent
    once the model has been captured. It is not StructuredOutputError, so
    it propagates out of the agent's try/except rather than being
    swallowed as a parse failure."""


def _usage() -> LLMUsage:
    return LLMUsage(
        input_tokens=1, output_tokens=1, wall_clock_ms=1, estimated_cost_usd=0.0,
        model_version="t", prompt_version_id=None, condition_label="query_gen",
        raw_response="{}",
    )


def _one_result() -> list[SearchResult]:
    return [SearchResult(title="A", url="https://a.example", snippet="snippet",
                         score=1.0, provider="diy")]


def _researcher_input() -> ResearcherInput:
    return ResearcherInput(
        question_id="P1", question_text="Is there a national open data policy?",
        dimension="Policy", indicator="policy_framework", response_scoring="{}",
        country_code="MT", country_name="Malta", country_language="en",
    )


def _researcher_output() -> ResearcherOutput:
    return ResearcherOutput(
        answer="yes", answer_explanation="x",
        evidence_quote="a quote long enough to pass validation",
        source_url="https://a.example", retrieval_confidence=0.8,
        answer_confidence=0.8,
    )


# 1. Researcher threads the model to both calls

def test_run_researcher_threads_model_to_query_gen_and_main(monkeypatch):
    captured: dict = {}

    def fake_gen(inp, subtrio_id=None, model=None, **kwargs):
        captured["qgen_model"] = model
        return (["q1"], _usage())

    def fake_call(**kw):
        captured["main_model"] = kw.get("model")
        raise _Stop()

    monkeypatch.setattr(researcher, "_try_catalogue", lambda *a, **k: None)
    monkeypatch.setattr(researcher, "generate_queries", fake_gen)
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: [])
    monkeypatch.setattr(researcher, "search_many", lambda queries, **kw: _one_result())
    monkeypatch.setattr(researcher.db_helpers, "ensure_prompt_version",
                        lambda *a, **k: 1)
    monkeypatch.setattr(researcher, "call_for_structured", fake_call)

    with pytest.raises(_Stop):
        researcher.run_researcher(_researcher_input(), model=HAIKU)

    assert captured["qgen_model"] == HAIKU
    assert captured["main_model"] == HAIKU


def test_run_researcher_default_model_is_none(monkeypatch):
    """No override means None is forwarded; the wrapper coalesces None to
    DEFAULT_MODEL, so the baseline arm is unchanged."""
    captured: dict = {}

    def fake_call(**kw):
        captured["main_model"] = kw.get("model")
        raise _Stop()

    monkeypatch.setattr(researcher, "_try_catalogue", lambda *a, **k: None)
    monkeypatch.setattr(researcher, "generate_queries",
                        lambda inp, subtrio_id=None, model=None, **kwargs: (["q1"], _usage()))
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: [])
    monkeypatch.setattr(researcher, "search_many", lambda queries, **kw: _one_result())
    monkeypatch.setattr(researcher.db_helpers, "ensure_prompt_version",
                        lambda *a, **k: 1)
    monkeypatch.setattr(researcher, "call_for_structured", fake_call)

    with pytest.raises(_Stop):
        researcher.run_researcher(_researcher_input())

    assert captured["main_model"] is None


# 2. Verifier threads the model to both calls

def test_run_verifier_threads_model_to_query_gen_and_main(monkeypatch):
    captured: dict = {}

    def fake_adv(inp, subtrio_id=None, model=None):
        captured["qgen_model"] = model
        return (["q1"], _usage())

    def fake_call(**kw):
        captured["main_model"] = kw.get("model")
        raise _Stop()

    monkeypatch.setattr(verifier, "_run_substring_check",
                        lambda *a, **k: ("pass", "ok", None))
    monkeypatch.setattr(verifier, "generate_adversarial_queries", fake_adv)
    monkeypatch.setattr(verifier, "search_many", lambda queries, **kw: _one_result())
    monkeypatch.setattr(verifier.db_helpers, "ensure_prompt_version",
                        lambda *a, **k: 1)
    monkeypatch.setattr(verifier, "call_for_structured", fake_call)

    v_inp = VerifierInput(
        question_id="P1", question_text="Q?", country_code="MT",
        country_name="Malta", researcher_output=_researcher_output(),
        researcher_snippets=["snippet"],
    )

    with pytest.raises(_Stop):
        verifier.run_verifier(v_inp, model=OPUS)

    assert captured["qgen_model"] == OPUS
    assert captured["main_model"] == OPUS


# 3. Receipts: the resolved model ID is logged, not the requested alias

class _Out(BaseModel):
    value: int


def test_usage_log_records_resolved_model(monkeypatch, tmp_path):
    import agents.tools.llm as llm

    dbp = tmp_path / "usage.db"
    sqlite3.connect(dbp).executescript(
        """CREATE TABLE claude_usage_log (
               id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, model TEXT,
               input_tokens INT, output_tokens INT, estimated_cost_usd REAL,
               rate_limited INT, context TEXT, subtrio_id TEXT);"""
    )
    monkeypatch.setattr(llm, "_DB_PATH", dbp)

    class _U:
        input_tokens = 10
        output_tokens = 5

    class _Block:
        text = '{"value": 3}'

    class _Msg:
        # The catalogue may resolve an alias to a dated version; the
        # receipts must record what was served, not what was asked for.
        model = "claude-haiku-4-5-20251001"
        usage = _U()
        content = [_Block()]

    class _Messages:
        @staticmethod
        def create(**kw):
            return _Msg()

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(llm, "_make_client", lambda: _Client())

    parsed, usage = llm.call_for_structured(
        system="s", user_message="u", output_schema=_Out, model="haiku-alias",
    )

    assert parsed.value == 3
    assert usage.model_version == "claude-haiku-4-5-20251001"
    rows = sqlite3.connect(dbp).execute(
        "SELECT model FROM claude_usage_log"
    ).fetchall()
    assert rows == [("claude-haiku-4-5-20251001",)]


# 4. model-fallback escalation selector (EXP-8)

class TestModelForAttempt:
    def test_attempt_zero_uses_base(self):
        assert _model_for_attempt(HAIKU, SONNET, 0) == HAIKU

    def test_retry_escalates(self):
        assert _model_for_attempt(HAIKU, SONNET, 1) == SONNET
        assert _model_for_attempt(HAIKU, SONNET, 3) == SONNET

    def test_no_escalation_holds_base(self):
        # Every non-fallback arm passes escalation=None and must hold.
        assert _model_for_attempt(SONNET, None, 0) == SONNET
        assert _model_for_attempt(SONNET, None, 2) == SONNET

    def test_base_none_is_passthrough(self):
        assert _model_for_attempt(None, None, 0) is None
        assert _model_for_attempt(None, None, 1) is None


# 5. dispatch forwards the model flags to the subprocess

def _neutralise_dispatch(ds, monkeypatch, captured):
    class _FakeProc:
        def wait(self):
            return 0

    def fake_popen(cmd, **kw):
        captured.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr(ds.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ds, "_read_default", lambda role: SONNET)
    monkeypatch.setattr(
        ds, "estimate_pair_cost",
        lambda **kw: ds.CostEstimate(
            per_subtrio_usd=0.01, projected_total_usd=0.01,
            rolling_window_cost_usd=0.0, fallback_level="cold_start",
            sample_size=0,
        ),
    )
    monkeypatch.setattr(ds, "rolling_window_cost_usd", lambda *a, **k: 0.0)
    monkeypatch.setattr(ds, "publish_to_main", lambda result, log=None: None)


def test_dispatch_forwards_per_agent_and_escalation_models(monkeypatch):
    import scripts.dispatch_subtrios as ds

    captured: list[list[str]] = []
    _neutralise_dispatch(ds, monkeypatch, captured)

    ds.dispatch(
        pairs=[("P1", "MT")],
        researcher_model=HAIKU, verifier_model=SONNET, adjudicator_model=OPUS,
        researcher_escalation_model=SONNET, verifier_escalation_model=SONNET,
    )

    assert len(captured) == 1
    cmd = captured[0]

    def val(flag):
        return cmd[cmd.index(flag) + 1]

    assert val("--researcher-model") == HAIKU
    assert val("--verifier-model") == SONNET
    assert val("--adjudicator-model") == OPUS
    assert val("--researcher-escalation-model") == SONNET
    assert val("--verifier-escalation-model") == SONNET


def test_dispatch_omits_escalation_when_unset(monkeypatch):
    import scripts.dispatch_subtrios as ds

    captured: list[list[str]] = []
    _neutralise_dispatch(ds, monkeypatch, captured)

    ds.dispatch(pairs=[("P1", "MT")], researcher_model=SONNET)

    cmd = captured[0]
    assert "--researcher-escalation-model" not in cmd
    assert "--verifier-escalation-model" not in cmd
