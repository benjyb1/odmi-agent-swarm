"""Tests for the EXP-40 ablation adapter (evaluation/exp40_analysis.py).

The adapter normalises four arms onto the exp36 reader vocabulary. Its job is to
change the pipeline being scored, not the outcome of any pair: a crashed pair
must stay crashed. Folding `agent_failure` into an abstention would report a
crash as a decision to decline, which is the Selectivity claim the ablation is
supposed to measure.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.exp36_analysis import three_outcome
from evaluation.exp40_analysis import (
    EXP34,
    EXP34_COND,
    EXP40,
    build_arms,
    completed_only,
)


def _db() -> sqlite3.Connection:
    """A minimal DB carrying the columns the adapter reads."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE phase2_final (
            id INTEGER PRIMARY KEY, pair_run_id TEXT, question_id TEXT,
            country_code TEXT, terminal_status TEXT, final_answer TEXT,
            experiment_id TEXT
        );
        CREATE TABLE phase2_researcher_runs (
            id INTEGER PRIMARY KEY, pair_run_id TEXT, question_id TEXT,
            country_code TEXT, retry_count INTEGER, answer TEXT,
            answer_confidence REAL, condition_label TEXT, experiment_id TEXT
        );
        CREATE TABLE ground_truth (
            question_id TEXT, country_code TEXT, response TEXT,
            decision TEXT, dimension TEXT
        );
        CREATE TABLE questions (question_id TEXT, answer_shape TEXT);
        """
    )
    return conn


def _pair(
    conn: sqlite3.Connection,
    qid: str,
    status: str,
    answer: str | None = "yes",
    gold: str = "yes",
    r0_answer: str | None = "yes",
    r0_conf: float | None = 0.9,
    coop_status: str = "accepted_cooperative",
) -> None:
    """Seed one exp34 pair, its cooperative counterpart and its ground truth.

    The cooperative arm is a separate live run, so every pair exists in both.
    """
    prid = f"pr-{qid}"
    conn.execute(
        "INSERT INTO phase2_final (pair_run_id, question_id, country_code,"
        " terminal_status, final_answer, experiment_id) VALUES (?,?,?,?,?,?)",
        (f"coop-{qid}", qid, "MT", coop_status, "yes", EXP40),
    )
    conn.execute(
        "INSERT INTO phase2_final (pair_run_id, question_id, country_code,"
        " terminal_status, final_answer, experiment_id) VALUES (?,?,?,?,?,?)",
        (prid, qid, "MT", status, answer, EXP34),
    )
    conn.execute(
        "INSERT INTO phase2_researcher_runs (pair_run_id, question_id,"
        " country_code, retry_count, answer, answer_confidence,"
        " condition_label, experiment_id) VALUES (?,?,?,?,?,?,?,?)",
        (prid, qid, "MT", 0, r0_answer, r0_conf, EXP34_COND, EXP34),
    )
    conn.execute(
        "INSERT INTO ground_truth (question_id, country_code, response,"
        " decision, dimension) VALUES (?,?,?,?,?)",
        (qid, "MT", gold, "confirm", "Policy"),
    )
    conn.execute(
        "INSERT INTO questions (question_id, answer_shape) VALUES (?,?)",
        (qid, "binary"),
    )
    conn.commit()


def test_crashed_pair_stays_crashed_in_every_adversarial_arm():
    """A crashed pair must not be recoded as an abstention."""
    conn = _db()
    _pair(conn, "P1", "accepted_by_verifier")
    _pair(conn, "P2", "agent_failure", answer=None)

    arms = build_arms(conn)

    for name in ("trio", "no_adjudicator", "researcher_only"):
        statuses = {r.question_id: r.terminal_status for r in arms[name]}
        assert statuses["P2"] == "agent_failure", (
            f"{name}: a crashed pair must stay crashed, got {statuses['P2']!r}"
        )


def test_three_outcome_sees_the_failure():
    """The reader already splits failures from abstentions; the adapter must
    not hide them before it gets there."""
    conn = _db()
    _pair(conn, "P1", "accepted_by_verifier")
    _pair(conn, "P2", "agent_failure", answer=None)
    _pair(conn, "P3", "abstained_adjudicator", answer="inconclusive")

    read = three_outcome(build_arms(conn)["trio"])

    assert read["n_failed"] == 1, f"expected 1 crash, got {read['n_failed']}"
    assert read["n_abstained"] == 1, (
        f"the crash must not inflate abstentions, got {read['n_abstained']}"
    )


def test_completed_only_drops_crashed_pairs_across_all_arms():
    """Coverage denominators must be able to exclude crashes, and the same
    pairs must go from every arm so the arms stay paired."""
    conn = _db()
    _pair(conn, "P1", "accepted_by_verifier")
    _pair(conn, "P2", "agent_failure", answer=None)

    trimmed = completed_only(build_arms(conn))

    for name, rows in trimmed.items():
        qids = {r.question_id for r in rows}
        assert "P2" not in qids, f"{name} still carries the crashed pair"
    lengths = {len(rows) for rows in trimmed.values()}
    assert lengths == {1}, f"arms must stay paired on the same pairs, got {lengths}"


def test_researcher_only_ignores_a_below_floor_attempt():
    """The researcher-only arm commits only at or above the 0.65 floor."""
    conn = _db()
    _pair(conn, "P1", "accepted_by_verifier", r0_answer="yes", r0_conf=0.40)

    row = build_arms(conn)["researcher_only"][0]

    assert row.terminal_status != "accepted_by_verifier", (
        "a 0.40-confidence attempt is below the 0.65 floor and must abstain"
    )


def test_missing_attempt1_row_is_reported_not_silently_abstained():
    """The 17 exp34 pairs with no retry_count=0 row are a logging gap, not a
    researcher decision. The arm still abstains on them, but the adapter must
    say how many it could not read so the number is disclosable."""
    conn = _db()
    _pair(conn, "P1", "accepted_by_verifier")
    _pair(conn, "P2", "abstained_adjudicator", answer="inconclusive")
    # P2 loses its attempt-1 row but keeps the retry that followed, exactly as
    # the 17 real pairs did: the pair still ran, so it stays in the arm.
    conn.execute(
        "UPDATE phase2_researcher_runs SET retry_count=1 WHERE question_id='P2'"
    )
    conn.commit()

    arms = build_arms(conn)
    gaps = [r for r in arms["researcher_only"] if r.question_id == "P2"]

    assert gaps and gaps[0].terminal_status != "accepted_by_verifier", (
        "an unreadable attempt-1 cannot commit"
    )
    from evaluation.exp40_analysis import attempt1_gap_pairs

    assert attempt1_gap_pairs(conn) == [("P2", "MT")], (
        "the adapter must report which pairs had no readable attempt-1 row"
    )
