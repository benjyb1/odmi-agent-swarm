"""Purge the whole DIY search cache, optionally archiving it first.

`purge_heldout_cache.py` clears only rows belonging to the D47 held-out eight.
A repeat-run experiment needs the opposite: every cached SERP, fetch and
snippet gone, so run N+1 cannot see run N's evidence under any circumstance.
That is what this does.

Why it is needed even when the run sets `no_cache: true`. The `--no-cache`
flag disables cache *reads* only; writes stay on so the cache remains an audit
record (`agents/tools/search_cache.py` docstring). So a cold run still refills
all three tables, and the purge has to be repeated before every repeat, not
once before the first. `--no-cache` is the load-bearing control; this purge is
the second, independent guard, and `--archive` turns the filled cache into that
run's evidence receipt before it is cleared.

The three tables self-recreate lazily via `search_cache.ensure_tables()`, so
deleting every row (or the tables themselves) is safe.

Usage:
  uv run python scripts/purge_search_cache.py --db data/odmi.db            # dry-run
  uv run python scripts/purge_search_cache.py --db data/odmi.db --apply
  uv run python scripts/purge_search_cache.py --db data/odmi.db --apply \
      --archive evaluation/runs/exp41_rep1/search_cache.db
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

CACHE_TABLES = ("search_cache_serp", "search_cache_fetch", "search_cache_snippet")


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row count per cache table; a missing table reads as 0, not an error."""
    out: dict[str, int] = {}
    for t in CACHE_TABLES:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = 0
    return out


def archive(conn: sqlite3.Connection, dest: Path) -> dict[str, int]:
    """Copy the three cache tables into `dest` as this run's evidence receipt.

    Written before the purge, so the archive is the complete record of what the
    run actually retrieved. Fails loudly if `dest` already exists: silently
    overwriting one run's receipt with another's is the failure this whole
    exercise exists to prevent.
    """
    if dest.exists():
        raise FileExistsError(f"{dest} exists; refusing to overwrite a run receipt")
    dest.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("ATTACH DATABASE ? AS arc", (str(dest),))
    try:
        written: dict[str, int] = {}
        for t in CACHE_TABLES:
            try:
                conn.execute(f"CREATE TABLE arc.{t} AS SELECT * FROM main.{t}")
                written[t] = conn.execute(f"SELECT COUNT(*) FROM arc.{t}").fetchone()[0]
            except sqlite3.OperationalError:
                written[t] = 0
        conn.commit()
        return written
    finally:
        conn.execute("DETACH DATABASE arc")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="DB the next dispatch will use.")
    ap.add_argument("--apply", action="store_true", help="Delete (default: dry-run).")
    ap.add_argument(
        "--archive",
        default=None,
        help="Write the cache to this SQLite file before purging (run receipt).",
    )
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: {db} does not exist")
        return 2

    conn = sqlite3.connect(str(db))
    try:
        before = counts(conn)
        print(f"DB: {db}")
        print(f"cache rows before: {before} (total {sum(before.values())})")

        if not args.apply:
            print("DRY-RUN: nothing deleted. Re-run with --apply to purge.")
            return 0

        if args.archive:
            try:
                written = archive(conn, Path(args.archive))
            except FileExistsError as exc:
                print(f"ERROR: {exc}")
                print("Nothing purged. Choose a fresh archive path per run.")
                return 2
            print(f"archived to {args.archive}: {written}")

        for t in CACHE_TABLES:
            try:
                conn.execute(f"DELETE FROM {t}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()

        after = counts(conn)
        print(f"cache rows after:  {after} (total {sum(after.values())})")
        ok = sum(after.values()) == 0
        print("VERIFIED EMPTY" if ok else "WARNING: cache rows remain")
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
