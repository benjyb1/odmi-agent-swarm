"""Tests for the EXP-7 chaining analysis harness (evaluation/chaining_analysis.py).

The pure layer (PairOutcome classifiers, arm_summary, paired_comparison) is
tested with synthetic outcomes, no DB. One focused DB test builds a minimal
SQLite database to confirm load_outcomes splits the arms, reuses the match SQL,
and counts calls. All offline.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.chaining_analysis import (
    FALSE_POSITIVE_MARGIN,
    PairOutcome,
    analyse,
    arm_summary,
    gold_class,
    is_abstention,
    is_committed,
    is_false_positive,
    load_outcomes,
    paired_comparison,
    recovered,
)


def _o(qid="Q1", cc="MT", arm="baseline", status="accepted_by_verifier",
       final="yes", gold="yes", match="match", calls=4) -> PairOutcome:
    return PairOutcome(
        question_id=qid, country_code=cc, arm=arm, terminal_status=status,
        final_answer=final, gold_answer=gold, match_status=match, calls=calls,
    )


# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------

def test_is_abstention():
    assert is_abstention("inconclusive") is True
    assert is_abstention("  Inconclusive ") is True
    assert is_abstention("yes") is False
    assert is_abstention("not_applicable") is False
    assert is_abstention(None) is False


def test_is_committed():
    assert is_committed(_o(status="accepted_by_verifier", final="yes")) is True
    assert is_committed(_o(status="accepted_by_adjudicator", final="no")) is True
    # An abstention is not a commit even on a committed status.
    assert is_committed(_o(status="accepted_by_adjudicator", final="inconclusive")) is False
    # An escalation is not a commit.
    assert is_committed(_o(status="escalated_adjudicator", final="inconclusive")) is False
    assert is_committed(_o(status="agent_failure", final=None)) is False


def test_recovered_only_on_match():
    assert recovered(_o(match="match")) is True
    assert recovered(_o(match="near_match")) is False
    assert recovered(_o(match="differ")) is False


def test_is_false_positive():
    # Committed and wrong.
    assert is_false_positive(_o(status="accepted_by_verifier", final="no",
                                match="differ")) is True
    # Committed and right.
    assert is_false_positive(_o(match="match")) is False
    # Abstained and wrong is not a false positive (no commit was made).
    assert is_false_positive(_o(status="escalated_adjudicator",
                                final="inconclusive", match="differ")) is False


def test_gold_class():
    assert gold_class("yes") == "yes"
    assert gold_class("Yes, fully") == "yes"
    assert gold_class("no") == "no"
    assert gold_class("71-90%") == "other"
    assert gold_class("") == "other"
    assert gold_class(None) == "other"


# ---------------------------------------------------------------------------
# arm_summary
# ---------------------------------------------------------------------------

def test_arm_summary_balance_aware():
    outcomes = [
        _o("Q1", gold="yes", final="yes", match="match",
           status="accepted_by_verifier", calls=4),       # yes recovered
        _o("Q2", gold="no", final="yes", match="differ",
           status="accepted_by_verifier", calls=6),        # no, FP
        _o("Q3", gold="no", final="no", match="match",
           status="accepted_by_verifier", calls=8),        # no recovered
        _o("Q4", gold="yes", final="inconclusive", match="differ",
           status="escalated_adjudicator", calls=2),        # abstained
    ]
    s = arm_summary(outcomes)
    assert s["n"] == 4
    assert s["n_committed"] == 3
    assert s["n_abstained"] == 1
    assert s["n_recovered"] == 2
    # Per-class recall: yes 1/2, no 1/2 -> balanced 0.5.
    assert s["per_class_recall"]["yes"]["rate"] == 0.5
    assert s["per_class_recall"]["no"]["rate"] == 0.5
    assert s["balanced_accuracy"] == 0.5
    # False positive: 1 committed-but-wrong (Q2) over 3 committed.
    assert s["false_positive_rate"]["successes"] == 1
    assert s["false_positive_rate"]["n"] == 3
    assert abs(s["false_positive_rate"]["rate"] - 1 / 3) < 1e-9
    # Abstention rate 1/4.
    assert s["abstention_rate"]["rate"] == 0.25
    # Calls per resolved (committed) pair: (4+6+8)/3 = 6.
    assert s["calls_per_resolved_pair"] == 6.0


def test_arm_summary_balanced_accuracy_none_when_one_class_absent():
    # All yes-gold: balanced accuracy needs both classes, so it is None.
    outcomes = [_o("Q1", gold="yes"), _o("Q2", gold="yes")]
    s = arm_summary(outcomes)
    assert s["per_class_recall"]["no"]["rate"] is None
    assert s["balanced_accuracy"] is None


def test_arm_summary_empty():
    s = arm_summary([])
    assert s["n"] == 0
    assert s["balanced_accuracy"] is None
    assert s["calls_per_resolved_pair"] is None


# ---------------------------------------------------------------------------
# paired_comparison
# ---------------------------------------------------------------------------

def _paired_fixture():
    baseline = [
        _o("Q1", gold="yes", final="yes", match="match",
           status="accepted_by_verifier", calls=6),
        _o("Q2", gold="no", final="yes", match="differ",
           status="accepted_by_verifier", calls=6),         # FP
        _o("Q3", gold="no", final="inconclusive", match="differ",
           status="escalated_adjudicator", calls=8),         # abstained
    ]
    chained = [
        _o("Q1", arm="chained", gold="yes", final="yes", match="match",
           status="accepted_by_verifier", calls=8),
        _o("Q2", arm="chained", gold="no", final="no", match="match",
           status="accepted_by_verifier", calls=8),          # recovered
        _o("Q3", arm="chained", gold="no", final="no", match="match",
           status="accepted_by_verifier", calls=10),         # recovered
    ]
    return baseline, chained


def test_paired_comparison_recovery_mcnemar():
    baseline, chained = _paired_fixture()
    p = paired_comparison(baseline, chained)
    assert p["n_paired"] == 3
    rec = p["recovery_mcnemar"]
    # Chained recovers Q2 and Q3 that baseline did not; baseline recovers none
    # that chained did not.
    assert rec["discordant_chained_only"] == 2
    assert rec["discordant_baseline_only"] == 0
    assert rec["p_value"] == 0.5  # mcnemar_exact(0, 2)


def test_paired_comparison_false_positive_mcnemar():
    baseline, chained = _paired_fixture()
    p = paired_comparison(baseline, chained)
    fp = p["false_positive_mcnemar"]
    # Baseline has one FP (Q2) that chained fixed; chained has none baseline lacks.
    assert fp["discordant_baseline_only"] == 1
    assert fp["discordant_chained_only"] == 0
    assert fp["p_value"] == 1.0  # mcnemar_exact(1, 0)


def test_paired_comparison_joint_verdict_passes():
    baseline, chained = _paired_fixture()
    p = paired_comparison(baseline, chained)
    jc = p["joint_confirmatory"]
    # Chained: balanced accuracy up (0.5 -> 1.0), false-positive down -> passes.
    assert jc["balanced_accuracy_non_decrease"] is True
    assert jc["false_positive_not_raised"] is True
    assert jc["passes"] is True
    assert jc["false_positive_margin"] == FALSE_POSITIVE_MARGIN
    # All call deltas were +2.
    assert p["median_call_delta"] == 2


def test_joint_verdict_fails_when_false_positive_rises():
    # Chained recovers more but commits a fresh wrong answer on a no-gold pair.
    baseline = [
        _o("Q1", gold="yes", final="inconclusive", match="differ",
           status="escalated_adjudicator", calls=6),         # abstained
        _o("Q2", gold="no", final="no", match="match",
           status="accepted_by_verifier", calls=6),
    ]
    chained = [
        _o("Q1", arm="chained", gold="yes", final="yes", match="match",
           status="accepted_by_verifier", calls=8),          # recovered
        _o("Q2", arm="chained", gold="no", final="yes", match="differ",
           status="accepted_by_verifier", calls=8),          # NEW false positive
    ]
    p = paired_comparison(baseline, chained)
    jc = p["joint_confirmatory"]
    # Baseline fp rate 0/1 = 0.0; chained fp rate 1/2 = 0.5; delta 0.5 > margin.
    assert jc["false_positive_not_raised"] is False
    assert jc["passes"] is False


# ---------------------------------------------------------------------------
# analyse() top level
# ---------------------------------------------------------------------------

def test_analyse_one_arm_empty_emits_note():
    report = analyse({"baseline": [_o()], "chained": []})
    assert "note" in report["paired"]
    assert "Malta dispatch" in report["paired"]["note"]


def test_analyse_both_arms_runs_paired():
    baseline, chained = _paired_fixture()
    report = analyse({"baseline": baseline, "chained": chained})
    assert "joint_confirmatory" in report["paired"]
    assert report["arms"]["chained"]["n"] == 3


# ---------------------------------------------------------------------------
# DB layer: load_outcomes against a minimal SQLite database
# ---------------------------------------------------------------------------

def _build_minimal_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE phase2_final (
            pair_run_id TEXT, question_id TEXT, country_code TEXT,
            terminal_status TEXT, final_answer TEXT, experiment_id TEXT
        );
        CREATE TABLE phase2_researcher_runs (
            pair_run_id TEXT, condition_label TEXT
        );
        CREATE TABLE ground_truth (
            question_id TEXT, country_code TEXT, response TEXT
        );
        CREATE TABLE claude_usage_log (subtrio_id TEXT);
        CREATE TABLE questions (
            question_id TEXT, answer_shape TEXT, allowed_answers TEXT
        );
        """
    )
    # Two pairs, one per arm, same question/country.
    conn.executemany(
        "INSERT INTO phase2_final VALUES (?,?,?,?,?,?)",
        [
            ("b1", "Q1", "MT", "accepted_by_verifier", "yes", "exp7"),
            ("c1", "Q1", "MT", "accepted_by_verifier", "no", "exp7"),
            # A pair from another experiment must be ignored.
            ("x1", "Q1", "MT", "accepted_by_verifier", "yes", "other_exp"),
        ],
    )
    conn.executemany(
        "INSERT INTO phase2_researcher_runs VALUES (?,?)",
        [("b1", "baseline"), ("c1", "chained"), ("x1", "baseline")],
    )
    conn.execute(
        "INSERT INTO ground_truth VALUES (?,?,?)", ("Q1", "MT", "yes")
    )
    # b1 spent 3 calls, c1 spent 5.
    conn.executemany(
        "INSERT INTO claude_usage_log VALUES (?)",
        [("b1",)] * 3 + [("c1",)] * 5,
    )
    conn.commit()
    conn.close()


def test_load_outcomes_splits_arms_and_counts(tmp_path):
    db = tmp_path / "mini.db"
    _build_minimal_db(db)
    conn = sqlite3.connect(db)
    try:
        arms = load_outcomes(conn, "exp7")
    finally:
        conn.close()

    assert set(arms) == {"baseline", "chained"}
    b = arms["baseline"][0]
    c = arms["chained"][0]
    # Baseline answered yes against a yes gold -> match; chained answered no -> differ.
    assert b.match_status == "match"
    assert recovered(b) is True
    assert c.match_status == "differ"
    assert is_false_positive(c) is True
    # Call counts pulled from claude_usage_log.
    assert b.calls == 3
    assert c.calls == 5
    # The other_exp row was excluded by the experiment_id filter.
    assert len(arms["baseline"]) == 1
