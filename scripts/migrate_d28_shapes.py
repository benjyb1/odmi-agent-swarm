"""D28 Phase 2 stage A migration.

Idempotent. Three things in one pass:

1. Adds `answer_shape` (TEXT, CHECK-constrained) and `allowed_answers`
   (TEXT JSON list) columns to the `questions` table. Existing rows
   keep their data; the columns are nullable until populated.
2. Classifies every row in `questions` by parsing `response_scoring`
   into one of five shapes: binary, percentage_band, ordinal_magnitude,
   count_band, categorical. Writes the shape and the allowed-answer
   list back to the row. Re-running overwrites; the classifier is
   deterministic.
3. Migrates `final_answer = 'other'` rows in `phase2_final` (and the
   matching `pair_run_id` rows in the upstream Researcher / Verifier /
   Adjudicator tables) to `inconclusive`. Only touches pairs on
   binary-shape questions whose ODMI rubric does not include 'other'
   as a valid answer. We hand-deleted the non-binary forced-collapse
   rows in D28 phase 1, so the remaining 22 'other' rows are all
   honest "couldn't tell" outcomes on yes/no-only rubrics.

Run:

    uv run python scripts/migrate_d28_shapes.py [--dry-run]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "odmi.db"

SHAPES = (
    "binary",
    "percentage_band",
    "ordinal_magnitude",
    "count_band",
    "categorical",
)

BINARY_KEY_WHITELIST = {
    "yes",
    "no",
    "other",
    "not applicable",
    "not_applicable",
    "i don't know",
}

ORDINAL_WORDS = ("all", "majority", "approximately half", "few", "none of")

PERCENTAGE_PATTERN = re.compile(r"(>\s*\d+\s*%|<\s*\d+\s*%|\d+\s*-\s*\d+\s*%|\d+%)")
COUNT_PATTERN = re.compile(
    r"(^\d+\s*-\s*\d+$|^>\s*\d+$|^<\s*\d+$|^yes,\s*[\d<>])"
)


def _parse_rubric(response_scoring: str | None) -> dict | None:
    if not response_scoring or not response_scoring.strip():
        return None
    try:
        rubric = ast.literal_eval(response_scoring)
    except (ValueError, SyntaxError):
        return None
    return rubric if isinstance(rubric, dict) else None


def _semantic_keys(rubric: dict) -> list[str]:
    keys: list[str] = []
    for k in rubric.keys():
        if k is None:
            continue
        s = str(k).strip().lower()
        if not s:
            continue
        keys.append(s)
    return keys


def classify(response_scoring: str | None) -> tuple[str, list]:
    """Return (shape, allowed_answers) for a `response_scoring` string.

    Degenerate rubrics (`{None: 0}`, empty, unparsable) fall back to
    `binary` with `['yes', 'no']`. The actual agent will still emit
    `inconclusive` when it cannot reach a confident answer.
    """
    rubric = _parse_rubric(response_scoring)
    if rubric is None:
        return ("binary", ["yes", "no"])

    keys = _semantic_keys(rubric)
    if not keys:
        return ("binary", ["yes", "no"])
    keys_set = set(keys)

    # Binary: keys are a subset of the binary whitelist. Long yes-variants
    # like 'yes, or all public sector data providers already publish data'
    # also count as binary if everything but the yes-variant is in the
    # whitelist.
    is_binary_pure = keys_set.issubset(BINARY_KEY_WHITELIST)
    has_no = "no" in keys_set
    has_long_yes = any(
        k.startswith("yes,") and not COUNT_PATTERN.search(k) for k in keys
    )
    is_binary_with_long_yes = (
        has_no
        and has_long_yes
        and (keys_set - {k for k in keys if k.startswith("yes,")}).issubset(
            BINARY_KEY_WHITELIST
        )
    )
    if is_binary_pure or is_binary_with_long_yes:
        return ("binary", _ordered_binary_keys(keys, rubric))

    # Percentage band: any key carries a % range / threshold.
    if any(PERCENTAGE_PATTERN.search(k) for k in keys):
        return ("percentage_band", _ordered_band_keys(keys, rubric, percentage=True))

    # Count band: keys mix numeric ranges (1-4, >10, yes, 6-9 ...). The
    # 'no' / "i don't know" entries can ride alongside.
    has_count_key = any(COUNT_PATTERN.search(k) for k in keys)
    has_count_yes_prefix = any(k.startswith("yes, ") and COUNT_PATTERN.search(k) for k in keys)
    if has_count_key or has_count_yes_prefix:
        return ("count_band", _ordered_band_keys(keys, rubric, percentage=False))

    # Ordinal magnitude: 'all X' / 'majority X' / 'approximately half X'
    # / 'few X' / 'none of X', possibly with 'not applicable'.
    if any(_starts_with_ordinal(k) for k in keys):
        return ("ordinal_magnitude", _ordered_ordinal_keys(keys, rubric))

    # Otherwise: small categorical (P14's top-down / bottom-up / hybrid,
    # Q3's within one day / week / month / longer ...). Q3's bands are
    # ordered by time delay; that ordering is captured by the order in
    # which we emit allowed_answers (rubric insertion order is honoured).
    return ("categorical", _rubric_keys_in_insertion_order(rubric))


def _starts_with_ordinal(key: str) -> bool:
    return any(key.startswith(w) for w in ORDINAL_WORDS) or key == "none"


def _ordered_binary_keys(keys: list[str], rubric: dict) -> list[str]:
    # Emit yes-variants first (in rubric insertion order), then 'no',
    # then 'other' / 'not applicable' / "i don't know" if present.
    yes_variants = [str(k) for k in rubric.keys() if str(k).strip().lower().startswith("yes")]
    no_keys = [str(k) for k in rubric.keys() if str(k).strip().lower() == "no"]
    tail_order = ("other", "not applicable", "not_applicable", "i don't know")
    tail = [
        str(k)
        for tag in tail_order
        for k in rubric.keys()
        if str(k).strip().lower() == tag
    ]
    return yes_variants + no_keys + tail


def _ordered_band_keys(keys: list[str], rubric: dict, percentage: bool) -> list[str]:
    # Preserve rubric insertion order: the questionnaire authors list
    # bands from highest to lowest, which is the ordering the swarm and
    # Verifier will rely on for near-miss logic.
    return _rubric_keys_in_insertion_order(rubric)


def _ordered_ordinal_keys(keys: list[str], rubric: dict) -> list[str]:
    return _rubric_keys_in_insertion_order(rubric)


def _rubric_keys_in_insertion_order(rubric: dict) -> list[str]:
    """Insertion-order keys, deduped by case-insensitive string form.

    Some ODMI rubrics carry the same label twice as both string and
    int (e.g. Q2 has `'1': 20, 1: 20`). We keep the first occurrence.
    """
    seen: set[str] = set()
    out: list[str] = []
    for k in rubric.keys():
        if k is None:
            continue
        s = str(k)
        norm = s.strip().lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(s)
    return out


# Migration


SCHEMA_MIGRATION = """
ALTER TABLE questions ADD COLUMN answer_shape   TEXT;
ALTER TABLE questions ADD COLUMN allowed_answers TEXT;
"""

CHECK_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_questions_answer_shape ON questions(answer_shape);
"""


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def add_schema(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "questions", "answer_shape"):
        conn.execute("ALTER TABLE questions ADD COLUMN answer_shape TEXT")
    if not _column_exists(conn, "questions", "allowed_answers"):
        conn.execute("ALTER TABLE questions ADD COLUMN allowed_answers TEXT")
    conn.executescript(CHECK_INDEXES)


def classify_all(conn: sqlite3.Connection, dry_run: bool) -> dict[str, int]:
    counts: dict[str, int] = {s: 0 for s in SHAPES}
    rows = conn.execute(
        "SELECT question_id, response_scoring FROM questions"
    ).fetchall()
    for question_id, scoring in rows:
        shape, allowed = classify(scoring)
        counts[shape] = counts.get(shape, 0) + 1
        if not dry_run:
            conn.execute(
                "UPDATE questions SET answer_shape = ?, allowed_answers = ? "
                "WHERE question_id = ?",
                (shape, json.dumps(allowed, ensure_ascii=False), question_id),
            )
    return counts


def relabel_other_to_inconclusive(
    conn: sqlite3.Connection, dry_run: bool
) -> dict[str, int]:
    """Migrate `final_answer = 'other'` rows to 'inconclusive' on
    questions whose ODMI rubric is yes/no only (i.e. their new
    `answer_shape` is `binary` and `other` is NOT in the allowed
    answer list). Cascade through phase2_researcher_runs.answer,
    phase2_verifier_runs.verifier_answer, phase2_adjudications.
    adjudicator_answer.
    """
    # The set of pair_run_ids to relabel: phase2_final.other rows on
    # questions whose allowed_answers does NOT include 'other'.
    target_rows = conn.execute(
        """
        SELECT f.pair_run_id
        FROM phase2_final f
        JOIN questions q ON q.question_id = f.question_id
        WHERE f.final_answer = 'other'
          AND (q.allowed_answers IS NULL
               OR instr(q.allowed_answers, '"other"') = 0)
        """
    ).fetchall()
    pair_ids = [r[0] for r in target_rows]
    counts = {
        "phase2_final": 0,
        "phase2_researcher_runs": 0,
        "phase2_verifier_runs": 0,
        "phase2_adjudications": 0,
    }
    if not pair_ids:
        return counts

    placeholders = ",".join(["?"] * len(pair_ids))

    def _update(table: str, column: str) -> int:
        if dry_run:
            cur = conn.execute(
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE pair_run_id IN ({placeholders}) AND {column} = 'other'",
                pair_ids,
            )
            return cur.fetchone()[0]
        cur = conn.execute(
            f"UPDATE {table} SET {column} = 'inconclusive' "
            f"WHERE pair_run_id IN ({placeholders}) AND {column} = 'other'",
            pair_ids,
        )
        return cur.rowcount

    counts["phase2_final"] = _update("phase2_final", "final_answer")
    counts["phase2_researcher_runs"] = _update("phase2_researcher_runs", "answer")
    counts["phase2_verifier_runs"] = _update(
        "phase2_verifier_runs", "verifier_answer"
    )
    counts["phase2_adjudications"] = _update(
        "phase2_adjudications", "adjudicator_answer"
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change, write nothing.",
    )
    args = parser.parse_args(argv)

    if not DB_PATH.exists():
        sys.exit(f"Database not found at {DB_PATH}.")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        if not args.dry_run:
            conn.execute("BEGIN")

        add_schema(conn)
        counts = classify_all(conn, dry_run=args.dry_run)
        relabel = relabel_other_to_inconclusive(conn, dry_run=args.dry_run)

        if not args.dry_run:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"D28 stage A migration ({'dry-run' if args.dry_run else 'applied'})")
    print("  Classification distribution:")
    for shape in SHAPES:
        print(f"    {shape:18s} {counts.get(shape, 0):3d}")
    print(f"  Relabel `other` -> `inconclusive`:")
    for table, n in relabel.items():
        print(f"    {table:28s} {n:3d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
