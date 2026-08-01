"""The EXP-8 `prompt-compressed` cost arm needs a leaner Researcher prompt
that is selectable per run, registered as its own `prompt_versions` row,
and that leaves the baseline prompt untouched.

These tests pin:
1. `variant('full')` returns the baseline V3 prompt unchanged.
2. `variant('compressed')` returns a distinct, shorter prompt with its own
   NAME/VERSION so the receipts trace to the exact text that ran.
3. An unknown variant name raises rather than silently falling back, so a
   typo in a dispatch cannot mislabel a run as baseline.
4. `run_researcher(prompt_variant='compressed')` registers and sends the
   compressed system prompt; the default leaves the baseline in place.
5. `dispatch()` forwards `--prompt-variant compressed` and omits it for the
   baseline so existing command lines are unchanged.

No network, Serper, Playwright, or real Claude calls are made.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents import researcher
from agents.models import LLMUsage, ResearcherInput
from agents.prompts import researcher as rp
from agents.tools.search import SearchResult


class _Stop(Exception):
    pass


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


# 1-3. The variant selector

class TestVariantSelector:
    def test_full_is_the_baseline(self):
        v = rp.variant("full")
        assert v.name == rp.NAME
        assert v.version == rp.VERSION
        assert v.system == rp.SYSTEM
        assert v.description == rp.DESCRIPTION

    def test_default_is_full(self):
        assert rp.variant() == rp.variant("full")

    def test_compressed_is_distinct_and_shorter(self):
        full = rp.variant("full")
        comp = rp.variant("compressed")
        assert comp.name == rp.COMPRESSED_NAME
        assert comp.name != full.name           # its own prompt_versions row
        assert comp.system != full.system
        # The point of the arm: fewer input tokens. The compressed system
        # prompt must actually be shorter than the baseline.
        assert len(comp.system) < len(full.system)

    def test_compressed_keeps_the_forbidden_source_rule(self):
        # Compression drops examples, not the anti-contamination rule.
        assert "data.europa.eu" in rp.variant("compressed").system

    def test_unknown_variant_raises(self):
        with pytest.raises(ValueError):
            rp.variant("terser-please")


# 4. run_researcher honours the variant

def _wire_researcher(monkeypatch, captured):
    def fake_ensure(name, version, system, desc):
        captured["registered_name"] = name
        captured["registered_system"] = system
        return 7

    def fake_call(**kw):
        captured["sent_system"] = kw.get("system")
        raise _Stop()

    monkeypatch.setattr(researcher, "_try_catalogue", lambda *a, **k: None)
    monkeypatch.setattr(researcher, "generate_queries",
                        lambda inp, subtrio_id=None, model=None, **kwargs: (["q1"], _usage()))
    monkeypatch.setattr(researcher, "trusted_domains_for", lambda cc: [])
    monkeypatch.setattr(researcher, "search_many", lambda queries, **kw: _one_result())
    monkeypatch.setattr(researcher.db_helpers, "ensure_prompt_version", fake_ensure)
    monkeypatch.setattr(researcher, "call_for_structured", fake_call)


def test_run_researcher_compressed_uses_compressed_prompt(monkeypatch):
    captured: dict = {}
    _wire_researcher(monkeypatch, captured)

    with pytest.raises(_Stop):
        researcher.run_researcher(_researcher_input(), prompt_variant="compressed")

    assert captured["registered_name"] == rp.COMPRESSED_NAME
    assert captured["registered_system"] == rp.COMPRESSED_SYSTEM
    assert captured["sent_system"] == rp.COMPRESSED_SYSTEM


def test_run_researcher_default_keeps_baseline_prompt(monkeypatch):
    captured: dict = {}
    _wire_researcher(monkeypatch, captured)

    with pytest.raises(_Stop):
        researcher.run_researcher(_researcher_input())

    assert captured["registered_name"] == rp.NAME
    assert captured["sent_system"] == rp.SYSTEM


# 5. dispatch forwards the prompt-variant flag

def _neutralise_dispatch(ds, monkeypatch, captured):
    class _FakeProc:
        def wait(self):
            return 0
        returncode = 0

        def communicate(self, *a, **kw):
            self.returncode = self.wait()
            return (b'', b'')

    monkeypatch.setattr(ds.subprocess, "Popen",
                        lambda cmd, **kw: captured.append(list(cmd)) or _FakeProc())
    monkeypatch.setattr(ds, "_read_default", lambda role: "claude-sonnet-4-6")
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


def test_dispatch_forwards_prompt_variant(monkeypatch):
    import scripts.dispatch_subtrios as ds

    captured: list[list[str]] = []
    _neutralise_dispatch(ds, monkeypatch, captured)

    ds.dispatch(pairs=[("P1", "MT")], prompt_variant="compressed")

    cmd = captured[0]
    assert "--prompt-variant" in cmd
    assert cmd[cmd.index("--prompt-variant") + 1] == "compressed"


def test_dispatch_omits_prompt_variant_for_baseline(monkeypatch):
    import scripts.dispatch_subtrios as ds

    captured: list[list[str]] = []
    _neutralise_dispatch(ds, monkeypatch, captured)

    ds.dispatch(pairs=[("P1", "MT")])  # default "full"

    assert "--prompt-variant" not in captured[0]
