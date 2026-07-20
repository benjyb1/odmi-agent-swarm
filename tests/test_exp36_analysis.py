"""Unit tests for the EXP-36 analysis pack (evaluation/exp36_analysis.py)."""

from __future__ import annotations

import math

import pytest

from evaluation.exp36_analysis import (
    PairRow,
    calibration,
    dedup_canonical,
    floor_sweep,
)
from evaluation.stats import two_proportion_test, wilson_interval


def _row(
    row_id: int,
    qid: str = "P1",
    cc: str = "BA",
    label: str = "BA",
    status: str = "accepted_by_verifier",
    answer: str = "yes",
    conf: float | None = 0.8,
    gold: str = "yes",
    match: str = "match",
) -> PairRow:
    return PairRow(
        row_id=row_id,
        question_id=qid,
        country_code=cc,
        condition_label=label,
        terminal_status=status,
        final_answer=answer,
        final_confidence=conf,
        gold_answer=gold,
        gold_decision="confirm",
        dimension="Policy",
        answer_shape="binary",
        match_status=match,
    )


class TestDedupCanonical:
    def test_latest_row_wins_and_duplicates_counted(self):
        rows = [
            _row(1, match="differ"),
            _row(7, match="match"),
            _row(3, qid="P2"),
        ]
        kept, superseded = dedup_canonical(rows)
        assert superseded == 1
        by_q = {r.question_id: r for r in kept}
        assert by_q["P1"].row_id == 7
        assert by_q["P1"].match_status == "match"

    def test_condition_label_scopes_the_key(self):
        rows = [_row(1, label="a"), _row(2, label="b")]
        kept, superseded = dedup_canonical(rows)
        assert superseded == 0
        assert len(kept) == 2

    def test_single_arm_collapses_labels_and_keeps_latest(self):
        # EXP-36 shape: an infra re-run wrote a second final for the same
        # pair whose researcher row carried no condition_label. Without
        # scope_by_label the pair must collapse to one row, the later one.
        rows = [
            _row(1, label="unlabelled", match="differ"),
            _row(9, label="BA", match="match"),
        ]
        kept, superseded = dedup_canonical(rows, scope_by_label=False)
        assert superseded == 1
        assert len(kept) == 1
        assert kept[0].row_id == 9
        assert kept[0].match_status == "match"

    def test_single_arm_keeps_distinct_pairs_apart(self):
        rows = [
            _row(1, qid="P1", cc="BA"),
            _row(2, qid="P1", cc="BE"),
            _row(3, qid="P2", cc="BA"),
        ]
        kept, superseded = dedup_canonical(rows, scope_by_label=False)
        assert superseded == 0
        assert len(kept) == 3


class TestCalibration:
    def test_ece_is_weighted_gap(self):
        # Two bins with known gaps: four pairs at 0.95 all matching
        # (gap 0.05), one pair at 0.55 not matching (gap 0.55).
        rows = [_row(i, qid=f"P{i}", conf=0.95, match="match") for i in range(4)]
        rows.append(_row(9, qid="P9", conf=0.55, match="differ"))
        out = calibration(rows)
        expected = (4 * 0.05 + 1 * 0.55) / 5
        assert out["ece"] == pytest.approx(expected, abs=1e-9)

    def test_top_bin_includes_exact_one(self):
        rows = [_row(1, conf=1.0, match="match")]
        out = calibration(rows)
        top = out["bins"][-1]
        assert top["n"] == 1

    def test_missing_confidence_excluded_and_counted(self):
        rows = [_row(1, conf=None), _row(2, qid="P2", conf=0.7)]
        out = calibration(rows)
        assert out["n_committed_excluded"]["missing_confidence"] == 1
        assert out["n_scored"] == 1


class TestFloorSweep:
    def test_coverage_never_rises_with_the_floor(self):
        rows = [
            _row(i, qid=f"P{i}", conf=c, match=m)
            for i, (c, m) in enumerate(
                [(0.66, "match"), (0.7, "differ"), (0.9, "match"), (0.95, "match")]
            )
        ]
        out = floor_sweep(rows)
        coverages = [pt["coverage"] for pt in out["floors"]]
        assert coverages == sorted(coverages, reverse=True)

    def test_unconfident_commit_never_passes(self):
        rows = [_row(1, conf=None, match="match")]
        out = floor_sweep(rows)
        assert all(pt["n_committed"] == 0 for pt in out["floors"])
        assert out["n_committed_missing_confidence"] == 1


class TestTwoProportion:
    def test_matches_wilson_edges_and_direction(self):
        res = two_proportion_test(8, 10, 2, 10)
        assert res["delta"] == pytest.approx(0.6)
        lo, hi = res["ci_95"]
        assert lo < 0.6 < hi
        assert res["p_value"] < 0.05

    def test_degenerate_pool_is_p_one(self):
        res = two_proportion_test(5, 5, 5, 5)
        assert res["p_value"] == 1.0

    def test_empty_group_is_null_delta(self):
        res = two_proportion_test(0, 0, 3, 10)
        assert res["delta"] is None
        assert res["p_value"] == 1.0


def test_wilson_interval_basic_properties():
    lo, hi = wilson_interval(9, 10)
    assert 0.0 <= lo < 0.9 < hi <= 1.0
    lo0, hi0 = wilson_interval(0, 10)
    assert lo0 == pytest.approx(0.0, abs=1e-12)
    assert hi0 < 0.35
