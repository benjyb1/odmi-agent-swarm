"""Unit tests for the maturity reconstruction
(evaluation/exp36_maturity_reconstruction.py).

The pure layer only, so the arithmetic is checkable without a database.
"""

from __future__ import annotations

import pytest

from evaluation.exp36_maturity_reconstruction import (
    GoldCell,
    build_rubric,
    dimension_mean,
    score_country,
)


def _cell(qid: str, dim: str, response: str, awarded: float,
          maximum: float = 100.0) -> GoldCell:
    return GoldCell(
        question_id=qid,
        dimension=dim,
        response=response,
        awarded_score=awarded,
        max_score=maximum,
    )


# the rubric

def test_rubric_maps_answer_to_awarded_fraction() -> None:
    rubric = build_rubric([
        _cell("P1", "policy_dimension", "yes", 100.0),
        _cell("P1", "policy_dimension", "no", 0.0),
        _cell("Q7", "quality_dimension", ">90%", 80.0),
    ])
    assert rubric[("P1", "yes")] == 1.0
    assert rubric[("P1", "no")] == 0.0
    assert rubric[("Q7", ">90%")] == 0.8


def test_rubric_normalises_case_and_whitespace() -> None:
    rubric = build_rubric([_cell("P1", "policy_dimension", "  YES ", 100.0)])
    assert rubric[("P1", "yes")] == 1.0


def test_rubric_rejects_a_question_marked_two_ways() -> None:
    """If ODMI awarded different marks for the same answer to the same
    question, the lookup would be guessing, so the build must fail loudly."""
    with pytest.raises(ValueError, match="not deterministic"):
        build_rubric([
            _cell("P1", "policy_dimension", "yes", 100.0),
            _cell("P1", "policy_dimension", "yes", 40.0),
        ])


def test_rubric_skips_unmarked_questions() -> None:
    """The 13 questions per country that carry no marks cannot contribute."""
    rubric = build_rubric([_cell("P1", "policy_dimension", "yes", 0.0, 0.0)])
    assert rubric == {}


# the score

def test_dimension_mean_averages_dimensions_not_questions() -> None:
    """The published formula weights each dimension equally however many
    questions or marks it holds. A flat SUM/SUM would give 20.0 here."""
    assert dimension_mean({"a": (100.0, 100.0), "b": (0.0, 400.0)}) == 50.0


def test_dimension_mean_drops_an_empty_dimension_rather_than_scoring_it_zero() -> None:
    assert dimension_mean({"a": (50.0, 100.0), "b": (0.0, 0.0)}) == 50.0


def _two_dimension_gold() -> list[GoldCell]:
    return [
        _cell("P1", "policy_dimension", "yes", 100.0),
        _cell("P2", "policy_dimension", "no", 0.0),
        _cell("Q1", "quality_dimension", "yes", 100.0),
        _cell("Q2", "quality_dimension", "yes", 100.0),
    ]


_RUBRIC = {
    ("P1", "yes"): 1.0, ("P1", "no"): 0.0,
    ("P2", "yes"): 1.0, ("P2", "no"): 0.0,
    ("Q1", "yes"): 1.0, ("Q1", "no"): 0.0,
    ("Q2", "yes"): 1.0, ("Q2", "no"): 0.0,
}


def test_a_swarm_that_answers_everything_correctly_reproduces_the_published_score() -> None:
    gold = _two_dimension_gold()
    answers = {"P1": "yes", "P2": "no", "Q1": "yes", "Q2": "yes"}
    scored = score_country("XX", gold, answers, _RUBRIC)

    assert scored.published == pytest.approx(75.0)
    assert scored.floor == pytest.approx(75.0)
    assert scored.ceiling == pytest.approx(75.0)
    assert scored.coverage == 1.0


def test_abstentions_open_the_band_between_floor_and_ceiling() -> None:
    """Floor keeps an abstention in the denominator; ceiling drops it. With
    policy half-abstained, the floor halves that dimension and the ceiling
    scores it on the one committed answer alone."""
    gold = _two_dimension_gold()
    answers = {"P1": "yes", "Q1": "yes", "Q2": "yes"}  # P2 abstained
    scored = score_country("XX", gold, answers, _RUBRIC)

    # floor: policy 100/200, quality 200/200 -> mean(50, 100)
    assert scored.floor == pytest.approx(75.0)
    # ceiling: policy 100/100, quality 200/200 -> mean(100, 100)
    assert scored.ceiling == pytest.approx(100.0)
    assert scored.n_abstained == 1
    assert scored.coverage == pytest.approx(0.75)


def test_an_answer_odmi_has_no_marks_for_scores_zero_and_is_counted() -> None:
    gold = _two_dimension_gold()
    answers = {"P1": "somewhat", "P2": "no", "Q1": "yes", "Q2": "yes"}
    scored = score_country("XX", gold, answers, _RUBRIC)

    assert scored.n_off_rubric == 1
    assert scored.n_committed == 4
    # The off-rubric answer stays in the denominator, so policy scores 0/200.
    assert scored.floor == pytest.approx(50.0)
    assert scored.ceiling == pytest.approx(50.0)


def test_unmarked_questions_are_excluded_from_every_denominator() -> None:
    gold = _two_dimension_gold() + [
        _cell("P3", "policy_dimension", "not applicable", 0.0, 0.0),
    ]
    answers = {"P1": "yes", "P2": "no", "Q1": "yes", "Q2": "yes"}
    scored = score_country("XX", gold, answers, _RUBRIC)

    assert scored.n_questions == 4
    assert scored.published == pytest.approx(75.0)


def test_width_is_the_gap_the_abstentions_leave_open() -> None:
    gold = _two_dimension_gold()
    answers = {"P1": "yes", "Q1": "yes", "Q2": "yes"}
    scored = score_country("XX", gold, answers, _RUBRIC)
    assert scored.width == pytest.approx(scored.ceiling - scored.floor)


def test_a_country_whose_golds_are_all_no_loses_little_by_abstaining() -> None:
    """Why Bosnia has the narrowest band despite the lowest coverage: an
    abstention on a question worth nothing costs nothing."""
    gold = [
        _cell("P1", "policy_dimension", "no", 0.0),
        _cell("P2", "policy_dimension", "no", 0.0),
    ]
    rubric = {("P1", "no"): 0.0, ("P2", "no"): 0.0,
              ("P1", "yes"): 1.0, ("P2", "yes"): 1.0}
    scored = score_country("XX", gold, {"P1": "no"}, rubric)  # P2 abstained

    assert scored.published == pytest.approx(0.0)
    assert scored.floor == pytest.approx(0.0)
    assert scored.ceiling == pytest.approx(0.0)
    assert scored.width == pytest.approx(0.0)
