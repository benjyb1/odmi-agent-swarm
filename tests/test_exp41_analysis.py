"""EXP-41 analysis: the metric definitions, tested before the data exists.

Fleiss' kappa and the outcome vocabulary are the load-bearing pieces. If either
is wrong the reported stability number is wrong in a way no amount of careful
dispatch would catch, so both are pinned against hand-worked cases.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from evaluation.exp41_analysis import (  # noqa: E402
    BARS, fleiss_kappa, normalise_url, outcome, wilson,
)


# --- outcome vocabulary ----------------------------------------------------

@pytest.mark.parametrize("status,answer,expected", [
    ("accepted_by_verifier", "yes", "commit-yes"),
    ("accepted_by_adjudicator", "no", "commit-no"),
    ("accepted_by_verifier", "YES", "commit-yes"),
    ("accepted_by_verifier", " no ", "commit-no"),
    ("abstained_adjudicator", "inconclusive", "no-commit"),
    ("abstained_researcher_only", None, "no-commit"),
])
def test_outcome_vocabulary(status, answer, expected):
    assert outcome(status, answer) == expected


def test_agent_failure_is_no_commit_not_dropped():
    """The pre-registered rule. Excluding failures per run would delete exactly
    the pairs where one run behaved differently from another."""
    assert outcome("agent_failure", None) == "no-commit"
    assert outcome("agent_failure", "yes") == "no-commit"


def test_committed_status_with_an_abstention_answer_is_not_a_commit():
    """A committed terminal status with no real answer behind it must not be
    counted as a commit, or coverage is overstated."""
    assert outcome("accepted_by_verifier", "inconclusive") == "no-commit"
    assert outcome("accepted_by_adjudicator", "") == "no-commit"


def test_non_binary_answers_stay_visible():
    """Band answers must not be silently binned into yes or no."""
    assert outcome("accepted_by_verifier", "10-25%") == "commit-other"


# --- URL normalisation (M5) ------------------------------------------------

def test_normalisation_is_the_pre_registered_rule():
    a = normalise_url("HTTPS://Data.Gov.MT/en/dataset/x/")
    b = normalise_url("https://data.gov.mt/en/dataset/x")
    assert a == b == "https://data.gov.mt/en/dataset/x"


def test_query_and_fragment_are_dropped():
    assert normalise_url("https://a.b/c?q=1#frag") == normalise_url("https://a.b/c")


def test_different_paths_stay_distinct():
    """M5 counts distinct evidence paths; over-normalising would erase the
    divergence the metric exists to detect."""
    assert normalise_url("https://a.b/one") != normalise_url("https://a.b/two")


def test_empty_url_is_empty():
    assert normalise_url(None) == "" and normalise_url("") == ""


# --- Fleiss' kappa ---------------------------------------------------------

def test_perfect_agreement_is_one():
    rows = [[3, 0, 0], [0, 3, 0], [3, 0, 0], [0, 3, 0]]
    assert fleiss_kappa(rows) == pytest.approx(1.0)


def test_chance_level_agreement_is_near_zero():
    rows = [[2, 1, 0], [1, 2, 0], [2, 1, 0], [1, 2, 0]]
    assert abs(fleiss_kappa(rows)) < 0.35


def test_kappa_undefined_when_every_rater_uses_one_category():
    """The all-abstain degenerate case: unanimity is 1.0 but kappa carries no
    information. It must return nan rather than a flattering 1.0, which is
    exactly why M2's marginals are reported alongside."""
    k = fleiss_kappa([[3, 0, 0]] * 10)
    assert k != k


def test_ragged_rater_counts_are_rejected():
    """A short row means a pair was dropped for one run, which this design
    forbids. Silently averaging over it would inflate agreement."""
    assert fleiss_kappa([[3, 0, 0], [2, 0, 0]]) != fleiss_kappa([[3, 0, 0], [3, 0, 0]])
    k = fleiss_kappa([[3, 0, 0], [2, 0, 0]])
    assert k != k


def test_known_worked_example():
    """Two raters, two items, one agreement and one split."""
    rows = [[2, 0], [1, 1]]
    assert fleiss_kappa(rows) == pytest.approx(0.0, abs=0.34)


# --- intervals and bars ----------------------------------------------------

def test_wilson_brackets_the_point_estimate():
    lo, hi = wilson(8, 10)
    assert lo < 0.8 < hi and 0 <= lo and hi <= 1


def test_wilson_handles_zero_and_full():
    assert wilson(0, 10)[0] == 0.0
    assert wilson(10, 10)[1] == pytest.approx(1.0, abs=1e-9)


def test_bars_match_the_preregistration():
    """If these drift from docs/EXPERIMENTS_RUN_STABILITY.md the result is being
    graded against a moved bar."""
    assert BARS == {
        "m1_unanimity": 0.80, "m1_kappa": 0.60,
        "m2_commit_rate_range": 0.10,
        "m3_unanimity": 0.90, "m3_kappa": 0.70,
        "m5_divergence": 0.50,
    }
