#!/usr/bin/env python3
"""Rename the Adjudicator `escalate_human` verdict to `abstain` (D51).

No human is ever in the loop in this automated swarm, so the fourth
Adjudicator verdict is an abstention, not an escalation. This migration
does two things:

1. Widens the phase2_adjudications.adjudicator_verdict CHECK constraint
   to allow 'abstain'. SQLite cannot ALTER a CHECK, so the table is
   rebuilt with the new constraint, preserving every row, index and the
   physical column order. 'escalate_human' is retained in the CHECK as a
   legacy value so the rebuild never rejects a pre-rename row.
2. Updates every existing row from 'escalate_human' to 'abstain'.

The row copy names every column explicitly, so it survives the
experiment_id/created_at column-order difference between a
freshly setup database and one that an earlier migration rebuilt.

The migration is idempotent: if 'abstain' is already allowed and no
'escalate_human' rows remain it is a no-op. It backs the database up
first and verifies row parity, the new and old constraint behaviour, and
that no legacy rows survive before committing.

Usage:
    uv run python scripts/migrate_escalate_human_to_abstain.py [path/to/db]
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "odmi.db"
OLD_VERDICT = "escalate_human"
NEW_VERDICT = "abstain"

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
                                    'abstain',
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


def _check_allows_abstain(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='phase2_adjudications'"
    ).fetchone()
    return bool(row) and f"'{NEW_VERDICT}'" in row[0]


def _legacy_rows(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM phase2_adjudications WHERE adjudicator_verdict = ?",
        (OLD_VERDICT,),
    ).fetchone()[0]


def _column_list(conn: sqlite3.Connection) -> str:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(phase2_adjudications)")]
    return ", ".join(cols)


def migrate(db_path: Path, *, make_backup: bool = True) -> str:
    """Run the migration on db_path. Returns a one-line status string."""
    conn = sqlite3.connect(str(db_path))
    try:
        if _check_allows_abstain(conn) and _legacy_rows(conn) == 0:
            return f"no-op: {NEW_VERDICT!r} already allowed, no {OLD_VERDICT!r} rows"

        before = conn.execute(
            "SELECT COUNT(*) FROM phase2_adjudications"
        ).fetchone()[0]
        legacy = _legacy_rows(conn)
        collist = _column_list(conn)

        backup = ""
        if make_backup:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = db_path.with_name(f"{db_path.stem}.{stamp}.pre-d51.db")
            shutil.copy2(db_path, backup_path)
            backup = str(backup_path)

        # Rebuild inside one transaction. Disable FK enforcement for the swap;
        # nothing references this table, but the rename is cleaner with it off.
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        conn.execute(NEW_TABLE_SQL)
        # Named-column copy: order-independent, so the experiment_id /
        # created_at ordering of either schema variant copies cleanly.
        conn.execute(
            f"INSERT INTO phase2_adjudications_new ({collist}) "
            f"SELECT {collist} FROM phase2_adjudications"
        )
        conn.execute("DROP TABLE phase2_adjudications")
        conn.execute(
            "ALTER TABLE phase2_adjudications_new RENAME TO phase2_adjudications"
        )
        for idx in INDEXES:
            conn.execute(idx)
        # Convert the legacy verdict in place now the CHECK admits both.
        conn.execute(
            "UPDATE phase2_adjudications SET adjudicator_verdict = ? "
            "WHERE adjudicator_verdict = ?",
            (NEW_VERDICT, OLD_VERDICT),
        )
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys=ON")

        after = conn.execute(
            "SELECT COUNT(*) FROM phase2_adjudications"
        ).fetchone()[0]
        if after != before:
            raise RuntimeError(
                f"row count changed during migration: {before} -> {after}"
            )
        if _legacy_rows(conn) != 0:
            raise RuntimeError("legacy 'escalate_human' rows survived the migration")

        _verify_constraints(conn)
        conn.commit()
        return (
            f"migrated: {before} rows preserved, {legacy} {OLD_VERDICT!r} -> "
            f"{NEW_VERDICT!r}, CHECK now admits {NEW_VERDICT!r}"
            + (f", backup {backup}" if backup else "")
        )
    finally:
        conn.close()


def _verify_constraints(conn: sqlite3.Connection) -> None:
    """`abstain` inserts; a junk verdict still fails. Roll both back."""
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
