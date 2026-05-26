"""Unit tests for the D28 answer-shape classifier."""

from __future__ import annotations

from scripts.migrate_d28_shapes import classify


def test_simple_yes_no_is_binary():
    shape, allowed = classify("{'yes': 20, 'no': 0}")
    assert shape == "binary"
    assert allowed == ["yes", "no"]


def test_yes_no_with_other_is_binary_and_keeps_other():
    shape, allowed = classify("{'yes': 40, 'no': 0, 'other': 40}")
    assert shape == "binary"
    assert "other" in allowed


def test_yes_no_with_not_applicable_is_binary():
    shape, allowed = classify("{'yes': 20, 'no': 0, 'not applicable': 20}")
    assert shape == "binary"
    assert allowed == ["yes", "no", "not applicable"]


def test_long_yes_variant_still_classes_as_binary():
    shape, allowed = classify(
        "{'yes, or all public sector data providers already publish data': 20, 'no': 0}"
    )
    assert shape == "binary"
    assert allowed[0].startswith("yes,")
    assert "no" in allowed


def test_six_band_percentage_is_percentage_band():
    shape, allowed = classify(
        "{'>90%': 25, '71-90%': 20, '51-70%': 15, '31-50%': 10, '10-30%': 5, '<10%': 0}"
    )
    assert shape == "percentage_band"
    assert allowed[0] == ">90%"
    assert allowed[-1] == "<10%"


def test_q2_eight_band_dedupes_duplicate_one_key():
    # Q2 has both '1' (str) and 1 (int) as keys with the same value 20.
    shape, allowed = classify(
        "{'1': 20, 1: 20, '100%': 20, '90-99%': 18, '70-89%': 15, "
        "'50-69%': 10, '30-49%': 5, '<30%': 0}"
    )
    assert shape == "percentage_band"
    # Duplicate '1' / 1 collapses to a single entry.
    assert allowed.count("1") == 1
    assert allowed == ["1", "100%", "90-99%", "70-89%", "50-69%", "30-49%", "<30%"]


def test_p29_count_band():
    shape, allowed = classify(
        "{'yes, >9': 20, 'yes, 6-9': 15, 'yes, 3-5': 10, 'yes, 1-2': 5, 'no': 0}"
    )
    assert shape == "count_band"
    assert "yes, >9" in allowed
    assert "no" in allowed


def test_q13_count_band_numeric_only():
    shape, allowed = classify(
        "{'1-4': 20, '5-10': 5, '>10': 0, \"i don't know\": 0}"
    )
    assert shape == "count_band"
    assert "1-4" in allowed
    assert ">10" in allowed


def test_p14_categorical():
    shape, allowed = classify("{'top-down': 0, 'bottom-up': 0, 'hybrid': 0}")
    assert shape == "categorical"
    assert set(allowed) == {"top-down", "bottom-up", "hybrid"}


def test_q3_categorical_temporal():
    shape, allowed = classify(
        "{'within one day': 40, 'within one week': 15, 'within one month': 5, "
        "\"longer than one month or i don't know\": 0}"
    )
    assert shape == "categorical"
    assert allowed[0] == "within one day"


def test_p16_ordinal_magnitude():
    shape, allowed = classify(
        "{'all public bodies': 20, 'the majority of public bodies': 15, "
        "'approximately half of the public bodies': 10, "
        "'few public bodies': 5, 'none of the public bodies': 0, "
        "'not applicable': 20}"
    )
    assert shape == "ordinal_magnitude"
    assert allowed[0].startswith("all")


def test_degenerate_yes_no_zero_zero_still_binary():
    shape, allowed = classify("{'yes': 0, 'no': 0}")
    assert shape == "binary"
    assert allowed == ["yes", "no"]


def test_none_key_degenerate_falls_back_to_binary():
    shape, allowed = classify("{None: 0}")
    assert shape == "binary"
    assert allowed == ["yes", "no"]


def test_empty_or_none_falls_back_to_binary():
    assert classify(None) == ("binary", ["yes", "no"])
    assert classify("") == ("binary", ["yes", "no"])


def test_unparsable_falls_back_to_binary():
    shape, allowed = classify("totally not a python dict")
    assert shape == "binary"
    assert allowed == ["yes", "no"]
