#!/usr/bin/env python3
"""Widen the phase2_adjudications.adjudicator_verdict CHECK constraint.

EXP-16's free attempt-selection arm (--adjudicator-selection free) commits a new
verdict, 'attempt_correct' (the Adjudicator may commit any of the up-to-four
Researcher attempts). The original CHECK constraint allows only
researcher_correct / verifier_correct / neither / escalate_human, so the insert
would fail. SQLite cannot ALTER a CHECK, so this rebuilds the table with the
widened constraint, preserving every row, index, and the column order.

The migration is idempotent: if 'attempt_correct' is already allowed it is a
no-op. It backs the database up first and verifies row parity plus the new and
old constraint behaviour before committing.

Usage:
    uv run python scripts/migrate_adjudicator_verdict.py [path/to/db]
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "odmi.db"
NEW_VERDICT = "attempt_correct"

NEW_TABLE_SQL = """
CREATE TABLE phase2_adjudications_new (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      TEXT NOT NULL,
    pair_run_id                 TEXT NOT NULL,
    question_id                 TEXT NOT NULL,
    country_code                TEXT NOT NULL,

    adjudicator_verdict         TEXT NOT NULL CHECK (adjudicator_verdict IN (
                                    'researcher_correct',
                                    'verifier_correct',
                                    'neither',
                                    'escalate_human',
                                    'attempt_correct'
                                )),
    adjudicator_answer          TEXT,
    adjudicator_confidence      REAL,
    adjudicator_reasoning       TEXT NOT NULL,
    chosen_source_url           TEXT,
    chosen_evidence_quote       TEXT,

    failure_mode                TEXT,

    input_tokens                INTEGER,
    output_tokens               INTEGER,
    wall_clock_ms               INTEGER,
    estimated_cost_usd          REAL,

    prompt_version_id           INTEGER REFERENCES prompt_versions(id),
    model_version               TEXT NOT NULL,

    raw_response                TEXT,
    created_at                  TEXT DEFAULT (datetime('now'))
, experiment_id TEXT)
"""

INDEXES = [
    "CREATE INDEX idx_p2adj_pair ON phase2_adjudications(pair_run_id)",
    "CREATE INDEX idx_p2adj_experiment ON phase2_adjudications(experiment_id)",
]


def already_widened(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='phase2_adjudications'"
    ).fetchone()
    return bool(row) and NEW_VERDICT in row[0]


def migrate(db_path: Path, *, make_backup: bool = True) -> str:
    """Run the migration on db_path. Returns a one-line status string."""
    conn = sqlite3.connect(str(db_path))
    try:
        if already_widened(conn):
            return f"no-op: {NEW_VERDICT!r} already allowed"

        before = conn.execute(
            "SELECT COUNT(*) FROM phase2_adjudications"
        ).fetchone()[0]

        backup = ""
        if make_backup:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = db_path.with_name(f"{db_path.stem}.{stamp}.pre-exp16.db")
            shutil.copy2(db_path, backup_path)
            backup = str(backup_path)

        # Rebuild inside one transaction. Disable FK enforcement for the swap;
        # nothing references this table, but the rename is cleaner with it off.
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        conn.execute(NEW_TABLE_SQL)
        conn.execute(
            "INSERT INTO phase2_adjudications_new SELECT * FROM phase2_adjudications"
        )
        conn.execute("DROP TABLE phase2_adjudications")
        conn.execute(
            "ALTER TABLE phase2_adjudications_new RENAME TO phase2_adjudications"
        )
        for idx in INDEXES:
            conn.execute(idx)
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys=ON")

        after = conn.execute(
            "SELECT COUNT(*) FROM phase2_adjudications"
        ).fetchone()[0]
        if after != before:
            raise RuntimeError(
                f"row count changed during migration: {before} -> {after}"
            )

        _verify_constraints(conn)
        conn.commit()
        return (f"migrated: {before} rows preserved, {NEW_VERDICT!r} now allowed"
                + (f", backup {backup}" if backup else ""))
    finally:
        conn.close()


def _verify_constraints(conn: sqlite3.Connection) -> None:
    """The new verdict inserts; a junk verdict still fails. Roll both back."""
    cols = ("run_id, pair_run_id, question_id, country_code, "
            "adjudicator_verdict, adjudicator_reasoning, model_version")
    vals = "('_v','_v','_v','_v',?, '_v','_v')"
    conn.execute("SAVEPOINT verify")
    try:
        conn.execute(
            f"INSERT INTO phase2_adjudications ({cols}) VALUES {vals}",
            (NEW_VERDICT,),
        )  # must succeed
        failed = False
        try:
            conn.execute(
                f"INSERT INTO phase2_adjudications ({cols}) VALUES {vals}",
                ("garbage_verdict",),
            )
        except sqlite3.IntegrityError:
            failed = True
        if not failed:
            raise RuntimeError("CHECK no longer rejects an invalid verdict")
    finally:
        conn.execute("ROLLBACK TO verify")
        conn.execute("RELEASE verify")


def main() -> int:
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    if not db.exists():
        print(f"no database at {db}")
        return 1
    print(migrate(db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
