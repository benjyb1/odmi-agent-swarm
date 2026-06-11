"""Integration tests for accuracy_summary against a temp file DB.

accuracy_summary() opens its own connection via the module-level DB_PATH, so
we point that at a throwaway SQLite file, build the three tables it joins, and
assert the headline counts. Covers three fixes:

- per-pair dedup: a re-dispatched pair with two phase2_final rows is counted
  once (the latest), never as both match and differ;
- n_failed: an empty/NULL final_answer is its own metric, split out of the
  ground-truth-missing bucket;
- n_flag_review: a committed answer on an n/a gold is surfaced for review and
  excluded from the accuracy denominator.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import dashboard.lib.db as db


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "odmi_test.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE questions (
            question_id     TEXT PRIMARY KEY,
            answer_shape    TEXT,
            allowed_answers TEXT
        );
        CREATE TABLE phase2_final (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_run_id   TEXT,
            question_id   TEXT,
            country_code  TEXT,
            final_answer  TEXT,
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

    def q(qid, allowed):
        conn.execute(
            "INSERT INTO questions(question_id, answer_shape, allowed_answers) "
            "VALUES (?, 'binary', ?)",
            (qid, json.dumps(allowed)),
        )

    def gt(qid, response):
        conn.execute(
            "INSERT INTO ground_truth(question_id, country_code, response) "
            "VALUES (?, 'NO', ?)",
            (qid, response),
        )

    def final(qid, answer):
        conn.execute(
            "INSERT INTO phase2_final(pair_run_id, question_id, country_code, "
            "final_answer, experiment_id) VALUES (?, ?, 'NO', ?, NULL)",
            (f"{qid}_{answer}", qid, answer),
        )

    yesno = ["yes", "no"]
    yesno_na = ["yes", "no", "not applicable"]
    for qid, allowed in [
        ("QM", yesno), ("QD", yesno), ("QA", yesno),
        ("QF", yesno), ("QR", yesno_na), ("QDUP", yesno),
    ]:
        q(qid, allowed)

    gt("QM", "yes"); final("QM", "yes")          # match
    gt("QD", "no"); final("QD", "yes")           # differ
    gt("QA", "yes"); final("QA", "inconclusive")  # abstained
    gt("QF", "yes"); final("QF", "")             # no_swarm_answer -> n_failed
    gt("QR", "n/a"); final("QR", "yes")          # committed on n/a -> flag_review
    # re-dispatched pair: first row differ, latest row match -> counts once
    gt("QDUP", "no"); final("QDUP", "yes"); final("QDUP", "no")

    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_accuracy_summary_dedups_and_splits_buckets(temp_db):
    s = db.accuracy_summary()
    # 6 distinct pairs, the duplicated one counted once.
    assert s["n_finalised"] == 6
    # QM plus the latest QDUP row ('no' == gold 'no').
    assert s["n_match"] == 2
    assert s["n_differ"] == 1
    assert s["n_abstained"] == 1
    assert s["n_failed"] == 1
    assert s["n_flag_review"] == 1
    assert s["n_no_truth"] == 0
    # denom = match + near + differ + abstained = 2 + 0 + 1 + 1 = 4
    assert s["accuracy"] == pytest.approx(2 / 4)
