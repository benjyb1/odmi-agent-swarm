"""Integration test for the D28 `near_match` state in _MATCH_STATUS_SQL.

Builds a small in-memory schema mirroring `questions`, `phase2_final`
and `ground_truth`, inserts one row per scenario, and asserts the
match_status the SQL returns.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from dashboard.lib.db import _MATCH_STATUS_SQL


@pytest.fixture()
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE questions (
            question_id     TEXT PRIMARY KEY,
            answer_shape    TEXT,
            allowed_answers TEXT
        );
        CREATE TABLE phase2_final (
            pair_run_id  TEXT PRIMARY KEY,
            question_id  TEXT,
            country_code TEXT,
            final_answer TEXT,
            experiment_id TEXT
        );
        CREATE TABLE ground_truth (
            question_id  TEXT,
            country_code TEXT,
            response     TEXT,
            PRIMARY KEY (question_id, country_code)
        );
        """
    )
    return conn


def _insert_question(conn, qid: str, shape: str, allowed: list[str]) -> None:
    conn.execute(
        "INSERT INTO questions(question_id, answer_shape, allowed_answers) "
        "VALUES (?, ?, ?)",
        (qid, shape, json.dumps(allowed)),
    )


def _insert_pair(conn, qid: str, swarm: str, odmi: str) -> None:
    conn.execute(
        "INSERT INTO phase2_final(pair_run_id, question_id, country_code, "
        "final_answer) VALUES (?, ?, 'FR', ?)",
        (qid + "_pair", qid, swarm),
    )
    conn.execute(
        "INSERT INTO ground_truth(question_id, country_code, response) "
        "VALUES (?, 'FR', ?)",
        (qid, odmi),
    )


def _status(conn) -> list[tuple[str, str]]:
    rows = conn.execute(
        f"""
        SELECT f.question_id, {_MATCH_STATUS_SQL} AS match_status
        FROM phase2_final f
        LEFT JOIN ground_truth gt
          ON gt.question_id = f.question_id
         AND gt.country_code = f.country_code
        """
    ).fetchall()
    return [(r["question_id"], r["match_status"]) for r in rows]


def test_not_applicable_underscore_matches_space(db):
    # The swarm writes the sentinel as `not_applicable`; ODMI gold carries
    # `not applicable`. These are the same answer and must score `match`,
    # not `differ` (the Norway underscore-vs-space scoring artefact).
    _insert_question(db, "NA1", "binary", ["yes", "no", "not applicable"])
    _insert_pair(db, "NA1", swarm="not_applicable", odmi="not applicable")
    assert dict(_status(db))["NA1"] == "match"


def test_not_applicable_space_matches_underscore_gold(db):
    # Symmetric: gold underscore, swarm space.
    _insert_question(db, "NA2", "binary", ["yes", "no", "not applicable"])
    _insert_pair(db, "NA2", swarm="not applicable", odmi="not_applicable")
    assert dict(_status(db))["NA2"] == "match"


def test_exact_band_match(db):
    _insert_question(
        db, "Q12", "percentage_band",
        [">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"],
    )
    _insert_pair(db, "Q12", "71-90%", "71-90%")
    assert _status(db) == [("Q12", "match")]


def test_adjacent_band_is_near_match(db):
    _insert_question(
        db, "Q12", "percentage_band",
        [">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"],
    )
    _insert_pair(db, "Q12", "71-90%", ">90%")
    assert _status(db) == [("Q12", "near_match")]


def test_two_band_gap_is_differ(db):
    _insert_question(
        db, "Q12", "percentage_band",
        [">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"],
    )
    _insert_pair(db, "Q12", "51-70%", ">90%")
    assert _status(db) == [("Q12", "differ")]


def test_ordinal_magnitude_adjacent(db):
    _insert_question(
        db, "P16", "ordinal_magnitude",
        [
            "all public bodies",
            "the majority of public bodies",
            "approximately half of the public bodies",
            "few public bodies",
            "none of the public bodies",
        ],
    )
    _insert_pair(db, "P16", "the majority of public bodies", "all public bodies")
    assert _status(db) == [("P16", "near_match")]


def test_categorical_never_near_match(db):
    # P14's shape is categorical (no inherent order). The SQL only
    # fires near_match for ordered shapes; categorical disagreements
    # stay as `differ`.
    _insert_question(db, "P14", "categorical", ["top-down", "bottom-up", "hybrid"])
    _insert_pair(db, "P14", "top-down", "bottom-up")
    assert _status(db) == [("P14", "differ")]


def test_binary_disagreement_stays_differ(db):
    # A yes/no question swapped doesn't qualify as adjacent because
    # binary shape isn't in the ordered list.
    _insert_question(db, "P17", "binary", ["yes", "no"])
    _insert_pair(db, "P17", "yes", "no")
    assert _status(db) == [("P17", "differ")]


def test_inconclusive_is_abstained_not_near_match(db):
    # `inconclusive` is an honest abstention (D35/D37). It gets its own
    # `abstained` status, never near_match and never differ, so the
    # abstention rate can be read on its own. It is still counted against
    # accuracy by accuracy_summary.
    _insert_question(
        db, "Q12", "percentage_band",
        [">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%"],
    )
    _insert_pair(db, "Q12", "inconclusive", "71-90%")
    assert _status(db) == [("Q12", "abstained")]


def test_yes_variant_swarm_matches_yes_prefix_on_binary(db):
    # ODMI ground truth often carries 'yes, with X' style responses on
    # binary questions. A swarm 'yes' should match those.
    _insert_question(db, "P25", "binary", ["yes", "no"])
    _insert_pair(db, "P25", "yes", "yes, with monitoring")
    assert _status(db) == [("P25", "match")]


def test_bare_yes_does_not_match_count_band_gold(db):
    # On a count_band question a bare `yes` is under-specified: it must
    # not score an exact match against a richer gold like `yes, >9`.
    _insert_question(
        db, "P29", "count_band",
        ["no", "yes, 1-2", "yes, 3-5", "yes, >9"],
    )
    _insert_pair(db, "P29", "yes", "yes, >9")
    assert _status(db) == [("P29", "differ")]


def test_sentinel_label_is_not_an_adjacent_band(db):
    # `not applicable` sits at the end of some ordinal allowed_answers
    # lists but is not a band step. A swarm `none...` against a gold of
    # `not applicable` must be differ, not a spurious near_match.
    _insert_question(
        db, "P16", "ordinal_magnitude",
        [
            "all public bodies",
            "the majority of public bodies",
            "approximately half of the public bodies",
            "few public bodies",
            "none of the public bodies",
            "not applicable",
        ],
    )
    _insert_pair(db, "P16", "none of the public bodies", "not applicable")
    assert _status(db) == [("P16", "differ")]


def test_case_insensitive_match(db):
    _insert_question(db, "P1", "binary", ["yes", "no", "other"])
    _insert_pair(db, "P1", "Yes", "YES")
    assert _status(db) == [("P1", "match")]
