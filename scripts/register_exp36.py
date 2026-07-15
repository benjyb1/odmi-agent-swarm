"""Register the EXP-36 frozen headline run in the `experiments` table (R1).

`run_experiments.py` hard-fails preflight on any experiment_id absent from this
table, so the headline cannot dispatch until this row exists. Idempotent: a
second run leaves the row unchanged. Run against the DB the dispatch will
actually use (a fresh, purged copy of the canonical DB per the runbook), not a
worktree copy.

  uv run python scripts/register_exp36.py --db data/odmi.db
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

EXPERIMENT_ID = "exp36_frozen_headline"
NAME = (
    "EXP-36 Frozen headline run, D47 held-out 8 "
    "(discards EXP-31 per the 2026-07-13 fresh pre-registration, D64)"
)
DESCRIPTION = (
    "Single frozen production configuration on the D47 held-out eight "
    "(BA MK ME BG FI HR SE BE), ~1,144 (question, country) pairs, dispatched as "
    "eight per-country sub-batches (condition_label = country code), stratum B "
    "first. Models claude-sonnet-4-6 for researcher / verifier / adjudicator / "
    "picker / query-gen (D59); search_strategy wide_only (EXP-34); DIY-only "
    "(D43); results-per-query 5 (EXP-18); verifier counter-search always "
    "(EXP-19); no chaining (EXP-20); full Researcher prompt, neg_licence off "
    "(D50); trio pipeline (D54); abstention floor 0.65 (D37); no_cache (leak "
    "guard, R9). No arms and no adoption rule: this is the single reported "
    "headline. Endpoints: balance-aware per-class recall with Wilson intervals, "
    "balanced accuracy, Youden's J vs the majority baseline; three-outcome "
    "commit-accuracy / coverage / negative-gold FPR with a D37 risk-coverage "
    "sweep; stratified by ODMI dimension, resource stratum, assessor decision "
    "(confirm / complement / change) and answer shape; ODMI disagreements "
    "reported as a D22 staleness band; FM-14 fingerprint audit post-run. Prior "
    "held-out exposure (exp21 partial, expC_held) voided and disclosed (D57). "
    "Pre-registration: docs/EXPERIMENTS_EXP36_PREREG.md."
)
CONDITIONS = (
    "Single frozen production configuration; claude-sonnet-4-6 all roles + "
    "picker; search_strategy=wide_only; no_cache; eight arms, "
    "condition_label = country code (FI SE BE HR BA MK ME BG); no adoption rule."
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="DB the dispatch will use.")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: {db} does not exist")
        return 2

    conn = sqlite3.connect(str(db))
    try:
        existing = conn.execute(
            "SELECT experiment_id FROM experiments WHERE experiment_id = ?",
            (EXPERIMENT_ID,),
        ).fetchone()
        if existing:
            print(f"{EXPERIMENT_ID} already registered; nothing to do.")
            return 0
        conn.execute(
            "INSERT INTO experiments (experiment_id, name, description, conditions) "
            "VALUES (?, ?, ?, ?)",
            (EXPERIMENT_ID, NAME, DESCRIPTION, CONDITIONS),
        )
        conn.commit()
        print(f"Registered {EXPERIMENT_ID} in {db}.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
