"""Offline tests for the EXP-10 Malta failure-mode audit (no DB, no network)."""
import re
from pathlib import Path

import evaluation.malta_failure_audit as mfa

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---- classify_match ----

def test_classify_match_exact_and_prefix_and_no():
    assert mfa.classify_match("yes", "yes") == "match"
    assert mfa.classify_match("yes", "Yes, or all providers already publish") == "match"
    assert mfa.classify_match("no", "no") == "match"


def test_classify_match_abstain_vs_differ():
    assert mfa.classify_match("inconclusive", "no") == "abstain"
    assert mfa.classify_match("not_applicable", "yes") == "abstain"
    assert mfa.classify_match("yes", "no") == "differ"


def test_classify_match_near_band():
    allowed = ["<10%", "10-50%", "50-90%", ">90%"]
    assert mfa.classify_match("10-50%", "50-90%", allowed, "percentage_band") == "near_match"
    assert mfa.classify_match("<10%", ">90%", allowed, "percentage_band") == "differ"


def test_classify_match_missing_data():
    assert mfa.classify_match("yes", "") == "no_ground_truth"
    assert mfa.classify_match("", "yes") == "no_swarm_answer"


def test_answer_matches_gold():
    assert mfa.answer_matches_gold("yes", "Yes, or all providers")
    assert mfa.answer_matches_gold("no", "no")
    assert not mfa.answer_matches_gold("yes", "no")
    assert not mfa.answer_matches_gold("inconclusive", "no")


# ---- code_cause (priority order) ----

def _abstain(**kw):
    base = dict(match_status="abstain", notes="", has_source=True, has_snippets=True,
                substring_failed=False, candidate_is_definite=False, candidate_confidence=None)
    base.update(kw)
    return base


def test_cause_fetch_beats_floor():
    p = _abstain(notes="HEAD/GET returned status 403", candidate_is_definite=True,
                 candidate_confidence=0.5)
    assert mfa.code_cause(p) == "fetch_4xx_5xx"


def test_cause_no_source():
    assert mfa.code_cause(_abstain(has_source=False, has_snippets=False)) == "no_source_found"


def test_cause_substring_gate():
    assert mfa.code_cause(_abstain(substring_failed=True)) == "substring_gate"


def test_cause_below_floor():
    p = _abstain(candidate_is_definite=True, candidate_confidence=0.58)
    assert mfa.code_cause(p) == "below_floor"


def test_cause_abstain_other():
    # definite candidate above the floor but still abstained: unexplained
    p = _abstain(candidate_is_definite=True, candidate_confidence=0.9)
    assert mfa.code_cause(p) == "abstain_other"


def test_cause_near_band_and_wrong_and_structural():
    assert mfa.code_cause(dict(match_status="near_match")) == "near_band"
    assert mfa.code_cause(dict(match_status="differ", is_structural_gold=False)) == "wrong_answer"
    assert mfa.code_cause(dict(match_status="differ", is_structural_gold=True)) == "selfreport_denylist_ceiling"


# ---- floor_sweep ----

def _pair(conf, correct, neg, definite=True):
    return dict(candidate_is_definite=definite, candidate_confidence=conf,
                candidate_correct=correct, is_negative_gold=neg)


def test_floor_sweep_recovers_and_flags_false_positive():
    pairs = [
        _pair(0.90, True, False),   # committed everywhere
        _pair(0.60, True, False),   # recovered below 0.65, correct
        _pair(0.58, False, True),   # recovered below 0.65, false positive on a negative gold
        _pair(None, False, False, definite=False),  # never a candidate
    ]
    sw = mfa.floor_sweep(pairs, [0.65, 0.55, 0.50])
    assert sw[0.65]["committed"] == 1 and sw[0.65]["recovered"] == 0
    assert sw[0.55]["recovered"] == 2
    assert sw[0.55]["recovered_correct"] == 1 and sw[0.55]["recovered_fp"] == 1
    assert sw[0.55]["recovery_precision"] == 0.5
    assert sw[0.55]["fpr_neg"] == 1.0   # the one negative gold got a false yes
    assert sw[0.65]["fpr_neg"] == 0.0


def test_floor_sweep_committed_real_bypasses_floor():
    # an adjudicator commit at 0.50 confidence stays committed at every floor and
    # is never counted as floor-recovered (the floor only gates the verifier path).
    p = _pair(0.50, True, False)
    p["committed_real"] = True
    sw = mfa.floor_sweep([p], [0.65, 0.55, 0.50])
    assert sw[0.65]["committed"] == 1 and sw[0.65]["correct"] == 1
    assert sw[0.50]["recovered"] == 0


def test_decide_floor_rejects_when_precision_low():
    pairs = [_pair(0.90, True, False), _pair(0.58, False, True)]
    sw = mfa.floor_sweep(pairs, [0.65, 0.55, 0.50])
    dec = mfa.decide_floor(sw, baseline=0.65)
    assert dec["recommended_floor"] == 0.65  # stays at baseline
    assert dec["verdicts"][0.55]["passes"] is False


def test_decide_floor_adopts_when_clean():
    pairs = [_pair(0.60, True, False), _pair(0.62, True, False)]
    sw = mfa.floor_sweep(pairs, [0.65, 0.55, 0.50])
    dec = mfa.decide_floor(sw, baseline=0.65)
    assert dec["recommended_floor"] == 0.55
    assert dec["verdicts"][0.55]["passes"] is True


# ---- the baseline floor must stay in sync with the coordinator ----

def test_baseline_floor_in_sync_with_coordinator():
    src = (REPO_ROOT / "scripts" / "run_coordinator.py").read_text()
    m = re.search(r"COMMIT_CONFIDENCE_FLOOR\s*=\s*([0-9.]+)", src)
    assert m, "could not find COMMIT_CONFIDENCE_FLOOR in run_coordinator.py"
    assert float(m.group(1)) == mfa.BASELINE_FLOOR
