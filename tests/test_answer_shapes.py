"""Unit tests for the D28 answer-shapes helper module."""

from __future__ import annotations

from agents.tools.answer_shapes import (
    INCONCLUSIVE,
    NOT_APPLICABLE,
    QuestionShape,
    band_distance,
    is_band_shape,
    is_inconclusive,
    is_valid_answer,
    normalise_answer,
)


def _binary() -> QuestionShape:
    return QuestionShape(
        question_id="Px",
        shape="binary",
        allowed_answers=("yes", "no"),
    )


def _band() -> QuestionShape:
    return QuestionShape(
        question_id="Q12",
        shape="percentage_band",
        allowed_answers=(">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"),
    )


def test_binary_allows_listed_answers():
    s = _binary()
    assert is_valid_answer("yes", s)
    assert is_valid_answer("no", s)


def test_inconclusive_always_valid():
    assert is_valid_answer(INCONCLUSIVE, _binary())
    assert is_valid_answer(INCONCLUSIVE, _band())


def test_not_applicable_always_valid():
    assert is_valid_answer(NOT_APPLICABLE, _binary())
    assert is_valid_answer(NOT_APPLICABLE, _band())


def test_off_script_answer_rejected():
    s = _band()
    assert not is_valid_answer("around 80%", s)
    assert not is_valid_answer("yes", s)


def test_normalise_case_insensitive():
    s = _band()
    assert normalise_answer("71-90%", s) == "71-90%"
    # Different case still normalises if labels collide case-insensitively.
    assert normalise_answer("INCONCLUSIVE", s) == "inconclusive"


def test_normalise_leaves_unknown_unchanged():
    s = _binary()
    assert normalise_answer("banana", s) == "banana"


def test_is_inconclusive():
    assert is_inconclusive("inconclusive")
    assert not is_inconclusive("yes")
    assert not is_inconclusive("not_applicable")


def test_is_band_shape():
    assert is_band_shape("percentage_band")
    assert is_band_shape("ordinal_magnitude")
    assert is_band_shape("count_band")
    assert not is_band_shape("binary")
    assert not is_band_shape("categorical")


def test_band_distance_exact_match():
    s = _band()
    assert band_distance(">90%", ">90%", s.allowed_answers) == 0


def test_band_distance_adjacent():
    s = _band()
    assert band_distance(">90%", "71-90%", s.allowed_answers) == 1
    assert band_distance("71-90%", ">90%", s.allowed_answers) == 1


def test_band_distance_far_apart():
    s = _band()
    assert band_distance(">90%", "<10%", s.allowed_answers) == 5


def test_band_distance_none_when_label_unknown():
    s = _band()
    # `inconclusive` is not in the band sequence.
    assert band_distance("inconclusive", ">90%", s.allowed_answers) is None


def test_all_valid_includes_escape_valves():
    s = _binary()
    assert "yes" in s.all_valid
    assert "no" in s.all_valid
    assert INCONCLUSIVE in s.all_valid
    assert NOT_APPLICABLE in s.all_valid
