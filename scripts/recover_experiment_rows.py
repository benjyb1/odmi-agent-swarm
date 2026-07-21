"""Export an experiment's rows out of a recovered database into a portable dump.

Runs whose worktree was deleted often survive as unreferenced Git LFS objects
under `.git/lfs/objects/` (see `data/recovery/README.md`). This script lifts one
experiment out of such a source and writes gzipped `INSERT OR REPLACE`
statements that can be replayed into the canonical database.

    uv run python scripts/recover_experiment_rows.py \
        --source .git/lfs/objects/ab/cd/abcd... \
        --experiment-id exp40_cooperative_contrast \
        --out data/recovery/exp40_cooperative_recovered.sql.gz

The source may be any SQLite file. If it carries `-wal`/`-shm` sidecars, pass
`--copy-wal` so they are copied alongside and checkpointed before reading;
without that, rows still sitting in the write-ahead log are silently missed.

Restore with `scripts/merge_recovered_experiment.py --dump`, never by piping
the dump into sqlite3. The ids in it are the source database's, and replaying
them directly overwrites whichever canonical rows happen to share those ids;
in testing that destroyed 831 rows of `exp36_frozen_headline`. The merge script
strips the ids and rewrites the foreign keys instead.
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

# Ordered so parents land before the rows that reference them.
TABLES = [
    "experiments",
    "phase2_final",
    "phase2_researcher_runs",
    "phase2_verifier_runs",
    "phase2_adjudications",
    "phase2_classifications",
    "subtrio_status",
]


def _literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, bytes):
        return "X'" + v.hex() + "'"
    return "'" + str(v).replace("'", "''") + "'"


def _prepare(source: Path, copy_wal: bool) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    """Copy the source (and its WAL) somewhere writable so the log can replay."""
    if not copy_wal:
        return source, None
    tmp = tempfile.TemporaryDirectory()
    staged = Path(tmp.name) / "recovered.db"
    shutil.copy2(source, staged)
    for suffix in ("-wal", "-shm"):
        side = source.with_name(source.name + suffix)
        if side.exists():
            shutil.copy2(side, staged.with_name(staged.name + suffix))
    conn = sqlite3.connect(staged)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return staged, tmp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path,
                    help="SQLite file holding the rows (an LFS object, a worktree DB)")
    ap.add_argument("--experiment-id", required=True,
                    help="matched with LIKE, so a prefix such as exp34%% works")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--copy-wal", action="store_true",
                    help="stage the source with its -wal/-shm and checkpoint first")
    args = ap.parse_args()

    if not args.source.exists():
        print(f"no such source: {args.source}", file=sys.stderr)
        return 1

    staged, tmp = _prepare(args.source, args.copy_wal)
    try:
        conn = sqlite3.connect(f"file:{staged}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        args.out.parent.mkdir(parents=True, exist_ok=True)

        counts: dict[str, int] = {}
        with gzip.open(args.out, "wt") as fh:
            fh.write(f"-- {args.experiment_id} recovered from {args.source.name}\n")
            fh.write("-- Merge with scripts/merge_recovered_experiment.py --dump.\n")
            fh.write("-- Do NOT pipe straight into sqlite3: the ids here belong to the\n")
            fh.write("-- source database and would overwrite unrelated canonical rows.\n")
            fh.write("BEGIN;\n")
            # Every prompt version, not just this experiment's: the runs carry
            # prompt_version_id foreign keys, and the table has no experiment_id
            # to filter on. Small enough that copying all of it is simplest.
            try:
                pv = conn.execute("SELECT * FROM prompt_versions").fetchall()
                for r in pv:
                    cols = ",".join(f'"{k}"' for k in r.keys())
                    vals = ",".join(_literal(v) for v in r)
                    fh.write(f"INSERT OR REPLACE INTO prompt_versions ({cols}) VALUES ({vals});\n")
                if pv:
                    counts["prompt_versions"] = len(pv)
            except sqlite3.Error:
                pass
            for table in TABLES:
                try:
                    rows = conn.execute(
                        f"SELECT * FROM {table} WHERE experiment_id LIKE ?",
                        (args.experiment_id,),
                    ).fetchall()
                except sqlite3.Error:
                    continue  # table absent, or has no experiment_id column
                for r in rows:
                    cols = ",".join(f'"{k}"' for k in r.keys())
                    vals = ",".join(_literal(v) for v in r)
                    fh.write(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({vals});\n")
                if rows:
                    counts[table] = len(rows)
            fh.write("COMMIT;\n")
        conn.close()
    finally:
        if tmp is not None:
            tmp.cleanup()

    if not counts:
        print(f"no rows matched {args.experiment_id} in {args.source}", file=sys.stderr)
        args.out.unlink(missing_ok=True)
        return 1

    for table, n in counts.items():
        print(f"  {table}: {n}")
    size_kb = args.out.stat().st_size / 1024
    print(f"wrote {args.out} ({sum(counts.values())} rows, {size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
