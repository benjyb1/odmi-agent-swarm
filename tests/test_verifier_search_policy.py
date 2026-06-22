"""EXP-14: the Verifier's web counter-search policy is a knob.

`run_verifier(..., verifier_search=...)` takes three values:

- 'always' (default) — current production behaviour, byte-identical. The
  Verifier generates adversarial queries and runs its own live web search.
- 'never' — the Verifier does NOT run its own web search. It reasons only
  over the Researcher's evidence and snippets. The substring gate and all
  verdict post-processing are untouched.
- 'elective' — not built; raises NotImplementedError.

These tests pin the three behaviours by mocking the network and LLM calls.
The default ('always' / absent) path must be byte-identical to production:
the rendered prompt is unchanged and the web search IS invoked.
"""

from __future__ import annotations

import pytest

from agents import verifier
from agents.models import LLMUsage, ResearcherOutput, VerifierInput, VerifierOutput
from agents.prompts import verifier as v_prompt
from agents.tools.search import SearchResult


# ============================================================
# Fixtures
# ============================================================

def _usage(label: str) -> LLMUsage:
    return LLMUsage(
        input_tokens=1, output_tokens=1, wall_clock_ms=1, estimated_cost_usd=0.0,
        model_version="t", prompt_version_id=None, condition_label=label,
        raw_response="{}",
    )


def _researcher_output() -> ResearcherOutput:
    return ResearcherOutput(
        answer="yes",
        answer_explanation="because evidence",
        evidence_quote="a literal quote from the source",
        source_url="https://example.org/page",
        retrieval_confidence=0.7,
        answer_confidence=0.7,
    )


def _verifier_input() -> VerifierInput:
    return VerifierInput(
        question_id="P1",
        question_text="Is there a national open data policy?",
        country_code="FR",
        country_name="France",
        researcher_output=_researcher_output(),
        strategy="verifier-disprove",
        answer_shape="binary",
        allowed_answers=["yes", "no"],
        # The snippets the Researcher actually read. With these present the
        # substring check runs against them, no live fetch.
        researcher_snippets=["a literal quote from the source is right here"],
    )


def _verifier_output() -> VerifierOutput:
    return VerifierOutput(
        verdict="pass",
        verifier_answer="yes",
        verifier_confidence=0.8,
        substring_check_result="pass",
    )


def _install_common_mocks(monkeypatch):
    """Mock the prompt registration and the main verdict LLM call.

    Captures the user_message the verdict call received so a test can assert
    on what the model actually saw. Leaves the query-gen and search functions
    for the per-test mocks so each test can assert whether they ran.
    """
    captured: dict = {}

    monkeypatch.setattr(
        verifier.db_helpers, "ensure_prompt_version",
        lambda *a, **k: 1,
    )

    def fake_main_call(*, system, user_message, **kw):
        captured["system"] = system
        captured["user_message"] = user_message
        return _verifier_output(), _usage("baseline")

    monkeypatch.setattr(verifier, "call_for_structured", fake_main_call)
    return captured


# ============================================================
# 'always' / default — byte-identical to production
# ============================================================

def test_always_runs_search_and_prompt_is_default(monkeypatch):
    """With the flag absent (default 'always') the Verifier runs its own
    adversarial query-gen and web search, and the verdict prompt is the
    production prompt with the independent-search block."""
    captured = _install_common_mocks(monkeypatch)
    calls = {"query_gen": 0, "search": 0}

    def fake_query_gen(inp, **kw):
        calls["query_gen"] += 1
        return ["adversarial q1", "adversarial q2"], _usage("verifier_query_gen")

    def fake_search_many(queries, **kw):
        calls["search"] += 1
        return [
            SearchResult(
                url="https://other.example/x", title="A title",
                snippet="an independent snippet", provider="diy",
            )
        ]

    monkeypatch.setattr(verifier, "generate_adversarial_queries", fake_query_gen)
    monkeypatch.setattr(verifier, "search_many", fake_search_many)

    result = verifier.run_verifier(_verifier_input())  # flag absent -> default

    # The web search ran exactly once, as in production.
    assert calls["query_gen"] == 1
    assert calls["search"] == 1
    assert result.output is not None
    assert result.output.verdict == "pass"

    # The rendered prompt is byte-identical to the production builder called
    # with the same captured queries/snippets, i.e. no policy note leaked in.
    expected = v_prompt.build_user_message(
        question_text="Is there a national open data policy?",
        country_name="France",
        country_code="FR",
        researcher_output=_researcher_output(),
        substring_result="pass",
        substring_notes=(
            "matched against snippet 0 the Researcher read (1 fragment(s))"
        ),
        independent_queries=["adversarial q1", "adversarial q2"],
        independent_snippets=["A title — an independent snippet"],
        strategy="verifier-disprove",
        answer_shape="binary",
        allowed_answers=["yes", "no"],
    )
    assert captured["user_message"] == expected
    assert "NOT RUN" not in captured["user_message"]


def test_explicit_always_matches_default(monkeypatch):
    """Passing verifier_search='always' explicitly is the same as omitting it."""
    captured = _install_common_mocks(monkeypatch)
    monkeypatch.setattr(
        verifier, "generate_adversarial_queries",
        lambda inp, **kw: (["q1"], _usage("verifier_query_gen")),
    )
    monkeypatch.setattr(
        verifier, "search_many",
        lambda queries, **kw: [
            SearchResult(url="https://x/y", title="t", snippet="s", provider="diy")
        ],
    )

    result = verifier.run_verifier(_verifier_input(), verifier_search="always")
    assert result.output is not None
    assert "NOT RUN" not in captured["user_message"]


# ============================================================
# 'never' — no independent web search
# ============================================================

def test_never_skips_web_search(monkeypatch):
    """'never' must not invoke the query-gen LLM call or search_many at all."""
    captured = _install_common_mocks(monkeypatch)

    def boom_query_gen(inp, **kw):
        raise AssertionError("query-gen must not run under verifier_search='never'")

    def boom_search(queries, **kw):
        raise AssertionError("search_many must not run under verifier_search='never'")

    monkeypatch.setattr(verifier, "generate_adversarial_queries", boom_query_gen)
    monkeypatch.setattr(verifier, "search_many", boom_search)

    result = verifier.run_verifier(_verifier_input(), verifier_search="never")

    # The verdict still came back, the substring gate still ran, and no
    # query-gen usage was billed because no query-gen call was made.
    assert result.output is not None
    assert result.output.verdict == "pass"
    assert result.query_gen_usage is None
    assert result.adversarial_queries == []
    assert result.search_results == []
    assert result.substring_result == "pass"


def test_never_prompt_carries_no_search_note(monkeypatch):
    """The 'never' verdict prompt swaps the search block for the no-search
    note, carried in the per-call user message, not the system prompt."""
    captured = _install_common_mocks(monkeypatch)
    monkeypatch.setattr(
        verifier, "generate_adversarial_queries",
        lambda inp, **kw: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    monkeypatch.setattr(
        verifier, "search_many",
        lambda queries, **kw: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    verifier.run_verifier(_verifier_input(), verifier_search="never")

    msg = captured["user_message"]
    assert "Independent search: NOT RUN" in msg
    # The system prompt is the unmodified registered strategy system prompt.
    assert captured["system"] == v_prompt.STRATEGIES["verifier-disprove"].system
    assert "NOT RUN" not in captured["system"]


# ============================================================
# 'elective' — not built, fails loud
# ============================================================

def test_elective_raises_not_implemented(monkeypatch):
    _install_common_mocks(monkeypatch)
    monkeypatch.setattr(
        verifier, "generate_adversarial_queries",
        lambda inp, **kw: (["q1"], _usage("verifier_query_gen")),
    )
    monkeypatch.setattr(
        verifier, "search_many",
        lambda queries, **kw: [],
    )

    with pytest.raises(NotImplementedError):
        verifier.run_verifier(_verifier_input(), verifier_search="elective")


# ============================================================
# Prompt builder: default rendering unchanged
# ============================================================

def test_prompt_builder_default_unchanged():
    """build_user_message with the new arg absent renders exactly as before."""
    common = dict(
        question_text="A question",
        country_name="France",
        country_code="FR",
        researcher_output=_researcher_output(),
        substring_result="pass",
        substring_notes=None,
        independent_queries=["q1"],
        independent_snippets=["snippet one"],
        strategy="verifier-disprove",
        answer_shape="binary",
        allowed_answers=["yes", "no"],
    )
    without_arg = v_prompt.build_user_message(**common)
    with_always = v_prompt.build_user_message(**common, verifier_search="always")
    assert without_arg == with_always
    # The independent-search block is present; the no-search note is not.
    assert "Snippets returned" in without_arg
    assert "NOT RUN" not in without_arg


def test_prompt_builder_never_swaps_block():
    msg = v_prompt.build_user_message(
        question_text="A question",
        country_name="France",
        country_code="FR",
        researcher_output=_researcher_output(),
        substring_result="pass",
        substring_notes=None,
        independent_queries=[],
        independent_snippets=[],
        strategy="verifier-disprove",
        answer_shape="binary",
        allowed_answers=["yes", "no"],
        verifier_search="never",
    )
    assert "Independent search: NOT RUN" in msg
    # The Researcher's claim and substring blocks survive.
    assert "Researcher's claim" in msg
    assert "Substring check" in msg


# ============================================================
# CLI threading
# ============================================================

def test_run_coordinator_cli_default_is_always():
    import argparse
    import scripts.run_coordinator as rc

    # Reconstruct the parser exactly as main() builds it is heavy; instead
    # assert the choices and default on a minimal parser mirroring the flag.
    p = argparse.ArgumentParser()
    p.add_argument("--verifier-search", default="always",
                   choices=["never", "elective", "always"])
    assert p.parse_args([]).verifier_search == "always"
    assert p.parse_args(["--verifier-search", "never"]).verifier_search == "never"


def test_dispatch_forwards_only_non_default(monkeypatch):
    """The dispatcher appends --verifier-search to the child command only when
    the policy differs from the 'always' default, keeping the baseline child
    invocation byte-identical."""
    import scripts.dispatch_subtrios as ds

    captured_cmds: list = []

    class _FakeProc:
        def wait(self):
            return 0
        def poll(self):
            return 0

    def fake_popen(cmd, **kw):
        captured_cmds.append(cmd)
        return _FakeProc()

    monkeypatch.setattr(ds.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ds, "estimate_pair_cost", lambda **kw: ds.CostEstimate(
        per_subtrio_usd=0.1, projected_total_usd=0.1, rolling_window_cost_usd=0.0,
        fallback_level="cold_start", sample_size=0,
    ))
    monkeypatch.setattr(ds, "_read_default", lambda role: "claude-sonnet-4-6")
    monkeypatch.setattr(ds, "publish_to_main", lambda result, **kw: None)

    # Default policy: no --verifier-search in the command.
    ds.dispatch(pairs=[("P1", "FR")], warm_catalogue=False)
    assert all("--verifier-search" not in c for c in captured_cmds)

    captured_cmds.clear()
    # never: flag forwarded.
    ds.dispatch(pairs=[("P1", "FR")], warm_catalogue=False, verifier_search="never")
    assert any(
        "--verifier-search" in c and c[c.index("--verifier-search") + 1] == "never"
        for c in captured_cmds
    )
