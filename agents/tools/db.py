"""SQLite helpers shared by all agents.

Centralises connection management and prompt-version logging so that
every LLM call writes through one code path. Per D5, every score
links to the exact prompt that produced it.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "odmi.db"


@contextmanager
def connect(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open a connection with WAL mode and foreign keys enabled.

    Always close on exit. Caller is responsible for commit.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def ensure_prompt_version(
    prompt_name: str,
    version: int,
    prompt_text: str,
    description: str = "",
    db_path: Path = DB_PATH,
) -> int:
    """Look up or insert a prompt_versions row. Idempotent.

    Returns the row id, which callers store alongside their run rows so
    every score links to its exact prompt.
    """
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT id FROM prompt_versions WHERE prompt_name = ? AND version = ?",
            (prompt_name, version),
        )
        row = cur.fetchone()
        if row is not None:
            return int(row[0])

        cur = conn.execute(
            "INSERT INTO prompt_versions (prompt_name, version, prompt_text, description) "
            "VALUES (?, ?, ?, ?)",
            (prompt_name, version, prompt_text, description),
        )
        conn.commit()
        return int(cur.lastrowid)
