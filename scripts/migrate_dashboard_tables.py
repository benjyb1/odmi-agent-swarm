"""Add the three dashboard tables to an existing odmi.db without wiping it.

Idempotent. Run once after pulling the dashboard branch:

    uv run python scripts/migrate_dashboard_tables.py

Existing data (questions, hand_marks, phase2_*) is left untouched.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "odmi.db"

MIGRATION = """
CREATE TABLE IF NOT EXISTS subtrio_status (
    subtrio_id              TEXT PRIMARY KEY,
    batch_id                TEXT NOT NULL,
    question_id             TEXT NOT NULL,
    country_code            TEXT NOT NULL,
    stage                   TEXT,
    substage                TEXT,
    retry_count             INTEGER DEFAULT 0,
    started_at              TEXT,
    updated_at              TEXT,
    ended_at                TEXT,
    final_verdict           TEXT,
    cumulative_cost_usd     REAL,
    last_message            TEXT,
    process_pid             INTEGER,
    researcher_model        TEXT,
    verifier_model          TEXT,
    adjudicator_model       TEXT,
    verifier_strategy       TEXT,
    final_failure_reason    TEXT,
    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS claude_usage_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    model               TEXT NOT NULL,
    input_tokens        INTEGER NOT NULL,
    output_tokens       INTEGER NOT NULL,
    estimated_cost_usd  REAL,
    rate_limited        INTEGER DEFAULT 0,
    context             TEXT,
    subtrio_id          TEXT
);

CREATE TABLE IF NOT EXISTS model_defaults (
    agent_role          TEXT PRIMARY KEY CHECK (agent_role IN (
                            'researcher', 'verifier', 'adjudicator'
                        )),
    model               TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    updated_by          TEXT
);

CREATE INDEX IF NOT EXISTS idx_subtrio_status_batch
    ON subtrio_status(batch_id);
CREATE INDEX IF NOT EXISTS idx_subtrio_status_stage
    ON subtrio_status(stage);
CREATE INDEX IF NOT EXISTS idx_subtrio_status_question_country
    ON subtrio_status(question_id, country_code);
CREATE INDEX IF NOT EXISTS idx_claude_usage_ts
    ON claude_usage_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_claude_usage_subtrio
    ON claude_usage_log(subtrio_id);
"""

SEED_DEFAULTS = """
INSERT OR IGNORE INTO model_defaults (agent_role, model, updated_at, updated_by)
VALUES
    ('researcher',  'claude-sonnet-4-6', datetime('now'), 'migration'),
    ('verifier',    'claude-sonnet-4-6', datetime('now'), 'migration'),
    ('adjudicator', 'claude-sonnet-4-6', datetime('now'), 'migration');
"""


def migrate() -> None:
    if not DB_PATH.exists():
        sys.exit(
            f"Database not found at {DB_PATH}. "
            f"Run scripts/setup_sqlite.py first."
        )
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(MIGRATION)
    conn.executescript(SEED_DEFAULTS)
    conn.commit()

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('subtrio_status', 'claude_usage_log', 'model_defaults')"
    )]
    defaults_count = conn.execute(
        "SELECT COUNT(*) FROM model_defaults"
    ).fetchone()[0]
    conn.close()

    print(f"Migration complete on {DB_PATH}")
    print(f"  New tables present: {', '.join(sorted(tables))}")
    print(f"  model_defaults rows: {defaults_count}")


if __name__ == "__main__":
    migrate()
