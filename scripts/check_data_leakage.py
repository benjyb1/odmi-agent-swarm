"""Audit `data/odmi.db` for any swarm row that cites a forbidden source.

The swarm is forbidden from using ODMI's own publications, the EU Data
Portal, archive mirrors of those, and any URL whose path advertises an
"open-data-maturity" or "odmi" topic. See SPEC D24.

This script is the last line of defence. The search, fetch, validator,
and prompt layers all enforce the deny-list before a forbidden URL can
land in a row; if anything slips through it shows up here. Exit code 0
means clean; exit code 1 means one or more rows violated the rule.

Usage
-----
    uv run python scripts/check_data_leakage.py

Optional flags:
    --quiet         only print the summary line
    --csv PATH      write violations to a CSV at PATH
    --purge         delete every pair_run row that produced a violation
                    (cascades through phase2_researcher_runs,
                    phase2_verifier_runs, phase2_final, and subtrio_status).
                    Off by default. Use with care: deleted rows cannot be
                    recovered without a DB backup.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.tools.blocked_domains import blocked_reason, is_blocked  # noqa: E402

DB_PATH = REPO_ROOT / "data" / "odmi.db"


_QUERIES = [
    # (table, label, sql returning rows of (pair_run_id, url))
    (
        "phase2_researcher_runs",
        "researcher.source_url",
        "SELECT pair_run_id, source_url FROM phase2_researcher_runs "
        "WHERE source_url IS NOT NULL AND TRIM(source_url) <> ''",
    ),
    (
        "phase2_verifier_runs",
        "verifier.counter_source_url",
        "SELECT pair_run_id, counter_source_url FROM phase2_verifier_runs "
        "WHERE counter_source_url IS NOT NULL AND TRIM(counter_source_url) <> ''",
    ),
    (
        "phase2_final",
        "final.final_source_url",
        "SELECT pair_run_id, final_source_url FROM phase2_final "
        "WHERE final_source_url IS NOT NULL AND TRIM(final_source_url) <> ''",
    ),
]


def _scan(conn: sqlite3.Connection) -> list[tuple[str, str, str, str, str]]:
    """Return rows of (table, column, pair_run_id, url, blocked_reason)."""
    violations: list[tuple[str, str, str, str, str]] = []
    for table, column, sql in _QUERIES:
        try:
            cur = conn.execute(sql)
        except sqlite3.OperationalError as exc:
            # Table may not exist on a fresh DB. Skip with a note.
            print(f"  (skipped {table}: {exc})")
            continue
        for pair_run_id, url in cur.fetchall():
            if is_blocked(url):
                violations.append(
                    (table, column, str(pair_run_id), url, blocked_reason(url) or "?")
                )
    return violations


_PURGE_TABLES = (
    "phase2_researcher_runs",
    "phase2_verifier_runs",
    "phase2_adjudicator_runs",
    "phase2_final",
    "subtrio_status",
    "pair_runs",
)


def _purge_pairs(conn: sqlite3.Connection, pair_ids: set[str]) -> int:
    """Delete every row across the swarm tables for the given pairs.

    Returns the total number of rows deleted across all tables. Safe to
    call on a DB whose schema lacks some of the listed tables.
    """
    if not pair_ids:
        return 0
    total = 0
    placeholders = ",".join("?" for _ in pair_ids)
    ids = list(pair_ids)
    for table in _PURGE_TABLES:
        try:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE pair_run_id IN ({placeholders})", ids
            )
        except sqlite3.OperationalError:
            # Table may not exist on a fresh DB or older schema. Skip.
            continue
        total += cur.rowcount or 0
    conn.commit()
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--csv", type=str, default=None)
    parser.add_argument("--purge", action="store_true",
                        help="Delete tainted pair_run rows (irreversible).")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}")
        return 2

    conn = sqlite3.connect(DB_PATH)
    try:
        violations = _scan(conn)

        if args.csv:
            out_path = Path(args.csv)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["table", "column", "pair_run_id", "url", "blocked_reason"])
                for row in violations:
                    w.writerow(row)

        if not violations:
            print("Data leakage audit: clean. No forbidden URLs found in swarm rows.")
            return 0

        if not args.quiet:
            print(f"Data leakage audit: {len(violations)} violation(s):")
            for table, column, pair_id, url, reason in violations:
                print(f"  [{table}.{column}] pair={pair_id} reason={reason}")
                print(f"      {url}")
        else:
            print(f"Data leakage audit: {len(violations)} violation(s).")

        if args.purge:
            tainted = {row[2] for row in violations}
            n = _purge_pairs(conn, tainted)
            print(
                f"--purge: removed {n} rows across {len(tainted)} pair_run_id(s)."
            )
    finally:
        conn.close()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
