"""Tests for the EXP-11 tristate verifier models and prompt wiring.

The validators encode the burden of proof: a refute needs counter-
evidence, a confirm needs corroboration, inconclusive needs nothing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.models import ProbeFinding, VerifierOutputTristate
from agents.prompts import verifier as vp


def _base(**over):
    d = dict(
        verdict="inconclusive",
        verifier_answer="no",
        verifier_confidence=0.5,
        substring_check_result="pass",
    )
    d.update(over)
    return d


def test_inconclusive_needs_nothing():
    out = VerifierOutputTristate(**_base())
    assert out.verdict == "inconclusive"


def test_refute_requires_reason_and_counter_evidence():
    with pytest.raises(ValidationError):
        VerifierOutputTristate(**_base(verdict="refute"))
    with pytest.raises(ValidationError):
        # reason but no counter quote/url
        VerifierOutputTristate(**_base(verdict="refute", rejection_reason="wrong"))
    ok = VerifierOutputTristate(**_base(
        verdict="refute", rejection_reason="portal exposes an API",
        counter_evidence_quote="The portal exposes a documented REST API for all datasets",
    ))
    assert ok.verdict == "refute"


def test_confirm_requires_corroboration():
    with pytest.raises(ValidationError):
        VerifierOutputTristate(**_base(verdict="confirm"))
    ok = VerifierOutputTristate(**_base(
        verdict="confirm",
        corroborating_quote="An independent registry lists the same enacted instrument",
    ))
    assert ok.verdict == "confirm"


def test_confirm_url_only_is_valid():
    ok = VerifierOutputTristate(**_base(
        verdict="confirm",
        corroborating_url="https://example.gov/registry",
    ))
    assert ok.corroborating_url is not None


def test_probe_findings_round_trip():
    out = VerifierOutputTristate(**_base(
        verdict="inconclusive",
        probe_findings=[
            ProbeFinding(query="malta portal api docs", found=False),
            ProbeFinding(query="malta data api", found=True, quote="REST API available"),
        ],
    ))
    assert len(out.probe_findings) == 2
    assert out.probe_findings[1].found is True


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        VerifierOutputTristate(**_base(some_unknown_field=1))


def test_both_tristate_strategies_registered():
    assert "verifier-tristate" in vp.STRATEGIES
    assert "verifier-tristate-probes" in vp.STRATEGIES
    # The four production strategies are still present.
    for s in ("verifier-disprove", "verifier-negation",
              "verifier-steelman", "verifier-blind"):
        assert s in vp.STRATEGIES
    # Tristate system prompts carry the tristate schema, not the binary one.
    assert "VerifierOutputTristate" in vp.STRATEGIES["verifier-tristate"].system
    assert "refute" in vp.STRATEGIES["verifier-tristate"].system


def test_probe_block_renders_only_when_absence():
    none = vp._probe_block([], [])
    assert "none run" in none
    some = vp._probe_block(["malta portal api"], ["Malta API docs page"])
    assert "Confirmation probes" in some
    assert "malta portal api" in some


def test_tristate_user_message_includes_probes_when_asked():
    from agents.models import ResearcherOutput
    ro = ResearcherOutput(
        answer="no", answer_explanation="No API found in the portal docs",
        evidence_quote="The portal documentation lists no programmatic access",
        source_url="https://data.gov.mt/",
        retrieval_confidence=0.6, answer_confidence=0.55,
    )
    msg = vp.build_tristate_user_message(
        question_text="Does the portal expose an API?",
        country_name="Malta", country_code="MT",
        researcher_output=ro, substring_result="pass", substring_notes=None,
        independent_queries=["q"], independent_snippets=["s"],
        answer_shape="binary", allowed_answers=["yes", "no"],
        probe_queries=["malta portal api documentation"],
        probe_snippets=["Malta open data API reference"],
        include_probes=True,
    )
    assert "Confirmation probes" in msg
    assert "VerifierOutputTristate" in msg
    # Without include_probes the block is absent.
    msg2 = vp.build_tristate_user_message(
        question_text="Q", country_name="Malta", country_code="MT",
        researcher_output=ro, substring_result="pass", substring_notes=None,
        independent_queries=["q"], independent_snippets=["s"],
    )
    assert "Confirmation probes" not in msg2
