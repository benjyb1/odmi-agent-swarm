"""EXP-42: the corroborative arm is a coherent stance, and the frozen set has
an auditable second-touch door.

Three defects blocked the EXP-42 dispatch. These tests pin all three fixes.

1. **Search direction.** EXP-40's cooperative arm searched adversarially. The
   shared `generate_adversarial_queries` told the model to find evidence
   AGAINST the answer, while corroborate step 4 told the verifier to look for
   support, so the corroborating verifier was handed counter-evidence and asked
   to corroborate from it. `verifier-corroborate` now generates its own
   support-seeking queries.

2. **Rigour parity.** Corroborate V2 dropped disprove V4's staleness criterion
   with no equivalent, so the corroborative verifier was missing a gate its
   comparator had. V3 restores the corroborative mirror.

3. **The D47 door.** The freeze guard had one exemption, `headline: true`, which
   EXP-42 must not claim because EXP-36 is the headline. A second touch now
   needs an explicit flag plus a logged justification, so it is auditable rather
   than a removed check.

See docs/EXPERIMENTS_EXP42_STANCE_HELDOUT.md.
"""

from __future__ import annotations

import pytest

from agents import verifier
from agents.models import LLMUsage, ResearcherOutput, VerifierInput, VerifierOutput
from agents.prompts import verifier as vp
from agents.tools.search import SearchResult
from scripts.run_experiments import preflight


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


def _verifier_input(strategy: str) -> VerifierInput:
    return VerifierInput(
        question_id="P1",
        question_text="Is there a national open data policy?",
        country_code="FI",
        country_name="Finland",
        researcher_output=_researcher_output(),
        strategy=strategy,
        answer_shape="binary",
        allowed_answers=["yes", "no"],
        researcher_snippets=["a literal quote from the source is right here"],
    )


def _install_common_mocks(monkeypatch):
    monkeypatch.setattr(verifier.db_helpers, "ensure_prompt_version", lambda *a, **k: 1)

    def fake_main_call(*, system, user_message, **kw):
        return (
            VerifierOutput(
                verdict="pass", verifier_answer="yes",
                verifier_confidence=0.8, substring_check_result="pass",
            ),
            _usage("baseline"),
        )

    monkeypatch.setattr(verifier, "call_for_structured", fake_main_call)


def _install_query_gen_spies(monkeypatch):
    """Spy on both generators so a test can assert which one the run used."""
    calls = {"adversarial": 0, "corroborative": 0, "search": 0}

    def fake_adversarial(inp, **kw):
        calls["adversarial"] += 1
        return ["against q1", "against q2"], _usage("verifier_query_gen")

    def fake_corroborative(inp, **kw):
        calls["corroborative"] += 1
        return ["support q1", "support q2"], _usage("verifier_corroborative_query_gen")

    def fake_search_many(queries, **kw):
        calls["search"] += 1
        return [SearchResult(
            url="https://other.example/x", title="A title",
            snippet="an independent snippet", provider="diy",
        )]

    monkeypatch.setattr(verifier, "generate_adversarial_queries", fake_adversarial)
    monkeypatch.setattr(verifier, "generate_corroborative_queries", fake_corroborative)
    monkeypatch.setattr(verifier, "search_many", fake_search_many)
    return calls


# ============================================================
# 1. Search direction follows the stance
# ============================================================

def test_corroborative_generator_exists_and_seeks_support():
    """The generator must ask for evidence FOR the answer. A corroborative
    verifier fed counter-evidence measures nothing."""
    assert hasattr(verifier, "generate_corroborative_queries")
    system = verifier._CORROBORATIVE_QUERY_GEN_SYSTEM
    assert "AGAINST" not in system, "the corroborative generator must not search against"
    assert "opposite label" not in system
    assert "SUPPORT" in system or "support" in system


def test_corroborate_strategy_uses_corroborative_queries(monkeypatch):
    """The whole point of EXP-42: stance moves search direction and verdict
    burden together."""
    _install_common_mocks(monkeypatch)
    calls = _install_query_gen_spies(monkeypatch)

    result = verifier.run_verifier(_verifier_input("verifier-corroborate"))

    assert calls["corroborative"] == 1, "corroborate must generate support-seeking queries"
    assert calls["adversarial"] == 0, "corroborate must not generate adversarial queries"
    assert calls["search"] == 1
    assert result.output is not None and result.output.verdict == "pass"


def test_disprove_strategy_still_uses_adversarial_queries(monkeypatch):
    """Production must be untouched. Arm A of EXP-42 is a replay of these rows."""
    _install_common_mocks(monkeypatch)
    calls = _install_query_gen_spies(monkeypatch)

    verifier.run_verifier(_verifier_input("verifier-disprove"))

    assert calls["adversarial"] == 1
    assert calls["corroborative"] == 0


def test_never_policy_skips_both_generators(monkeypatch):
    """The EXP-14 'never' knob composes with the stance knob."""
    _install_common_mocks(monkeypatch)
    calls = _install_query_gen_spies(monkeypatch)

    verifier.run_verifier(_verifier_input("verifier-corroborate"), verifier_search="never")

    assert calls["adversarial"] == 0
    assert calls["corroborative"] == 0
    assert calls["search"] == 0


# ============================================================
# 2. Corroborate V3 restores the rigour gate
# ============================================================

def test_corroborate_is_v3():
    assert vp.STRATEGIES["verifier-corroborate"].version == 3


def test_corroborate_v3_has_the_staleness_mirror():
    """Disprove V4 rejects vague, paraphrased or out-of-date evidence. V2 had no
    equivalent, so the corroborative arm was missing a gate its comparator had."""
    system = vp.STRATEGIES["verifier-corroborate"].system.lower()
    assert "out-of-date" in system
    assert "does not constitute corroboration" in system


def test_corroborate_v3_does_not_import_the_adversarial_framing():
    """The mirror must be phrased as a corroboration bar, not a rejection bar;
    importing disprove's wording would import the opposing stance."""
    system = vp.STRATEGIES["verifier-corroborate"].system
    assert "is grounds for rejection" not in system
    assert "Your default stance is scepticism" not in system


def test_corroborate_v3_keeps_steps_1_to_3_shared_with_disprove():
    """The one variable is stance. Steps 1-3 stay byte-identical so the contrast
    is not confounded by the substring gate, source authority or evidence fit."""
    corr = vp.STRATEGIES["verifier-corroborate"].system
    disp = vp.STRATEGIES["verifier-disprove"].system
    for step in ("1. Substring check.", "2. Source authority.", "3. Evidence fit."):
        assert step in corr and step in disp
    start, end = "1. Substring check.", "4."
    assert corr[corr.index(start):corr.index(end)] == disp[disp.index(start):disp.index(end)]


# ============================================================
# 3. The D47 second-touch door is auditable
# ============================================================

def _heldout_spec():
    return {
        "run_id": "exp42_stance_heldout",
        "global_parallel": 3,
        "budget_calls": 60000,
        "experiments": [
            {
                "experiment_id": "exp42_stance_heldout",
                "type": "accuracy",
                "questions": ["P1", "P2"],
                "countries": ["FI"],
                # No `strategy` pin: the coordinator derives
                # `verifier-corroborate` from pipeline_mode, and pinning it on
                # the command line is an argparse error. See the guard below.
                "baseline_knobs": {"verifier_search": "always"},
                "arms": [{"condition_label": "FI", "knobs": {"pipeline_mode": "cooperative"}}],
            }
        ],
    }


def test_heldout_still_blocked_without_the_flag():
    """Regression: the default door stays shut."""
    assert any("held-out" in e for e in preflight(_heldout_spec()))


def test_second_touch_flag_with_justification_opens_the_door():
    spec = _heldout_spec()
    spec["heldout_second_touch"] = True
    spec["heldout_second_touch_justification"] = (
        "EXP-42 characterisation, no adoption rule; supervisor sign-off 2026-07-29."
    )
    assert preflight(spec) == []


def test_second_touch_without_justification_is_refused():
    """An override with no logged reason is a removed check, not an audit trail."""
    spec = _heldout_spec()
    spec["heldout_second_touch"] = True
    errors = preflight(spec)
    assert any("justification" in e for e in errors)


def test_second_touch_will_not_smuggle_a_dev_country():
    """The door opens for a frozen-set re-measurement only. Mixing dev countries
    in would make it a general bypass."""
    spec = _heldout_spec()
    spec["heldout_second_touch"] = True
    spec["heldout_second_touch_justification"] = "supervisor sign-off"
    spec["experiments"][0]["countries"] = ["FI", "NL"]
    assert any("held-out" in e for e in preflight(spec))


def test_cooperative_spec_may_not_pin_the_corroborate_strategy():
    """`verifier-corroborate` is not a `--strategy` CLI choice: the coordinator
    derives it from `pipeline_mode=cooperative` and overrides whatever was
    passed. A spec that pins it dies at dispatch with an argparse error, after
    the orchestrator has already reported preflight clean. Catch it at preflight.
    """
    spec = _heldout_spec()
    spec["heldout_second_touch"] = True
    spec["heldout_second_touch_justification"] = "supervisor sign-off"
    spec["experiments"][0]["baseline_knobs"]["strategy"] = "verifier-corroborate"
    errors = preflight(spec)
    assert any("verifier-corroborate" in e and "pipeline_mode" in e for e in errors)


def test_arm_level_corroborate_pin_is_caught_too():
    """Arm knobs override baseline knobs, so both levels need the check."""
    spec = _heldout_spec()
    spec["heldout_second_touch"] = True
    spec["heldout_second_touch_justification"] = "supervisor sign-off"
    spec["experiments"][0]["arms"][0]["knobs"]["strategy"] = "verifier-corroborate"
    assert any("verifier-corroborate" in e for e in preflight(spec))


def test_second_touch_must_not_claim_headline():
    """EXP-36 is the headline. A second flag would corrupt the receipts."""
    spec = _heldout_spec()
    spec["heldout_second_touch"] = True
    spec["heldout_second_touch_justification"] = "supervisor sign-off"
    spec["headline"] = True
    assert any("headline" in e for e in preflight(spec))
