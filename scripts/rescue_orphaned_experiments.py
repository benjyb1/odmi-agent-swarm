"""Rescue experiment rows that exist only in worktree databases.

`data/odmi.db` is git-tracked and every worktree carries its own diverging
copy, so a run dispatched inside a worktree writes its rows there and nowhere
else. If that worktree is pruned, the rows go with it. This has already
happened once: the EXP-40 cooperative arm was dispatched live, its worktree is
gone, and no database on the machine holds a single row of it. Its result
survives only as an aggregate JSON that nobody can now verify or recompute.

This script finds every experiment cited by the project that has rows in some
worktree database but none in the canonical one, and copies them somewhere they
will survive. It is read-only on every source.

Two modes:

    --out data/rescued_experiments.db   (default)
        Write a standalone SQLite file holding just the orphaned experiments.
        Safe: it never opens the canonical database for writing, and it is a
        small artefact that git can hold without a 650 MB binary diff.

    --merge-into data/odmi.db
        Insert the rescued rows straight into the canonical database. Run this
        deliberately, against the canonical checkout, never from inside a
        worktree (see the DB divergence note above), and with no other window
        dispatching at the time.

Row identity: `phase2_final.id` is a per-database autoincrement and collides
across copies, so it is never carried over. `pair_run_id` is a UUID and is
globally unique, so it is the key that stitches a pair to its Researcher,
Verifier and Adjudicator trail. Rows already present in the destination (by
pair_run_id) are skipped, which makes the script idempotent.

Usage:
    uv run python scripts/rescue_orphaned_experiments.py --dry-run
    uv run python scripts/rescue_orphaned_experiments.py
    uv run python scripts/rescue_orphaned_experiments.py --merge-into data/odmi.db
"""

from __future__ import annotations

import argparse
import glob
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path("/Users/benjyb/Desktop/MscProject")
CANONICAL = PROJECT_ROOT / "data" / "odmi.db"
WORKTREE_GLOB = str(PROJECT_ROOT / ".claude" / "worktrees" / "*" / "data" / "odmi.db")

# Tables that carry experiment rows, in insert order (parents before children).
TABLES = (
    "experiments",
    "phase2_final",
    "phase2_researcher_runs",
    "phase2_verifier_runs",
    "phase2_adjudications",
    "subtrio_status",
)

# Column used to detect an already-present row, per table. phase2_final is one
# row per pair, so pair_run_id alone is not unique on the trail tables; those
# use the natural key that the runner writes.
DEDUP_KEY = {
    "experiments": ("experiment_id",),
    "phase2_final": ("pair_run_id",),
    "phase2_researcher_runs": ("pair_run_id", "retry_count"),
    "phase2_verifier_runs": ("pair_run_id", "retry_count"),
    "phase2_adjudications": ("pair_run_id",),
    "subtrio_status": ("question_id", "country_code", "experiment_id"),
}


def _open_ro(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def canonical_experiments(canonical: Path) -> set[str]:
    with _open_ro(canonical) as conn:
        return {
            r[0] for r in conn.execute(
                "SELECT DISTINCT experiment_id FROM phase2_final "
                "WHERE experiment_id IS NOT NULL"
            )
        }


def find_orphans(canonical: Path) -> dict[str, tuple[str, int]]:
    """Map experiment_id -> (best source db, row count in phase2_final)."""
    have = canonical_experiments(canonical)
    best: dict[str, tuple[str, int]] = {}
    for db in sorted(glob.glob(WORKTREE_GLOB)):
        try:
            with _open_ro(db) as conn:
                rows = conn.execute(
                    "SELECT experiment_id, COUNT(*) FROM phase2_final "
                    "WHERE experiment_id IS NOT NULL GROUP BY 1"
                ).fetchall()
        except sqlite3.Error:
            continue
        for eid, n in rows:
            if eid in have:
                continue
            if eid not in best or n > best[eid][1]:
                best[eid] = (db, n)
    return best


def ensure_schema(dest: sqlite3.Connection, source_db: str) -> None:
    """Copy table definitions from a source database if they are absent."""
    with _open_ro(source_db) as src:
        for table in TABLES:
            row = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if row and row[0]:
                dest.execute(row[0].replace("CREATE TABLE",
                                            "CREATE TABLE IF NOT EXISTS", 1))
    dest.commit()


def copy_experiment(dest: sqlite3.Connection, source_db: str,
                    experiment_id: str, dry_run: bool) -> dict[str, int]:
    """Copy one experiment's rows across every table. Idempotent."""
    copied: dict[str, int] = {}
    with _open_ro(source_db) as src:
        for table in TABLES:
            cols = [c[1] for c in src.execute(f"PRAGMA table_info({table})")]
            if not cols or "experiment_id" not in cols:
                continue
            payload = [c for c in cols if c != "id"]
            rows = src.execute(
                f"SELECT {','.join(payload)} FROM {table} WHERE experiment_id=?",
                (experiment_id,),
            ).fetchall()
            if not rows:
                continue

            # Skip rows the destination already holds.
            key = [k for k in DEDUP_KEY.get(table, ()) if k in payload]
            existing: set[tuple] = set()
            if key and not dry_run:
                try:
                    existing = {
                        tuple(r) for r in dest.execute(
                            f"SELECT {','.join(key)} FROM {table} "
                            f"WHERE experiment_id=?", (experiment_id,)
                        )
                    }
                except sqlite3.Error:
                    existing = set()
            fresh = []
            for r in rows:
                d = dict(zip(payload, r))
                if key and tuple(d[k] for k in key) in existing:
                    continue
                fresh.append(tuple(d[c] for c in payload))

            copied[table] = len(fresh)
            if fresh and not dry_run:
                placeholders = ",".join("?" * len(payload))
                dest.executemany(
                    f"INSERT INTO {table} ({','.join(payload)}) "
                    f"VALUES ({placeholders})", fresh
                )
    if not dry_run:
        dest.commit()
    return copied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--canonical", default=str(CANONICAL))
    ap.add_argument("--out", default=str(PROJECT_ROOT / "data"
                                         / "rescued_experiments.db"))
    ap.add_argument("--merge-into", default=None,
                    help="write into this database instead of --out")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    canonical = Path(args.canonical)
    if not canonical.exists():
        raise SystemExit(f"canonical database not found: {canonical}")

    orphans = find_orphans(canonical)
    if not orphans:
        print("no orphaned experiments: every experiment with rows in a "
              "worktree is also present in the canonical database")
        return 0

    print(f"orphaned experiments (rows in a worktree, none in "
          f"{canonical.name}):\n")
    total = 0
    for eid, (db, n) in sorted(orphans.items(), key=lambda x: -x[1][1]):
        worktree = os.path.basename(os.path.dirname(os.path.dirname(db)))
        print(f"  {eid:36} {n:5d} pairs   <- {worktree}")
        total += n
    print(f"\n  {total} finalised pairs at risk across "
          f"{len(orphans)} experiments")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    target = Path(args.merge_into) if args.merge_into else Path(args.out)
    mode = "MERGE into" if args.merge_into else "write to"
    print(f"\n{mode} {target}")
    if args.merge_into and Path(args.merge_into) == canonical:
        print("  (canonical merge: make sure no dispatch is running)")

    dest = sqlite3.connect(target)
    first_source = next(iter(orphans.values()))[0]
    ensure_schema(dest, first_source)

    grand: dict[str, int] = {}
    for eid, (db, _n) in sorted(orphans.items()):
        copied = copy_experiment(dest, db, eid, dry_run=False)
        line = ", ".join(f"{t}={c}" for t, c in copied.items() if c)
        print(f"  {eid:36} {line or 'nothing new'}")
        for t, c in copied.items():
            grand[t] = grand.get(t, 0) + c
    dest.close()

    print("\nrescued rows by table:")
    for t, c in grand.items():
        print(f"  {t:26} {c:6d}")
    if target.exists():
        print(f"\n{target} is {target.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
