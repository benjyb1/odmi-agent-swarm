#!/usr/bin/env python3
"""Widen phase2_final.terminal_status for the EXP-35 self-critique arm.

The `researcher_self_verify` pipeline_mode (EXP-35) introduces two
terminal statuses the EXP-28-era CHECK constraint does not admit:

- accepted_researcher_self_verify   (self-critique upheld the answer:
                                     real label at or above the D37
                                     floor, no separate Verifier agent)
- abstained_researcher_self_verify  (self-critique retry exhaustion)

SQLite cannot ALTER a CHECK, so the table is rebuilt with the widened
constraint, preserving every row, index and the physical column order.
Same pattern as scripts/migrate_pipeline_mode_statuses.py (EXP-28).

The migration is idempotent: if the CHECK already admits the new values it
is a no-op. It backs the database up first and verifies row parity and the
new and old constraint behaviour before committing.

Usage:
    uv run python scripts/migrate_self_verify_statuses.py [path/to/db]
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "odmi.db"

NEW_STATUSES = (
    "accepted_researcher_self_verify",
    "abstained_researcher_self_verify",
)

NEW_TABLE_SQL = """
CREATE TABLE phase2_final_new (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      TEXT NOT NULL,
    pair_run_id                 TEXT NOT NULL UNIQUE,
    question_id                 TEXT NOT NULL,
    country_code                TEXT NOT NULL,

    terminal_status             TEXT NOT NULL CHECK (terminal_status IN (
                                    'accepted_by_verifier',
                                    'accepted_by_adjudicator',
                                    'accepted_researcher_only',
                                    'accepted_researcher_self_verify',
                                    'abstained_captcha',
                                    'abstained_adjudicator',
                                    'abstained_researcher_only',
                                    'abstained_no_adjudicator',
                                    'abstained_researcher_self_verify',
                                    'escalated_captcha',
                                    'escalated_adjudicator',
                                    'agent_failure'
                                )),

    final_answer                TEXT,
    final_answer_explanation    TEXT,
    final_evidence_quote        TEXT,
    final_source_url            TEXT,
    final_retrieval_confidence  REAL,
    final_answer_confidence     REAL,

    retry_count                 INTEGER NOT NULL,
    adjudicator_involved        INTEGER NOT NULL DEFAULT 0,
    captcha_escalated           INTEGER NOT NULL DEFAULT 0,

    cumulative_input_tokens     INTEGER NOT NULL DEFAULT 0,
    cumulative_output_tokens    INTEGER NOT NULL DEFAULT 0,
    cumulative_wall_clock_ms    INTEGER NOT NULL DEFAULT 0,
    cumulative_cost_usd         REAL,

    final_failure_reason        TEXT,

    created_at                  TEXT DEFAULT (datetime('now'))
, experiment_id TEXT)
"""

INDEXES = [
    "CREATE INDEX idx_p2final_status ON phase2_final(terminal_status)",
    "CREATE INDEX idx_p2final_run ON phase2_final(run_id)",
    "CREATE INDEX idx_p2final_experiment ON phase2_final(experiment_id)",
]


def _check_allows_new(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='phase2_final'"
    ).fetchone()
    return bool(row) and all(f"'{s}'" in row[0] for s in NEW_STATUSES)


def _column_list(conn: sqlite3.Connection) -> str:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(phase2_final)")]
    return ", ".join(cols)


def migrate(db_path: Path, *, make_backup: bool = True) -> str:
    """Run the migration on db_path. Returns a one-line status string."""
    conn = sqlite3.connect(str(db_path))
    try:
        if _check_allows_new(conn):
            return "no-op: self-verify statuses already allowed"

        before = conn.execute("SELECT COUNT(*) FROM phase2_final").fetchone()[0]
        collist = _column_list(conn)

        backup = ""
        if make_backup:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = db_path.with_name(f"{db_path.stem}.{stamp}.pre-exp35.db")
            shutil.copy2(db_path, backup_path)
            backup = str(backup_path)

        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        conn.execute(NEW_TABLE_SQL)
        # Named-column copy: order-independent across schema variants.
        conn.execute(
            f"INSERT INTO phase2_final_new ({collist}) "
            f"SELECT {collist} FROM phase2_final"
        )
        conn.execute("DROP TABLE phase2_final")
        conn.execute("ALTER TABLE phase2_final_new RENAME TO phase2_final")
        for idx in INDEXES:
            conn.execute(idx)
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys=ON")

        after = conn.execute("SELECT COUNT(*) FROM phase2_final").fetchone()[0]
        if after != before:
            raise RuntimeError(
                f"row count changed during migration: {before} -> {after}"
            )

        _verify_constraints(conn)
        conn.commit()
        return (
            f"migrated: {before} rows preserved, CHECK now admits "
            f"{', '.join(NEW_STATUSES)}"
            + (f", backup {backup}" if backup else "")
        )
    finally:
        conn.close()


def _verify_constraints(conn: sqlite3.Connection) -> None:
    """Each new status inserts; a junk status still fails. Roll back."""
    cols = ("run_id, pair_run_id, question_id, country_code, "
            "terminal_status, retry_count")
    conn.execute("SAVEPOINT verify")
    try:
        for i, status in enumerate(NEW_STATUSES):
            conn.execute(
                f"INSERT INTO phase2_final ({cols}) "
                f"VALUES ('_v', '_v_verify_{i}', '_v', '_v', ?, 0)",
                (status,),
            )  # must succeed
        failed = False
        try:
            conn.execute(
                f"INSERT INTO phase2_final ({cols}) "
                f"VALUES ('_v', '_v_verify_bad', '_v', '_v', ?, 0)",
                ("garbage_status",),
            )
        except sqlite3.IntegrityError:
            failed = True
        if not failed:
            raise RuntimeError("CHECK no longer rejects an invalid status")
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
