"""Pure-logic tests for the DIY-vs-Tavily adjudicated evaluation harness.

No network, no DB, no LLM. Covers the parts where a bug would silently
corrupt the headline number: mapping a blind verdict back to the DIY frame,
combining the two position-swapped runs (and detecting position bias), the
dimension stratifier, and the aggregate rates.
"""
from __future__ import annotations

from evaluation.diy_vs_tavily import (
    orientation_to_diy, combine_orientations, aggregate, stratify_pairs,
    dimension_of, decided_stats, select_subsample, filter_pairs,
)


# orientation_to_diy: blind A/B verdict -> DIY frame

def test_orientation_winner_a_when_diy_is_a():
    assert orientation_to_diy("A", diy_is="A") == "diy"


def test_orientation_winner_a_when_diy_is_b():
    assert orientation_to_diy("A", diy_is="B") == "tavily"


def test_orientation_tie_and_both_fail_passthrough():
    assert orientation_to_diy("tie", diy_is="A") == "tie"
    assert orientation_to_diy("both_fail", diy_is="B") == "both_fail"


# combine_orientations: two swapped runs -> one verdict

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


# aggregate: verdicts -> rates

def test_aggregate_counts_and_rates():
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
    assert agg["diy_win_rate"] == 0.5
    assert agg["consistency_rate"] == 0.75
    # The discredited (diy+tie)/decisive metric is gone from the harness.
    assert "diy_not_worse_decisive" not in agg
    assert "diy_not_worse_rate" not in agg


def test_aggregate_empty_is_safe():
    agg = aggregate([])
    assert agg["n"] == 0
    assert agg["decisive"] == 0
    assert agg["diy_win_rate"] == 0.0


def test_aggregate_decisive_excludes_both_fail():
    """both_fail pairs (question unanswerable from the web) must not count
    in the head-to-head; decisive uses (n - both_fail)."""
    verdicts = [
        {"verdict": "diy", "consistent": True},
        {"verdict": "both_fail", "consistent": True},
        {"verdict": "tavily", "consistent": True},
    ]
    agg = aggregate(verdicts)
    assert agg["both_fail"] == 1
    assert agg["decisive"] == 2


# decided_stats: real win share + Wilson CI + sign test

def test_decided_stats_known_inputs():
    """12 DIY wins, 4 Tavily wins, ties excluded from the strict denominator.

    decided = 16, share = 0.75; the sign test is the exact two-sided binomial
    of 4 vs 12 against 0.5.
    """
    from evaluation.stats import sign_test, wilson_interval

    out = decided_stats(diy_wins=12, tavily_wins=4)
    assert out["decided_strict"] == 16
    assert out["diy_win_share"] == 0.75
    assert out["sign_test_p"] == sign_test(12, 4)
    lo, hi = wilson_interval(12, 16)
    assert out["wilson_low"] == lo
    assert out["wilson_high"] == hi
    # Ties never enter the strict denominator.
    out_with_ties = decided_stats(diy_wins=12, tavily_wins=4)
    assert out_with_ties["decided_strict"] == 16


def test_decided_stats_zero_decided_is_safe():
    out = decided_stats(diy_wins=0, tavily_wins=0)
    assert out["decided_strict"] == 0
    assert out["diy_win_share"] == 0.0
    assert out["sign_test_p"] == 1.0
    # Wilson on n=0 is the whole unit interval.
    assert out["wilson_low"] == 0.0
    assert out["wilson_high"] == 1.0


# select_subsample: deterministic seeded 30% draw

def test_select_subsample_deterministic_for_fixed_seed():
    records = [{"question_id": f"P{i}", "country_code": "FR"} for i in range(20)]
    a = select_subsample(records, seed=20260602, frac=0.30)
    b = select_subsample(records, seed=20260602, frac=0.30)
    assert a == b  # same seed -> identical draw
    # 30% of 20 = 6
    assert len(a) == 6
    # every selected record is one of the originals (no fabrication)
    assert all(r in records for r in a)


def test_select_subsample_seed_changes_draw():
    records = [{"question_id": f"P{i}", "country_code": "FR"} for i in range(20)]
    a = select_subsample(records, seed=20260602, frac=0.30)
    c = select_subsample(records, seed=1, frac=0.30)
    assert a != c  # a different seed gives a different (here, non-identical) draw


def test_select_subsample_at_least_one_when_nonempty():
    records = [{"question_id": "P1", "country_code": "FR"}]
    out = select_subsample(records, seed=20260602, frac=0.30)
    # round(0.3) == 0, but a non-empty input must yield at least one pair.
    assert len(out) == 1


# filter_pairs: country + exclude-dimensions

def test_filter_pairs_excludes_quality_dimension():
    pairs = [
        {"question_id": "Q1", "country_code": "FR", "dimension": "Quality"},
        {"question_id": "P1", "country_code": "FR", "dimension": "Policy"},
        {"question_id": "I1", "country_code": "FR", "dimension": "Impact"},
    ]
    out = filter_pairs(pairs, countries=None, exclude_dimensions=["Quality"])
    dims = {p["dimension"] for p in out}
    assert "Quality" not in dims
    assert len(out) == 2


def test_filter_pairs_by_country():
    pairs = [
        {"question_id": "P1", "country_code": "FR", "dimension": "Policy"},
        {"question_id": "P1", "country_code": "DE", "dimension": "Policy"},
        {"question_id": "P2", "country_code": "EE", "dimension": "Policy"},
    ]
    out = filter_pairs(pairs, countries=["FR"], exclude_dimensions=[])
    assert {p["country_code"] for p in out} == {"FR"}


def test_filter_pairs_country_filter_is_case_insensitive():
    pairs = [{"question_id": "P1", "country_code": "FR", "dimension": "Policy"}]
    out = filter_pairs(pairs, countries=["fr"], exclude_dimensions=[])
    assert len(out) == 1


def test_filter_pairs_none_country_keeps_all_countries():
    pairs = [
        {"question_id": "P1", "country_code": "FR", "dimension": "Policy"},
        {"question_id": "P2", "country_code": "DE", "dimension": "Portal"},
    ]
    out = filter_pairs(pairs, countries=None, exclude_dimensions=["Quality"])
    assert len(out) == 2


# dimension_of / stratify_pairs

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
