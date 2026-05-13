"""Mirror a hand-marks CSV into the SQLite `hand_marks` table.

The CSV is canonical (human-edited); the DB is the join surface for
swarm analysis. Per D9 a hand-mark is locked only when committed. This
script refuses to sync a CSV with uncommitted changes, then records the
SHA of the commit that last touched the file in `locked_by_commit`.

Idempotent. Re-running upserts by (question_id, country_code,
marked_at). If the CSV row's `marked_at` matches an existing row for
the same (question, country), the row is updated in place. Otherwise a
new row is inserted (this is how D9 supports re-marks, per
PROTOCOL.md).

    uv run python scripts/sync_hand_marks.py data/hand_marks/france_handmarks.csv
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "odmi.db"


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), *args],
        text=True,
    ).strip()


def file_has_uncommitted_changes(path: Path) -> bool:
    rel = path.resolve().relative_to(REPO_ROOT)
    status = git("status", "--porcelain", "--", str(rel))
    return bool(status.strip())


def last_commit_for(path: Path) -> str | None:
    rel = path.resolve().relative_to(REPO_ROOT)
    sha = git("log", "-1", "--pretty=format:%H", "--", str(rel))
    return sha or None


def parse_marked_at(s: str) -> str:
    return s.strip()


def sync(csv_path: Path) -> None:
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    if file_has_uncommitted_changes(csv_path):
        raise SystemExit(
            f"Refusing to sync {csv_path.name}: it has uncommitted changes. "
            "Commit it first (D9 lock rule)."
        )

    sha = last_commit_for(csv_path)
    if not sha:
        raise SystemExit(
            f"No commit found that touches {csv_path.name}. "
            "Add and commit it before syncing."
        )

    rows = list(csv.DictReader(csv_path.open()))
    if not rows:
        print("CSV is empty (only header). Nothing to sync.")
        return

    inserted = 0
    updated = 0
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        for r in rows:
            existing = cur.execute(
                """SELECT id FROM hand_marks
                   WHERE question_id = ? AND country_code = ?
                     AND marked_at = ?""",
                (r["question_id"], r["country"], parse_marked_at(r["marked_at"])),
            ).fetchone()
            payload = (
                r["question_id"],
                r["country"],
                int(r["evidence_score"]),
                r["evidence_justification"],
                int(r["determinism_score"]),
                r["determinism_justification"],
                int(r["complexity_score"]),
                r["complexity_justification"],
                int(r["composite_score"]),
                r["tier"],
                r.get("search_queries") or None,
                r.get("sources_found") or None,
                r.get("answer_obtained") or None,
                r["marker"],
                parse_marked_at(r["marked_at"]),
                sha,
                r.get("notes") or None,
            )
            if existing:
                cur.execute(
                    """UPDATE hand_marks SET
                         evidence_score = ?, evidence_justification = ?,
                         determinism_score = ?, determinism_justification = ?,
                         complexity_score = ?, complexity_justification = ?,
                         composite_score = ?, tier = ?,
                         search_queries = ?, sources_found = ?,
                         answer_obtained = ?, marker = ?, marked_at = ?,
                         locked_by_commit = ?, notes = ?
                       WHERE id = ?""",
                    payload[2:] + (existing[0],),
                )
                updated += 1
            else:
                cur.execute(
                    """INSERT INTO hand_marks
                       (question_id, country_code,
                        evidence_score, evidence_justification,
                        determinism_score, determinism_justification,
                        complexity_score, complexity_justification,
                        composite_score, tier,
                        search_queries, sources_found, answer_obtained,
                        marker, marked_at, locked_by_commit, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    payload,
                )
                inserted += 1
        conn.commit()

    print(
        f"Synced {csv_path.name}: inserted {inserted}, updated {updated}. "
        f"locked_by_commit = {sha[:8]}."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", type=Path)
    args = ap.parse_args()
    sync(args.csv_path)


if __name__ == "__main__":
    main()
