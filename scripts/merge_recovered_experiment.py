"""Merge a recovered experiment's rows into the canonical database.

Recovered rows come from a different database, so their INTEGER PRIMARY KEYs
mean nothing here: id 8325 in the source is a different row from id 8325 in
canonical. Replaying a plain dump with `INSERT OR REPLACE` therefore overwrites
unrelated rows -- in testing it silently destroyed 831 rows of
`exp36_frozen_headline`. This script exists because that is not recoverable by
inspection afterwards.

Instead, every row is inserted with its `id` omitted so SQLite assigns a fresh
one, and `phase2_verifier_runs.researcher_run_id` (the one real foreign key
between these tables) is rewritten through the old-id -> new-id map built while
inserting the researcher rows.

Idempotent: rows are matched on natural keys, and anything already present is
left untouched rather than duplicated.

    pair_run_id                          phase2_final (already UNIQUE)
    pair_run_id, retry_count             phase2_researcher_runs
    pair_run_id, retry_count,
      strategy_label, created_at         phase2_verifier_runs
    pair_run_id                          phase2_adjudications
    subtrio_id                           subtrio_status (text PK, no collision)

Usage:

    uv run python scripts/merge_recovered_experiment.py \
        --db data/odmi.db --source <recovered.db> --experiment-id exp40%

    # or straight from a gzipped dump produced by recover_experiment_rows.py
    uv run python scripts/merge_recovered_experiment.py \
        --db data/odmi.db --dump data/recovery/exp40_cooperative_recovered.sql.gz

`--dry-run` reports what would be inserted and rolls back. Run against the
canonical checkout, never a worktree copy.
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

# table -> columns forming the natural key used to detect an existing row.
NATURAL_KEY = {
    "prompt_versions": ("prompt_name", "version"),
    "phase2_final": ("pair_run_id",),
    "phase2_researcher_runs": ("pair_run_id", "retry_count"),
    "phase2_verifier_runs": ("pair_run_id", "retry_count", "strategy_label", "created_at"),
    "phase2_adjudications": ("pair_run_id",),
    "subtrio_status": ("subtrio_id",),
}

# Insertion order: researcher rows must land before the verifier rows that
# point at them, or the id remap has nothing to resolve against.
ORDER = [
    "experiments",
    "phase2_final",
    "phase2_researcher_runs",
    "phase2_verifier_runs",
    "phase2_adjudications",
    "subtrio_status",
]


def _dump_to_db(dump: Path, like_db: Path) -> tuple[Path, tempfile.TemporaryDirectory]:
    """Replay a gzipped dump into a scratch DB so it can be merged like any source.

    The scratch DB borrows its schema from the destination, so a dump only
    loads if the destination can actually hold it -- a dump carrying EXP-40's
    cooperative terminal statuses fails loudly here if the corroborate-label
    migration has not been run yet, rather than half-applying.
    """
    tmp = tempfile.TemporaryDirectory()
    staged = Path(tmp.name) / "dump.db"

    src_schema = sqlite3.connect(f"file:{like_db}?mode=ro", uri=True)
    ddl = [
        r[0] for r in src_schema.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
        )
    ]
    src_schema.close()

    conn = sqlite3.connect(staged)
    for stmt in ddl:
        conn.execute(stmt)
    opener = gzip.open if dump.suffix == ".gz" else open
    with opener(dump, "rt") as fh:
        conn.executescript(fh.read())
    conn.commit()
    conn.close()
    return staged, tmp


def _merge_prompt_versions(dst, src, stats) -> dict[int, int]:
    """Copy any missing prompt versions across; return old id -> new id.

    A prompt version already present under the same (prompt_name, version) but
    with different text is a real integrity problem -- two different prompts
    wearing one version number -- so it stops the merge rather than being
    quietly reused.
    """
    try:
        rows = src.execute(
            "SELECT id, prompt_name, version, prompt_text FROM prompt_versions"
        ).fetchall()
    except sqlite3.Error:
        return {}

    remap, inserted, skipped = {}, 0, 0
    for r in rows:
        got = dst.execute(
            "SELECT id, prompt_text FROM prompt_versions WHERE prompt_name=? AND version=?",
            (r["prompt_name"], r["version"]),
        ).fetchone()
        if got:
            if got[1] != r["prompt_text"]:
                raise RuntimeError(
                    f"prompt {r['prompt_name']} v{r['version']} differs between "
                    "source and destination; refusing to guess which run used which"
                )
            remap[r["id"]] = got[0]
            skipped += 1
            continue
        full = src.execute("SELECT * FROM prompt_versions WHERE id=?", (r["id"],)).fetchone()
        data = {k: full[k] for k in full.keys() if k != "id"}
        cols = ",".join(f'"{c}"' for c in data)
        ph = ",".join("?" * len(data))
        cur = dst.execute(
            f"INSERT INTO prompt_versions ({cols}) VALUES ({ph})", tuple(data.values())
        )
        remap[r["id"]] = cur.lastrowid
        inserted += 1
    if inserted or skipped:
        stats["prompt_versions"] = {"inserted": inserted, "skipped": skipped}
    return remap


def _existing_keys(dst, table, cols):
    sel = ",".join(f'"{c}"' for c in cols)
    try:
        return {tuple(r) for r in dst.execute(f"SELECT {sel} FROM {table}")}
    except sqlite3.Error:
        return set()


def merge(dst_path: Path, src_path: Path, eid: str, dry_run: bool) -> dict:
    dst = sqlite3.connect(dst_path)
    dst.execute("PRAGMA foreign_keys=ON")
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    stats, researcher_remap = {}, {}
    fk_before = len(dst.execute("PRAGMA foreign_key_check").fetchall())
    try:
        # Prompt versions come first and are handled wholesale rather than per
        # experiment: the recovered rows point at them, and a prompt written in
        # a deleted worktree (EXP-40's corroborate V2) never reached canonical.
        # Matched on (prompt_name, version) so an id that means different things
        # in the two databases cannot silently rebind a run to the wrong prompt.
        prompt_remap = _merge_prompt_versions(dst, src, stats)

        for table in ORDER:
            try:
                rows = src.execute(
                    f"SELECT * FROM {table} WHERE experiment_id LIKE ?", (eid,)
                ).fetchall()
            except sqlite3.Error:
                continue
            if not rows:
                continue

            if table == "experiments":  # keyed by text id, no collision risk
                n = 0
                for r in rows:
                    cols = ",".join(f'"{k}"' for k in r.keys())
                    ph = ",".join("?" * len(r))
                    cur = dst.execute(
                        f"INSERT OR IGNORE INTO experiments ({cols}) VALUES ({ph})", tuple(r)
                    )
                    n += cur.rowcount
                stats[table] = {"inserted": n, "skipped": len(rows) - n}
                continue

            key = NATURAL_KEY[table]
            seen = _existing_keys(dst, table, key)
            inserted = skipped = 0
            for r in rows:
                k = tuple(r[c] for c in key)
                if k in seen:
                    skipped += 1
                    if table == "phase2_researcher_runs":
                        # Still need its new id so verifier rows resolve.
                        got = dst.execute(
                            "SELECT id FROM phase2_researcher_runs "
                            "WHERE pair_run_id=? AND retry_count=?", k
                        ).fetchone()
                        if got:
                            researcher_remap[r["id"]] = got[0]
                    continue

                data = {k2: r[k2] for k2 in r.keys() if k2 != "id"}
                if data.get("prompt_version_id") is not None:
                    data["prompt_version_id"] = prompt_remap.get(
                        data["prompt_version_id"], data["prompt_version_id"]
                    )
                if table == "phase2_verifier_runs":
                    old = data.get("researcher_run_id")
                    if old is not None:
                        if old not in researcher_remap:
                            skipped += 1  # orphan: its researcher row never arrived
                            continue
                        data["researcher_run_id"] = researcher_remap[old]

                cols = ",".join(f'"{c}"' for c in data)
                ph = ",".join("?" * len(data))
                cur = dst.execute(
                    f"INSERT INTO {table} ({cols}) VALUES ({ph})", tuple(data.values())
                )
                if table == "phase2_researcher_runs":
                    researcher_remap[r["id"]] = cur.lastrowid
                seen.add(k)
                inserted += 1
            stats[table] = {"inserted": inserted, "skipped": skipped}

        # The destination already carries orphaned rows of its own (canonical
        # holds 1,592 verifier rows whose researcher row never made it in), so
        # an absolute check would fail on damage this merge did not cause.
        # Only a net increase matters.
        after = len(dst.execute("PRAGMA foreign_key_check").fetchall())
        if after > fk_before:
            raise RuntimeError(
                f"merge introduced {after - fk_before} new foreign key violations"
            )
        stats["_fk_violations"] = {"before": fk_before, "after": after}
        if dry_run:
            dst.rollback()
        else:
            dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, type=Path, help="destination (canonical)")
    ap.add_argument("--source", type=Path, help="a recovered SQLite database")
    ap.add_argument("--dump", type=Path, help="a .sql.gz from recover_experiment_rows.py")
    ap.add_argument("--experiment-id", default="%", help="LIKE pattern; default every experiment")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if bool(args.source) == bool(args.dump):
        print("pass exactly one of --source or --dump", file=sys.stderr)
        return 2

    tmp = None
    if args.dump:
        src, tmp = _dump_to_db(args.dump, args.db)
    else:
        src = args.source

    try:
        stats = merge(args.db, src, args.experiment_id, args.dry_run)
    finally:
        if tmp is not None:
            tmp.cleanup()

    fk = stats.pop("_fk_violations", None)
    total = sum(s["inserted"] for s in stats.values())
    for t, s in stats.items():
        print(f"  {t:28s} +{s['inserted']:5d}  ({s['skipped']} already present)")
    if fk and fk["before"]:
        print(f"  (pre-existing foreign key violations: {fk['before']}, unchanged)")
    print(f"{'would insert' if args.dry_run else 'inserted'} {total} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
