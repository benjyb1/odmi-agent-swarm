"""Tests for the cross-family reliability backfill (EXP-1).

There are NO live judge calls here. The whole point of the backfill is that the
evidence is frozen, so the network is mocked: ``judge_verdict_for`` is patched in
the ``run_backfill`` tests, and the ``cached_adjudicate``-routed judge call is
patched at its module boundary where the orientation plumbing is exercised.

Coverage:
- ``compute_reliability`` pairs [opus, judge] verdicts and returns the right
  raw agreement, Krippendorff's alpha (matched against the stats module on the
  same units), error handling (errored pairs excluded and counted), and a
  confusion breakdown.
- ``run_backfill`` reads a hand-made EXP-1-shaped result, re-judges the recorded
  subsample with a mocked judge verdict per pair, and surfaces a per-pair list
  plus the reliability summary; a per-pair judge error is caught and recorded,
  not raised.
- ``judge_verdict_for`` position-swaps and combines exactly like the Opus
  harness (mocked at the adjudicate boundary, so the orientation -> DIY-frame ->
  combine plumbing is what is under test, not the network).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import evaluation.cross_family_backfill as cfb
from agents.tools.search_adjudicator import AdjudicationResult
from evaluation.stats import krippendorff_alpha


# compute_reliability: pairing + agreement + alpha + confusion

def test_perfect_agreement_alpha_one():
    """Identical verdicts on every pair => agreement 1.0 and alpha 1.0."""
    per_pair = [
        {"pair_id": "P1/FR", "opus_verdict": "diy", "judge_verdict": "diy"},
        {"pair_id": "P2/FR", "opus_verdict": "tavily", "judge_verdict": "tavily"},
        {"pair_id": "P3/FR", "opus_verdict": "both_fail", "judge_verdict": "both_fail"},
    ]
    rel = cfb.compute_reliability(per_pair)
    assert rel["n_subsample"] == 3
    assert rel["n_judged"] == 3
    assert rel["n_errors"] == 0
    assert rel["raw_agreement"] == 1.0
    assert rel["krippendorff_alpha"] == 1.0


def test_agreement_and_alpha_match_stats_module():
    """Raw agreement is the fraction of identical pairs; alpha matches stats.

    Three of four judged pairs agree, so raw agreement is 0.75. Alpha is checked
    against the project's own estimator on the same [opus, groq] units, so this
    test pins the wiring (which units are built, in which order) rather than
    re-deriving the coefficient by hand.
    """
    per_pair = [
        {"pair_id": "P1/FR", "opus_verdict": "diy", "judge_verdict": "diy"},
        {"pair_id": "P2/FR", "opus_verdict": "diy", "judge_verdict": "tavily"},
        {"pair_id": "P3/FR", "opus_verdict": "tie", "judge_verdict": "tie"},
        {"pair_id": "P4/FR", "opus_verdict": "both_fail", "judge_verdict": "both_fail"},
    ]
    rel = cfb.compute_reliability(per_pair)
    assert rel["n_judged"] == 4
    assert rel["raw_agreement"] == pytest.approx(0.75)

    expected_units = [
        ["diy", "diy"], ["diy", "tavily"], ["tie", "tie"], ["both_fail", "both_fail"],
    ]
    assert rel["krippendorff_alpha"] == pytest.approx(
        krippendorff_alpha(expected_units, level="nominal")
    )


def test_errored_pair_excluded_from_denominators():
    """A pair with an error is counted under n_errors and excluded elsewhere.

    The errored pair must not enter the agreement denominator or the alpha
    units, so a Groq failure cannot silently move the statistics. Here two of
    three JUDGED pairs agree => 2/3, computed over the judged pairs only.
    """
    per_pair = [
        {"pair_id": "P1/FR", "opus_verdict": "diy", "judge_verdict": "diy"},
        {"pair_id": "P2/FR", "opus_verdict": "tavily", "judge_verdict": "tavily"},
        {"pair_id": "P3/FR", "opus_verdict": "diy", "judge_verdict": "tavily"},
        {"pair_id": "P4/FR", "opus_verdict": "tie", "judge_verdict": None,
         "error": "GroqAuthError: HTTP 429"},
    ]
    rel = cfb.compute_reliability(per_pair)
    assert rel["n_subsample"] == 4
    assert rel["n_judged"] == 3
    assert rel["n_errors"] == 1
    assert rel["raw_agreement"] == pytest.approx(2 / 3)
    # The single disagreement is opus=diy vs groq=tavily.
    assert rel["confusion"]["diy"]["tavily"] == 1
    assert rel["confusion"]["diy"]["diy"] == 1
    assert rel["confusion"]["tavily"]["tavily"] == 1


def test_empty_subsample_is_safe():
    """No pairs => n=0, agreement 0.0, alpha None (nothing to score)."""
    rel = cfb.compute_reliability([])
    assert rel["n_subsample"] == 0
    assert rel["n_judged"] == 0
    assert rel["raw_agreement"] == 0.0
    assert rel["krippendorff_alpha"] is None


# run_backfill: end-to-end on a hand-made frozen result, Groq mocked

def _write_result(path, pair_ids, verdict_by_pair, seed=99):
    """Write a minimal EXP-1-shaped JSONL: summary line then per-pair records."""
    summary = {
        "model": "claude-opus-4-6",
        "subsample": {"seed": seed, "frac": 0.3, "pair_ids": pair_ids},
    }
    lines = [json.dumps(summary)]
    for pid in pair_ids:
        qid, cc = pid.split("/")
        lines.append(json.dumps({
            "question_id": qid,
            "country_code": cc,
            "dimension": "Impact",
            "question_text": f"Question {qid}?",
            "gold": "ANSWER: Yes",
            "verdict": verdict_by_pair[pid],
            "diy_evidence": [{"url": "https://a.fr/x", "snippet": "diy snippet"}],
            "tavily_evidence": [{"url": "https://b.com/y", "snippet": "tav snippet"}],
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_run_backfill_pairs_and_summarises(tmp_path):
    """End-to-end: subsample re-judged with a mocked judge verdict per pair.

    The judge is stubbed at ``judge_verdict_for`` so each pair gets a
    deterministic verdict (no network). The summary must pair each record's Opus
    verdict with the stubbed judge verdict, report the right agreement and a
    real alpha, and write one summary line plus one record per subsample pair.
    """
    result = tmp_path / "exp1.jsonl"
    pair_ids = ["P1/FR", "P2/FR", "P3/FR"]
    opus = {"P1/FR": "diy", "P2/FR": "tavily", "P3/FR": "both_fail"}
    _write_result(result, pair_ids, opus)

    # Stubbed judge verdicts: P1 agrees, P2 flips to diy, P3 agrees.
    judge = {"P1/FR": "diy", "P2/FR": "diy", "P3/FR": "both_fail"}

    def fake_judge_verdict_for(rec, *, adjudicate_fn, model):
        pid = f"{rec['question_id']}/{rec['country_code']}"
        return {"verdict": judge[pid], "consistent": True,
                "orientation_1": {"winner": "A", "diy_frame": judge[pid]},
                "orientation_2": {"winner": "B", "diy_frame": judge[pid]}}

    with patch.object(cfb, "judge_verdict_for", side_effect=fake_judge_verdict_for):
        out = cfb.run_backfill(result)

    summary = out["summary"]
    assert summary["n_subsample"] == 3
    assert summary["n_judged"] == 3
    assert summary["n_errors"] == 0
    assert summary["opus_model"] == "claude-opus-4-6"
    assert summary["judge_family"] == "groq"
    assert summary["judge_model"] == cfb.GROQ_JUDGE_MODEL
    # P1 and P3 agree, P2 disagrees => 2/3.
    assert summary["raw_agreement"] == pytest.approx(2 / 3)
    assert summary["confusion"]["tavily"]["diy"] == 1

    by_pair = {p["pair_id"]: p for p in out["per_pair"]}
    assert by_pair["P2/FR"]["opus_verdict"] == "tavily"
    assert by_pair["P2/FR"]["judge_verdict"] == "diy"
    assert len(out["per_pair"]) == 3


def test_run_backfill_mistral_judge_records_family(tmp_path):
    """Selecting --judge mistral routes the Mistral fn and records its family.

    The judge is stubbed at ``judge_verdict_for`` so no network is touched; the
    test pins that ``run_backfill(judge='mistral')`` resolves the Mistral model
    and writes ``judge_family='mistral'`` into the summary receipt.
    """
    result = tmp_path / "exp1.jsonl"
    pair_ids = ["P1/FR", "P2/FR"]
    opus = {"P1/FR": "diy", "P2/FR": "tavily"}
    _write_result(result, pair_ids, opus)

    def fake_judge_verdict_for(rec, *, adjudicate_fn, model):
        # The Mistral family's default model must have been resolved.
        assert model == cfb.MISTRAL_JUDGE_MODEL
        assert adjudicate_fn is cfb.adjudicate_mistral
        return {"verdict": "diy", "consistent": True,
                "orientation_1": {}, "orientation_2": {}}

    with patch.object(cfb, "judge_verdict_for", side_effect=fake_judge_verdict_for):
        out = cfb.run_backfill(result, judge="mistral")

    summary = out["summary"]
    assert summary["judge_family"] == "mistral"
    assert summary["judge_model"] == cfb.MISTRAL_JUDGE_MODEL


def test_run_backfill_catches_per_pair_judge_error(tmp_path):
    """A judge error on one pair is recorded, not raised; the rest still judge."""
    result = tmp_path / "exp1.jsonl"
    pair_ids = ["P1/FR", "P2/FR"]
    opus = {"P1/FR": "diy", "P2/FR": "tavily"}
    _write_result(result, pair_ids, opus)

    def flaky(rec, *, adjudicate_fn, model):
        pid = f"{rec['question_id']}/{rec['country_code']}"
        if pid == "P2/FR":
            raise RuntimeError("Judge HTTP 500")
        return {"verdict": "diy", "consistent": True,
                "orientation_1": {}, "orientation_2": {}}

    with patch.object(cfb, "judge_verdict_for", side_effect=flaky):
        out = cfb.run_backfill(result)

    summary = out["summary"]
    assert summary["n_judged"] == 1
    assert summary["n_errors"] == 1
    by_pair = {p["pair_id"]: p for p in out["per_pair"]}
    assert "error" in by_pair["P2/FR"]
    assert by_pair["P2/FR"]["judge_verdict"] is None
    # The healthy pair agrees, so agreement over the judged set is 1.0.
    assert summary["raw_agreement"] == 1.0


# judge_verdict_for: position-swap + DIY-frame combination (adjudicate mocked)

def _adj(winner):
    return AdjudicationResult(
        winner=winner, answer_supported_by_a="x", answer_supported_by_b="y",
        reasoning="because", confidence=0.8,
    )


def test_judge_verdict_for_combines_position_swapped(tmp_path):
    """Both orientations call DIY the winner => combined DIY verdict.

    Orientation 1 has DIY in slot A and the judge picks "A"; orientation 2 swaps
    so DIY is slot B and the judge picks "B". Both map to "diy" in the DIY frame,
    so the combined verdict is "diy" and consistent. The adjudicate function is
    mocked, so the orientation plumbing is what is under test, not the network.
    """
    rec = {
        "question_id": "P1", "country_code": "FR",
        "question_text": "Q?", "gold": "ANSWER: Yes",
        "diy_evidence": [{"url": "https://a.fr/x", "snippet": "diy"}],
        "tavily_evidence": [{"url": "https://b.com/y", "snippet": "tav"}],
    }
    # Orientation 1 -> winner "A" (= DIY in slot A); orientation 2 -> winner "B"
    # (= DIY in slot B). Returned in call order.
    winners = ["A", "B"]
    calls = {"n": 0}

    def fake_adjudicate(*, question_text, ground_truth, evidence_a, evidence_b,
                        model, answer_blind=False, **kw):
        w = winners[calls["n"]]
        calls["n"] += 1
        return _adj(w), object()  # usage is discarded by the harness

    with patch(
        "evaluation.cross_family_backfill.cached_adjudicate",
        side_effect=fake_adjudicate,
    ):
        judged = cfb.judge_verdict_for(rec)

    assert calls["n"] == 2  # exactly two position-swapped calls
    assert judged["verdict"] == "diy"
    assert judged["consistent"] is True
    assert judged["orientation_1"]["diy_frame"] == "diy"
    assert judged["orientation_2"]["diy_frame"] == "diy"
