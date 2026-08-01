#!/usr/bin/env python3
"""Rename the abstention terminal statuses `escalated_*` to `abstained_*` (D52).

The swarm has no human-review stage: a pair either commits an answer or
abstains. The old `escalated_captcha` / `escalated_adjudicator` terminal
statuses implied a handoff to a human queue that was never built, so they
are renamed to `abstained_captcha` / `abstained_adjudicator`. This
migration does three things:

1. Widens the phase2_final.terminal_status CHECK constraint to allow the
   two `abstained_*` values. SQLite cannot ALTER a CHECK, so the table is
   rebuilt with the new constraint, preserving every row, index and the
   physical column order. The `escalated_*` values are retained in the
   CHECK as legacy so the rebuild never rejects a pre-rename row.
2. Updates phase2_final rows: escalated_captcha -> abstained_captcha and
   escalated_adjudicator -> abstained_adjudicator.
3. Updates the free-text subtrio_status.final_verdict mirror the same way
   (no CHECK there, so a plain UPDATE).

The row copy names every column explicitly, so it survives the
experiment_id/created_at column-order difference between a freshly
setup database and one an earlier migration rebuilt.

The migration is idempotent: if the CHECK already admits `abstained_*`
and no `escalated_*` rows remain it is a no-op. It backs the database up
first and verifies row parity, the new and old constraint behaviour, and
that no legacy rows survive before committing.

Usage:
    uv run python scripts/migrate_terminal_status_to_abstained.py [path/to/db]
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "odmi.db"
RENAMES = {
    "escalated_captcha": "abstained_captcha",
    "escalated_adjudicator": "abstained_adjudicator",
}

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
                                    'abstained_captcha',
                                    'abstained_adjudicator',
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


def _check_allows_abstained(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='phase2_final'"
    ).fetchone()
    return bool(row) and "'abstained_adjudicator'" in row[0]


def _legacy_rows(conn: sqlite3.Connection) -> int:
    placeholders = ",".join("?" for _ in RENAMES)
    return conn.execute(
        f"SELECT COUNT(*) FROM phase2_final WHERE terminal_status IN ({placeholders})",
        tuple(RENAMES),
    ).fetchone()[0]


def _column_list(conn: sqlite3.Connection) -> str:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(phase2_final)")]
    return ", ".join(cols)


def migrate(db_path: Path, *, make_backup: bool = True) -> str:
    """Run the migration on db_path. Returns a one-line status string."""
    conn = sqlite3.connect(str(db_path))
    try:
        if _check_allows_abstained(conn) and _legacy_rows(conn) == 0:
            return "no-op: abstained_* already allowed, no escalated_* rows"

        before = conn.execute("SELECT COUNT(*) FROM phase2_final").fetchone()[0]
        legacy = _legacy_rows(conn)
        collist = _column_list(conn)

        backup = ""
        if make_backup:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = db_path.with_name(f"{db_path.stem}.{stamp}.pre-d52.db")
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
        # Convert the legacy values now the CHECK admits both names.
        for old, new in RENAMES.items():
            conn.execute(
                "UPDATE phase2_final SET terminal_status = ? WHERE terminal_status = ?",
                (new, old),
            )
        # subtrio_status.final_verdict mirrors terminal_status as free text.
        for old, new in RENAMES.items():
            conn.execute(
                "UPDATE subtrio_status SET final_verdict = ? WHERE final_verdict = ?",
                (new, old),
            )
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys=ON")

        after = conn.execute("SELECT COUNT(*) FROM phase2_final").fetchone()[0]
        if after != before:
            raise RuntimeError(
                f"row count changed during migration: {before} -> {after}"
            )
        if _legacy_rows(conn) != 0:
            raise RuntimeError("legacy escalated_* rows survived the migration")

        _verify_constraints(conn)
        conn.commit()
        return (
            f"migrated: {before} rows preserved, {legacy} escalated_* -> "
            f"abstained_*, CHECK now admits abstained_*"
            + (f", backup {backup}" if backup else "")
        )
    finally:
        conn.close()


def _verify_constraints(conn: sqlite3.Connection) -> None:
    """`abstained_adjudicator` inserts; a junk status still fails. Roll back."""
    cols = ("run_id, pair_run_id, question_id, country_code, "
            "terminal_status, retry_count")
    vals = "('_v','_v_verify','_v','_v',?,0)"
    conn.execute("SAVEPOINT verify")
    try:
        conn.execute(
            f"INSERT INTO phase2_final ({cols}) VALUES {vals}",
            ("abstained_adjudicator",),
        )  # must succeed
        failed = False
        try:
            conn.execute(
                f"INSERT INTO phase2_final ({cols}) VALUES {vals}",
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
