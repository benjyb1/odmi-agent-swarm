"""Add the two D30 catalogue-metrics tables to an existing odmi.db.

Idempotent. Run once after pulling the catalogue-tool change:

    uv run python scripts/migrate_catalogue_tables.py

Existing data is left untouched. These tables hold the committed
reproducibility receipt for the deterministic catalogue tool; the raw
harvest itself lives on disk under data/catalogue_snapshots/ (gitignored).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "odmi.db"

MIGRATION = """
CREATE TABLE IF NOT EXISTS catalogue_snapshots (
    snapshot_id         TEXT PRIMARY KEY,
    country_code        TEXT NOT NULL,
    harvest_route       TEXT NOT NULL,
    source_endpoint     TEXT NOT NULL,
    fetched_at          TEXT NOT NULL,
    dataset_count       INTEGER,
    page_count          INTEGER,
    content_sha256      TEXT,
    cache_path          TEXT,
    partial             INTEGER DEFAULT 0,
    notes               TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS catalogue_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id         TEXT,
    question_id         TEXT NOT NULL,
    country_code        TEXT NOT NULL,
    metric_function     TEXT NOT NULL,
    raw_value           REAL,
    numerator           INTEGER,
    denominator         INTEGER,
    band_label          TEXT,
    breakdown           TEXT,
    computed_at         TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cat_snapshots_country
    ON catalogue_snapshots(country_code);
CREATE INDEX IF NOT EXISTS idx_cat_metrics_question_country
    ON catalogue_metrics(question_id, country_code);
CREATE INDEX IF NOT EXISTS idx_cat_metrics_snapshot
    ON catalogue_metrics(snapshot_id);
"""


def migrate() -> None:
    if not DB_PATH.exists():
        sys.exit(
            f"Database not found at {DB_PATH}. Run scripts/setup_sqlite.py first."
        )
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(MIGRATION)
    conn.commit()

    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('catalogue_snapshots', 'catalogue_metrics')"
        )
    ]
    conn.close()
    print(f"Migration complete on {DB_PATH}")
    print(f"  New tables present: {', '.join(sorted(tables))}")


if __name__ == "__main__":
    migrate()
