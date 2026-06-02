"""Unit tests for db.cancel_subtrio.

Covers the deletion scoping that matters for the audit trail: cancelling
one in-flight subtrio wipes only that run's rows, leaves sibling runs of
the same (question, country) pair alone, and never touches the cost
receipt in claude_usage_log.

The process-kill path is exercised indirectly: rows carry
process_pid=None, so _pid_is_coordinator is never consulted and nothing
is signalled. Killing a live coordinator is covered by manual use of the
Run Console, not here, to avoid spawning real processes in CI.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db


def _build_db(path: Path) -> None:
    """Minimal schema: only the columns cancel_subtrio reads or deletes."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE subtrio_status (
            subtrio_id TEXT PRIMARY KEY,
            batch_id TEXT, question_id TEXT, country_code TEXT,
            process_pid INTEGER
        );
        CREATE TABLE phase2_final (pair_run_id TEXT, question_id TEXT);
        CREATE TABLE phase2_adjudications (pair_run_id TEXT);
        CREATE TABLE phase2_verifier_runs (pair_run_id TEXT);
        CREATE TABLE phase2_researcher_runs (pair_run_id TEXT);
        CREATE TABLE claude_usage_log (subtrio_id TEXT);
        """
    )
    # Target run (will be cancelled) and a sibling run of the same pair
    # that must survive.
    conn.executescript(
        """
        INSERT INTO subtrio_status VALUES ('A', 'b1', 'P1', 'FR', NULL);
        INSERT INTO subtrio_status VALUES ('B', 'b1', 'P1', 'FR', NULL);

        INSERT INTO phase2_researcher_runs VALUES ('A'), ('A'), ('B');
        INSERT INTO phase2_verifier_runs VALUES ('A'), ('B');
        INSERT INTO phase2_adjudications VALUES ('A');
        INSERT INTO phase2_final VALUES ('B', 'P1');

        INSERT INTO claude_usage_log VALUES ('A'), ('A'), ('B');
        """
    )
    conn.commit()
    conn.close()


def _count(path: Path, table: str, where: str = "1=1") -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def test_cancel_scopes_deletion_to_one_subtrio(tmp_path, monkeypatch):
    db_path = tmp_path / "odmi.db"
    _build_db(db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)

    result = db.cancel_subtrio("A")

    # No live pid recorded, so nothing was signalled.
    assert result["killed"] is False
    assert result["pid"] is None

    # Target run's rows are gone across every phase2 table and the
    # status row itself.
    assert _count(db_path, "subtrio_status", "subtrio_id = 'A'") == 0
    assert _count(db_path, "phase2_researcher_runs", "pair_run_id = 'A'") == 0
    assert _count(db_path, "phase2_verifier_runs", "pair_run_id = 'A'") == 0
    assert _count(db_path, "phase2_adjudications", "pair_run_id = 'A'") == 0
    assert _count(db_path, "phase2_final", "pair_run_id = 'A'") == 0

    # Reported counts match what was there.
    assert result["deleted"]["phase2_researcher_runs"] == 2
    assert result["deleted"]["phase2_verifier_runs"] == 1
    assert result["deleted"]["phase2_adjudications"] == 1
    assert result["deleted"]["phase2_final"] == 0
    assert result["deleted"]["subtrio_status"] == 1

    # Sibling run B (same P1/FR pair) is untouched.
    assert _count(db_path, "subtrio_status", "subtrio_id = 'B'") == 1
    assert _count(db_path, "phase2_researcher_runs", "pair_run_id = 'B'") == 1
    assert _count(db_path, "phase2_final", "pair_run_id = 'B'") == 1

    # Cost receipt is preserved for both runs.
    assert _count(db_path, "claude_usage_log") == 3


def test_cancel_unknown_subtrio_is_a_noop(tmp_path, monkeypatch):
    db_path = tmp_path / "odmi.db"
    _build_db(db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)

    result = db.cancel_subtrio("does-not-exist")

    assert result["killed"] is False
    assert result["pid"] is None
    assert sum(result["deleted"].values()) == 0
    # Both real runs still intact.
    assert _count(db_path, "subtrio_status") == 2
