"""Add search_snippets column to phase2_researcher_runs.

Idempotent. Guards with PRAGMA table_info before attempting the ALTER
TABLE, so re-running is safe.

    uv run python scripts/migrate_search_snippets.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "odmi.db"


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def main() -> int:
    if not DB_PATH.exists():
        sys.exit(f"Database not found at {DB_PATH}.")

    conn = sqlite3.connect(DB_PATH)
    try:
        if _column_exists(conn, "phase2_researcher_runs", "search_snippets"):
            print("search_snippets column already exists — nothing to do.")
        else:
            conn.execute(
                "ALTER TABLE phase2_researcher_runs "
                "ADD COLUMN search_snippets TEXT"
            )
            conn.commit()
            print("Added search_snippets column to phase2_researcher_runs.")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
