"""Pure-logic tests for the DIY-vs-Tavily adjudicated evaluation harness.

No network, no DB, no LLM. Covers the parts where a bug would silently
corrupt the headline number: mapping a blind verdict back to the DIY frame,
combining the two position-swapped runs (and detecting position bias), the
dimension stratifier, and the aggregate rates.
"""
from __future__ import annotations

from evaluation.diy_vs_tavily import (
    orientation_to_diy, combine_orientations, aggregate, stratify_pairs,
    dimension_of,
)


# --- orientation_to_diy: blind A/B verdict -> DIY frame ---------------------

def test_orientation_winner_a_when_diy_is_a():
    assert orientation_to_diy("A", diy_is="A") == "diy"


def test_orientation_winner_a_when_diy_is_b():
    assert orientation_to_diy("A", diy_is="B") == "tavily"


def test_orientation_tie_and_both_fail_passthrough():
    assert orientation_to_diy("tie", diy_is="A") == "tie"
    assert orientation_to_diy("both_fail", diy_is="B") == "both_fail"


# --- combine_orientations: two swapped runs -> one verdict ------------------

def test_combine_agreement_diy_wins_both_orientations():
    out = combine_orientations("diy", "diy")
    assert out["verdict"] == "diy"
    assert out["consistent"] is True


def test_combine_position_flip_is_tie_and_inconsistent():
    # Judge picked whoever was in slot A both times -> pure position bias.
    out = combine_orientations("diy", "tavily")
    assert out["verdict"] == "tie"
    assert out["consistent"] is False


def test_combine_diy_and_tie_leans_diy():
    out = combine_orientations("diy", "tie")
    assert out["verdict"] == "diy"
    assert out["consistent"] is False


def test_combine_both_fail_when_both_orientations_fail():
    out = combine_orientations("both_fail", "both_fail")
    assert out["verdict"] == "both_fail"
    assert out["consistent"] is True


# --- aggregate: verdicts -> rates ------------------------------------------

def test_aggregate_counts_and_not_worse_rate():
    verdicts = [
        {"verdict": "diy", "consistent": True},
        {"verdict": "diy", "consistent": True},
        {"verdict": "tie", "consistent": True},
        {"verdict": "tavily", "consistent": False},
    ]
    agg = aggregate(verdicts)
    assert agg["n"] == 4
    assert agg["diy"] == 2
    assert agg["tie"] == 1
    assert agg["tavily"] == 1
    # "not worse than Tavily" = (diy wins + ties) / total
    assert agg["diy_not_worse_rate"] == 0.75
    assert agg["diy_win_rate"] == 0.5
    assert agg["consistency_rate"] == 0.75


def test_aggregate_empty_is_safe():
    agg = aggregate([])
    assert agg["n"] == 0
    assert agg["diy_not_worse_rate"] == 0.0
    assert agg["diy_not_worse_decisive"] == 0.0


def test_aggregate_decisive_excludes_both_fail():
    """both_fail pairs (question unanswerable from the web) must not count
    in the head-to-head; the decisive rate uses (n - both_fail)."""
    verdicts = [
        {"verdict": "diy", "consistent": True},
        {"verdict": "both_fail", "consistent": True},
        {"verdict": "tavily", "consistent": True},
    ]
    agg = aggregate(verdicts)
    assert agg["both_fail"] == 1
    assert agg["decisive"] == 2
    # among decisive {diy, tavily}: DIY not worse = 1/2
    assert agg["diy_not_worse_decisive"] == 0.5
    # overall still divides by all 3
    assert round(agg["diy_not_worse_rate"], 3) == round(1 / 3, 3)


# --- dimension_of / stratify_pairs -----------------------------------------

def test_dimension_of_handles_all_prefixes():
    assert dimension_of("I1") == "I"
    assert dimension_of("P10-b") == "P"
    assert dimension_of("PT4") == "PT"
    assert dimension_of("Q6") == "Q"


def test_stratify_round_robins_across_dimensions():
    pairs = (
        [{"question_id": f"P{i}", "country_code": "FR"} for i in range(5)]
        + [{"question_id": f"Q{i}", "country_code": "FR"} for i in range(5)]
        + [{"question_id": f"I{i}", "country_code": "FR"} for i in range(5)]
        + [{"question_id": f"PT{i}", "country_code": "FR"} for i in range(5)]
    )
    out = stratify_pairs(pairs, limit=8)
    assert len(out) == 8
    # 8 across 4 dimensions, round-robin => 2 from each
    dims = [dimension_of(p["question_id"]) for p in out]
    assert dims.count("P") == 2 and dims.count("Q") == 2
    assert dims.count("I") == 2 and dims.count("PT") == 2


def test_stratify_dedupes_by_question_country():
    pairs = [
        {"question_id": "P1", "country_code": "FR"},
        {"question_id": "P1", "country_code": "FR"},  # dup
        {"question_id": "P1", "country_code": "DE"},  # distinct country
    ]
    out = stratify_pairs(pairs, limit=10)
    keys = {(p["question_id"], p["country_code"]) for p in out}
    assert len(out) == len(keys) == 2
