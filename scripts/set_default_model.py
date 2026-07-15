#!/usr/bin/env python3
"""Set the per-role default model in the `model_defaults` table.

The dispatcher reads `model_defaults` (via `_read_default`) to pick the model
for each agent role; the DB row wins over the code fallback in
`dispatch_subtrios.py`. So a model default change is only real once this table
is updated, not just the `DEFAULT_MODEL` constant.

Idempotent. Prints the before/after rows. Defaults to the repo's canonical
`data/odmi.db`; pass `--db` for a worktree copy.

    uv run python scripts/set_default_model.py --model claude-sonnet-4-6
    uv run python scripts/set_default_model.py --model claude-sonnet-4-6 --db /path/to/odmi.db

Used to set the canonical model default to Sonnet 4.6 (the model every June
dev experiment ran on), per the 2026-07-09 decision (D59).
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROLES = ("researcher", "verifier", "adjudicator")
DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "odmi.db"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="model id to set for all roles")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to the SQLite DB")
    ap.add_argument("--updated-by", default="revert-sonnet46",
                    help="audit tag written to updated_by")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    try:
        before = con.execute(
            "SELECT agent_role, model FROM model_defaults ORDER BY agent_role"
        ).fetchall()
        print(f"before ({args.db}):", dict(before))
        for role in ROLES:
            con.execute(
                "INSERT OR REPLACE INTO model_defaults "
                "(agent_role, model, updated_at, updated_by) "
                "VALUES (?, ?, datetime('now'), ?)",
                (role, args.model, args.updated_by),
            )
        con.commit()
        after = con.execute(
            "SELECT agent_role, model FROM model_defaults ORDER BY agent_role"
        ).fetchall()
        print("after: ", dict(after))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
