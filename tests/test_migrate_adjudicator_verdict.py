"""Tests for the EXP-16 adjudicator_verdict CHECK-widening migration.

Run against a temporary database with the original (narrow) constraint, so the
live data is never touched. Pin: the new verdict inserts after migration, the
old verdicts still insert, an invalid verdict still fails, rows are preserved,
and a second run is a no-op.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts.migrate_adjudicator_verdict import (
    NEW_VERDICT,
    already_widened,
    migrate,
)

OLD_TABLE = """
CREATE TABLE phase2_adjudications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    pair_run_id         TEXT NOT NULL,
    question_id         TEXT NOT NULL,
    country_code        TEXT NOT NULL,
    adjudicator_verdict TEXT NOT NULL CHECK (adjudicator_verdict IN (
                            'researcher_correct','verifier_correct',
                            'neither','escalate_human')),
    adjudicator_answer  TEXT,
    adjudicator_confidence REAL,
    adjudicator_reasoning TEXT NOT NULL,
    chosen_source_url   TEXT,
    chosen_evidence_quote TEXT,
    failure_mode        TEXT,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    wall_clock_ms       INTEGER,
    estimated_cost_usd  REAL,
    prompt_version_id   INTEGER,
    model_version       TEXT NOT NULL,
    raw_response        TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
, experiment_id TEXT)
"""

COLS = ("run_id, pair_run_id, question_id, country_code, "
        "adjudicator_verdict, adjudicator_reasoning, model_version")
ROW = "('r','p','Q','NL',?, 'because','sonnet')"


def _seed(path):
    conn = sqlite3.connect(str(path))
    # The adjudications table has an FK to prompt_versions; with FK enforcement
    # on, the referenced table must exist, so seed a minimal stand-in.
    conn.execute("CREATE TABLE prompt_versions (id INTEGER PRIMARY KEY)")
    conn.execute(OLD_TABLE)
    conn.execute("CREATE INDEX idx_p2adj_pair ON phase2_adjudications(pair_run_id)")
    conn.execute("CREATE INDEX idx_p2adj_experiment ON phase2_adjudications(experiment_id)")
    for v in ("researcher_correct", "verifier_correct", "neither"):
        conn.execute(f"INSERT INTO phase2_adjudications ({COLS}) VALUES {ROW}", (v,))
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    _seed(p)
    return p


def test_old_constraint_rejects_new_verdict_before_migration(db):
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"INSERT INTO phase2_adjudications ({COLS}) VALUES {ROW}",
                     (NEW_VERDICT,))
    conn.close()


def test_migration_allows_new_verdict_and_preserves_rows(db):
    status = migrate(db, make_backup=False)
    assert "migrated" in status
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM phase2_adjudications").fetchone()[0] == 3
    # new verdict now inserts
    conn.execute(f"INSERT INTO phase2_adjudications ({COLS}) VALUES {ROW}",
                 (NEW_VERDICT,))
    # an old verdict still inserts
    conn.execute(f"INSERT INTO phase2_adjudications ({COLS}) VALUES {ROW}",
                 ("escalate_human",))
    conn.commit()
    conn.close()


def test_invalid_verdict_still_rejected_after_migration(db):
    migrate(db, make_backup=False)
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"INSERT INTO phase2_adjudications ({COLS}) VALUES {ROW}",
                     ("garbage",))
    conn.close()


def test_indexes_recreated(db):
    migrate(db, make_backup=False)
    conn = sqlite3.connect(str(db))
    idx = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='phase2_adjudications'").fetchall()}
    assert {"idx_p2adj_pair", "idx_p2adj_experiment"} <= idx
    conn.close()


def test_migration_is_idempotent(db):
    assert "migrated" in migrate(db, make_backup=False)
    conn = sqlite3.connect(str(db))
    assert already_widened(conn)
    conn.close()
    assert "no-op" in migrate(db, make_backup=False)
