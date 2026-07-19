"""Idempotent migration: widen two CHECK constraints for the EXP-40
cooperative arm.

  1. phase2_verifier_runs.strategy_label  += 'verifier-corroborate'
  2. phase2_final.terminal_status         += 'accepted_cooperative',
                                             'abstained_cooperative'

The cooperative arm runs the corroborate verifier live (writing verifier rows)
and finalises with cooperative-specific terminal statuses. The original CHECKs
(scripts/setup_sqlite.py) predate both. SQLite cannot ALTER a CHECK in place,
so each affected table is rebuilt (data preserved, indexes restored) inside one
transaction. The new DDL is derived from the live table's own
sqlite_master SQL with the labels injected after an existing anchor label, so
the migration tracks whatever columns the table currently has rather than
hardcoding a snapshot.

Idempotent: a table already carrying its labels is skipped.

    uv run python scripts/migrate_corroborate_strategy_label.py [--db data/odmi.db]

Run it against the DB the run dispatches from (the worktree copy for an
experiment; the canonical checkout for a main-line migration). Never commit a
mutated worktree DB (see the db-tracked-diverges-per-worktree note).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# table -> (marker label proving migration done, anchor->insertion pairs).
# Each insertion adds `new` immediately after the line containing `anchor`,
# copying the anchor line's leading whitespace so the rebuilt DDL stays valid.
MIGRATIONS = {
    "phase2_verifier_runs": {
        "marker": "verifier-corroborate",
        "inserts": [("'verifier-blind'", "'verifier-corroborate'")],
        "indexes": [
            "CREATE INDEX idx_p2ver_pair ON phase2_verifier_runs(pair_run_id)",
            "CREATE INDEX idx_p2ver_strategy ON phase2_verifier_runs(strategy_label)",
            "CREATE INDEX idx_p2ver_experiment ON phase2_verifier_runs(experiment_id)",
        ],
    },
    "phase2_final": {
        "marker": "accepted_cooperative",
        "inserts": [
            ("'accepted_researcher_self_verify'", "'accepted_cooperative'"),
            ("'abstained_researcher_self_verify'", "'abstained_cooperative'"),
        ],
        "indexes": None,  # discovered from sqlite_master at runtime
    },
}


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not row:
        raise SystemExit(f"table {table} not found")
    return row[0]


def _index_sqls(conn: sqlite3.Connection, table: str) -> list[str]:
    return [
        r[0] for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? "
            "AND sql IS NOT NULL", (table,)
        )
    ]


def _inject(ddl: str, anchor: str, new_label: str) -> str:
    """Append `new_label` to a CHECK IN-list, right after the anchor label.

    Replaces the quoted anchor token (e.g. `'verifier-blind'`) with
    `<anchor>, <new_label>`. This keeps the list valid whether the anchor was
    the last item (no trailing comma: the new label becomes the new last item)
    or mid-list (its trailing comma stays after the new label). The anchor
    token appears once in the CHECK, so a single replacement is unambiguous.
    """
    if anchor not in ddl:
        raise SystemExit(f"anchor {anchor!r} not found for injection")
    return ddl.replace(anchor, f"{anchor}, {new_label}", 1)


def _migrate_table(conn: sqlite3.Connection, table: str, cfg: dict) -> str:
    ddl = _table_sql(conn, table)
    if cfg["marker"] in ddl:
        return f"skip {table}: already migrated"

    new_ddl = ddl
    for anchor, new_label in cfg["inserts"]:
        new_ddl = _inject(new_ddl, anchor, new_label)

    cols = ", ".join(r[1] for r in conn.execute(f"PRAGMA table_info({table})"))
    before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    indexes = cfg["indexes"] or _index_sqls(conn, table)

    conn.execute("BEGIN")
    conn.execute(f"ALTER TABLE {table} RENAME TO _mig_old")
    conn.executescript(new_ddl)
    conn.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _mig_old")
    conn.execute("DROP TABLE _mig_old")
    for ddl_idx in indexes:
        conn.execute(ddl_idx)
    conn.execute("COMMIT")

    after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if before != after:
        raise SystemExit(f"{table}: row count {before}->{after}, aborting")
    return f"migrated {table}: {before} rows preserved"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/odmi.db")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: {db_path} does not exist")
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        for table, cfg in MIGRATIONS.items():
            print(_migrate_table(conn, table, cfg))
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.execute("PRAGMA foreign_keys=ON")
        print(f"{db_path}: integrity={integrity}")
        return 0 if integrity == "ok" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
