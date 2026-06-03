"""Tests that _find_resumable_researcher is scoped to its own arm.

For paired experiments (EXP-7, D39) baseline and chained run on the identical
pairs, often back to back. An unscoped resume would let one arm inherit the
other's Researcher row and silently mix the arms. The resume must match on
experiment_id AND condition_label. Production (NULL experiment, 'baseline')
must still resume its own rows.

Offline: a temp SQLite DB with the minimal columns the resume query reads, with
`connect` monkeypatched to point at it.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.run_coordinator as rc


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE phase2_researcher_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_run_id TEXT, question_id TEXT, country_code TEXT,
            retry_count INTEGER, answer TEXT, answer_explanation TEXT,
            evidence_quote TEXT, source_url TEXT,
            retrieval_confidence REAL, answer_confidence REAL,
            search_queries_used TEXT, fetched_urls TEXT,
            domain_trust_score REAL, language_route_used TEXT, notes TEXT,
            failure_mode TEXT,
            created_at TEXT, experiment_id TEXT, condition_label TEXT
        );
        CREATE TABLE subtrio_status (
            subtrio_id TEXT, stage TEXT, updated_at TEXT
        );
        CREATE TABLE phase2_final (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pair_run_id TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def _insert_researcher(path: Path, *, pair_run_id, experiment_id,
                       condition_label, answer="yes",
                       failure_mode=None) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO phase2_researcher_runs (
            pair_run_id, question_id, country_code, retry_count, answer,
            answer_explanation, evidence_quote, source_url,
            retrieval_confidence, answer_confidence, search_queries_used,
            fetched_urls, domain_trust_score, language_route_used, notes,
            failure_mode, created_at, experiment_id, condition_label
        ) VALUES (?, 'P1', 'MT', 0, ?, 'x', 'a quote here', 'https://x.mt',
                  0.8, 0.7, '[]', '[]', 1.0, 'native', NULL,
                  ?, '2026-06-03T00:00:00Z', ?, ?)""",
        (pair_run_id, answer, failure_mode, experiment_id, condition_label),
    )
    # Orphaned subtrio with no final row -> resumable if scope matches.
    conn.execute(
        "INSERT INTO subtrio_status (subtrio_id, stage, updated_at) "
        "VALUES (?, 'orphaned', '2026-06-03T00:00:00Z')",
        (pair_run_id,),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    db = tmp_path / "resume.db"
    _make_db(db)

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(rc, "connect", _connect)
    return db


def test_chained_does_not_resume_baseline_row(patched_db):
    # A baseline production row exists.
    _insert_researcher(patched_db, pair_run_id="b1",
                       experiment_id=None, condition_label="baseline")
    # A chained EXP-7 run must NOT pick it up.
    got = rc._find_resumable_researcher(
        "P1", "MT", experiment_id="retry_chaining_mt_v1",
        condition_label="chained",
    )
    assert got is None


def test_chained_resumes_its_own_row(patched_db):
    _insert_researcher(patched_db, pair_run_id="c1",
                       experiment_id="retry_chaining_mt_v1",
                       condition_label="chained")
    got = rc._find_resumable_researcher(
        "P1", "MT", experiment_id="retry_chaining_mt_v1",
        condition_label="chained",
    )
    assert got is not None
    assert got["pair_run_id"] == "c1"


def test_baseline_does_not_resume_chained_row(patched_db):
    _insert_researcher(patched_db, pair_run_id="c1",
                       experiment_id="retry_chaining_mt_v1",
                       condition_label="chained")
    # A production run (NULL experiment, baseline) must not grab the chained row.
    got = rc._find_resumable_researcher(
        "P1", "MT", experiment_id=None, condition_label="baseline",
    )
    assert got is None


def test_production_still_resumes_production_row(patched_db):
    # The common case is unchanged: NULL experiment + baseline resumes its own.
    _insert_researcher(patched_db, pair_run_id="b1",
                       experiment_id=None, condition_label="baseline")
    got = rc._find_resumable_researcher(
        "P1", "MT", experiment_id=None, condition_label="baseline",
    )
    assert got is not None
    assert got["pair_run_id"] == "b1"


def test_does_not_resume_inconclusive_row(patched_db):
    # An abstention is not a result; resuming from it stranded pairs at
    # 'researching' with no phase2_final. The finder must skip it.
    _insert_researcher(patched_db, pair_run_id="b1", answer="inconclusive",
                       experiment_id=None, condition_label="baseline")
    got = rc._find_resumable_researcher(
        "P1", "MT", experiment_id=None, condition_label="baseline",
    )
    assert got is None


def test_does_not_resume_failed_row(patched_db):
    # A Researcher row that failed (failure_mode set, e.g. url_unreachable)
    # is not a clean result; a fresh Researcher call is the right move.
    _insert_researcher(patched_db, pair_run_id="b1", answer="no",
                       failure_mode="url_unreachable",
                       experiment_id=None, condition_label="baseline")
    got = rc._find_resumable_researcher(
        "P1", "MT", experiment_id=None, condition_label="baseline",
    )
    assert got is None


def test_two_arms_each_resume_their_own(patched_db):
    _insert_researcher(patched_db, pair_run_id="b1", answer="yes",
                       experiment_id="retry_chaining_mt_v1",
                       condition_label="baseline")
    _insert_researcher(patched_db, pair_run_id="c1", answer="no",
                       experiment_id="retry_chaining_mt_v1",
                       condition_label="chained")
    base = rc._find_resumable_researcher(
        "P1", "MT", experiment_id="retry_chaining_mt_v1",
        condition_label="baseline")
    chain = rc._find_resumable_researcher(
        "P1", "MT", experiment_id="retry_chaining_mt_v1",
        condition_label="chained")
    assert base["pair_run_id"] == "b1"
    assert chain["pair_run_id"] == "c1"
