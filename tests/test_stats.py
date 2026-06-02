"""Tests for the experiment-analysis statistics module (``evaluation.stats``).

Every function is pure: no I/O, no global state. The assertions below pin each
estimator to a known textbook value so an examiner can confirm correctness by
hand. Where a target is checked against an external reference it is named in a
comment.

scipy is an optional dependency. The Wilcoxon test branches on whether scipy
imports, so the test for that function adapts to the environment.
"""
from __future__ import annotations

import importlib.util

import pytest

from evaluation import stats

# Is scipy importable in this environment? The Wilcoxon wrapper depends on it.
_HAS_SCIPY = importlib.util.find_spec("scipy") is not None


# ---------------------------------------------------------------------------
# wilson_interval
# ---------------------------------------------------------------------------

def test_wilson_known_8_of_10() -> None:
    # Reference: Newcombe (1998) / Wallis (2013) Wilson score interval for
    # 8/10 successes at 95% confidence is (0.4902, 0.9433). Note the upper
    # bound is 0.9433, not the naive 15/16 = 0.9375.
    lo, hi = stats.wilson_interval(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3)
    assert hi == pytest.approx(0.9433, abs=1e-3)


def test_wilson_zero_successes_lower_is_zero() -> None:
    lo, _hi = stats.wilson_interval(0, 10)
    assert lo == 0.0


def test_wilson_centre_symmetric_at_half() -> None:
    # 5/10 is symmetric, so the interval centre sits on 0.5.
    lo, hi = stats.wilson_interval(5, 10)
    assert (lo + hi) / 2 == pytest.approx(0.5, abs=1e-9)


def test_wilson_n_zero_returns_full_unit_interval() -> None:
    assert stats.wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_bounds_stay_within_unit_interval() -> None:
    for s in range(0, 11):
        lo, hi = stats.wilson_interval(s, 10)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_confidence_widens_interval() -> None:
    lo95, hi95 = stats.wilson_interval(8, 10, confidence=0.95)
    lo99, hi99 = stats.wilson_interval(8, 10, confidence=0.99)
    assert (hi99 - lo99) > (hi95 - lo95)


# ---------------------------------------------------------------------------
# sign_test
# ---------------------------------------------------------------------------

def test_sign_test_all_wins_is_significant() -> None:
    assert stats.sign_test(10, 0) < 0.01


def test_sign_test_balanced_is_one() -> None:
    assert stats.sign_test(5, 5) == 1.0


def test_sign_test_eight_two_known_value() -> None:
    # Two-sided exact binomial, n=10, p=0.5: 2 * P(X <= 2) = 0.109375.
    assert stats.sign_test(8, 2) == pytest.approx(0.1094, abs=1e-3)


def test_sign_test_symmetric_in_arguments() -> None:
    assert stats.sign_test(8, 2) == stats.sign_test(2, 8)


def test_sign_test_no_decided_trials_is_one() -> None:
    assert stats.sign_test(0, 0) == 1.0


# ---------------------------------------------------------------------------
# mcnemar_exact
# ---------------------------------------------------------------------------

def test_mcnemar_all_one_direction_is_significant() -> None:
    assert stats.mcnemar_exact(0, 10) < 0.01


def test_mcnemar_balanced_is_one() -> None:
    assert stats.mcnemar_exact(5, 5) == 1.0


def test_mcnemar_matches_sign_test_on_discordants() -> None:
    # McNemar's exact test is the sign test over the b + c discordant pairs.
    assert stats.mcnemar_exact(8, 2) == pytest.approx(stats.sign_test(8, 2), abs=1e-12)


def test_mcnemar_no_discordants_is_one() -> None:
    assert stats.mcnemar_exact(0, 0) == 1.0


# ---------------------------------------------------------------------------
# wilcoxon_signed_rank
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_HAS_SCIPY, reason="scipy present: NotImplementedError path not taken")
def test_wilcoxon_raises_without_scipy() -> None:
    with pytest.raises(NotImplementedError):
        stats.wilcoxon_signed_rank([1.0, -2.0, 3.0, -0.5])


@pytest.mark.skipif(not _HAS_SCIPY, reason="scipy not installed")
def test_wilcoxon_sanity_with_scipy() -> None:
    # A clear positive shift should yield a small p-value; the statistic is
    # non-negative. Zero differences are dropped before the test runs.
    stat, p = stats.wilcoxon_signed_rank([3.0, 4.0, 2.5, 5.0, 0.0, 3.5, 4.5, 2.0])
    assert stat >= 0.0
    assert 0.0 <= p <= 1.0
    assert p < 0.05


# ---------------------------------------------------------------------------
# krippendorff_alpha
# ---------------------------------------------------------------------------

def test_krippendorff_perfect_agreement_is_one() -> None:
    units = [[1, 1], [2, 2], [3, 3], [1, 1], [2, 2]]
    assert stats.krippendorff_alpha(units) == pytest.approx(1.0, abs=1e-12)


def test_krippendorff_canonical_nominal_example() -> None:
    # Canonical nominal worked example from the Krippendorff's-alpha literature
    # (the 3-observer, 15-unit reliability matrix reproduced on Wikipedia).
    # 12 multiply-coded units, 26 pairable values, alpha_nominal = 0.691.
    # The general coincidence-matrix formula handles a variable number of
    # coders per item, so units may be longer than two entries.
    n = None
    a = [n, n, n, n, n, 3, 4, 1, 2, 1, 1, 3, 3, n, 3]
    b = [1, n, 2, 1, 3, 3, 4, 3, n, n, n, n, n, n, n]
    c = [n, n, 2, 1, 3, 4, 4, n, 2, 1, 1, 3, 3, n, 4]
    units = [[a[i], b[i], c[i]] for i in range(15)]
    assert stats.krippendorff_alpha(units) == pytest.approx(0.691, abs=1e-2)


def test_krippendorff_chance_labels_near_zero() -> None:
    # Systematic swapping between coders carries no agreement beyond chance,
    # so alpha sits at or below zero (here it is negative, not near +1).
    units = [[1, 2], [2, 1], [1, 2], [2, 1], [3, 4], [4, 3], [3, 4], [4, 3]]
    assert stats.krippendorff_alpha(units) < 0.05


def test_krippendorff_ignores_units_with_one_label() -> None:
    # A unit coded by only one observer carries no pair, so it must not change
    # the result relative to dropping it.
    base = [[1, 1], [2, 2], [3, 3]]
    with_singleton = base + [[4, None]]
    assert stats.krippendorff_alpha(with_singleton) == pytest.approx(
        stats.krippendorff_alpha(base), abs=1e-12
    )


def test_krippendorff_two_disagreements_known_value() -> None:
    # A small hand-checkable case: 5 units, 2 coders, 1 disagreement.
    #   coincidences: labels {1,2,3}; n1=3, n2=4, n3=3 (n_total=10).
    #   one unit disagrees 1 vs 2, so o_12 = o_21 = 1, all else on-diagonal.
    #   Do = 2; De = (n1 n2 + n2 n1 + ... summed off-diagonal)/(n_total-1).
    units = [[1, 1], [2, 2], [3, 3], [1, 2], [3, 3]]
    labels = [1, 2, 3]
    n_counts = {1: 3.0, 2: 4.0, 3: 3.0}
    n_total = 10.0
    do = 2.0
    de = sum(
        n_counts[i] * n_counts[j] for i in labels for j in labels if i != j
    ) / (n_total - 1)
    expected = 1 - do / de
    assert stats.krippendorff_alpha(units) == pytest.approx(expected, abs=1e-9)


def test_krippendorff_all_missing_is_one() -> None:
    # No pairable values at all: degenerate, defined here as perfect (1.0).
    units = [[None, None], [None, None]]
    assert stats.krippendorff_alpha(units) == 1.0
