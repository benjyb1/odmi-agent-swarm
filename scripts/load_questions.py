"""Load parsed questions from JSON into the SQLite `questions` table.

Idempotent. Re-runs replace each row by `question_id`. Run after
`parse_questions.py` produces / refreshes `odmi_2025_questions.json`.

    uv run python scripts/load_questions.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "odmi.db"
JSON_PATH = REPO_ROOT / "data" / "questions" / "odmi_2025_questions.json"


def main() -> None:
    if not JSON_PATH.exists():
        raise SystemExit(
            f"Question JSON not found at {JSON_PATH}. "
            "Run scripts/parse_questions.py first."
        )

    records = json.loads(JSON_PATH.read_text())
    if not isinstance(records, list):
        raise SystemExit("Expected a list at top level of the question JSON.")

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        inserted = 0
        updated = 0
        for r in records:
            existing = cur.execute(
                "SELECT 1 FROM questions WHERE question_id = ?",
                (r["question_id"],),
            ).fetchone()
            if existing:
                cur.execute(
                    """UPDATE questions
                       SET dimension = ?, indicator = ?, question_text = ?,
                           response_scoring = ?
                       WHERE question_id = ?""",
                    (
                        r["dimension"],
                        r["indicator"],
                        r["question_text"],
                        r.get("response_scoring") or None,
                        r["question_id"],
                    ),
                )
                updated += 1
            else:
                cur.execute(
                    """INSERT INTO questions
                       (question_id, dimension, indicator, question_text,
                        response_scoring, in_subset)
                       VALUES (?, ?, ?, ?, ?, 0)""",
                    (
                        r["question_id"],
                        r["dimension"],
                        r["indicator"],
                        r["question_text"],
                        r.get("response_scoring") or None,
                    ),
                )
                inserted += 1
        conn.commit()

    total = cur.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    print(f"Inserted {inserted}, updated {updated}. Table now has {total} rows.")


if __name__ == "__main__":
    main()
