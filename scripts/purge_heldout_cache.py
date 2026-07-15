"""Purge held-out-country cache rows from a DB before the EXP-36 headline run.

The 2026-07-13 purge (commit b8a316c) matched cache rows to URLs/queries that
appeared in surviving held-out `phase2_*` rows and cleared the fetch layer, but
left a residual in the SERP and snippet layers: rows whose query still names a
held-out country (Finland, Croatia, Bulgaria, ...) but whose originating
`phase2_*` row had already been deleted, so the join-based purge could not see
them. This script closes that gap and is the load-bearing hygiene step named in
`docs/EXPERIMENTS_EXP36_PREREG.md`.

The EXP-36 dispatch runs `no_cache: true`, so cache reads are disabled and the
purge is defence in depth, not the sole guard. Over-deleting is harmless: the
cache is disposable and regenerated live, and the run never reads it.

Held-out set (D47): BA MK ME BG FI HR SE BE. A row is held-out cache if:
  - its query names a held-out country (SERP / snippet), or
  - its url / query is referenced by a held-out `phase2_*` row, or
  - (fetch) its url host is on a held-out national ccTLD.

Usage:
  uv run python scripts/purge_heldout_cache.py --db data/odmi.db            # dry-run
  uv run python scripts/purge_heldout_cache.py --db data/odmi.db --apply    # delete + VACUUM
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

# D47 held-out eight. Kept in one place so a typo cannot desync from the spec.
HELD_OUT = ("BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE")

# Country-name fragments (lowercased) that a held-out query may contain, English
# plus the native forms seen in the bilingual query generator.
HELD_OUT_NAME_FRAGMENTS = (
    "bosnia", "bosna", "herzegovina", "hercegovina",
    "macedonia", "makedonija", "north macedonia",
    "montenegro", "crna gora",
    "bulgaria", "българия", "balgariya",
    "finland", "suomi",
    "croatia", "hrvatska",
    "sweden", "sverige",
    "belgium", "belgi", "belgique", "belgien",
)

# Held-out national ccTLD hosts (fetch layer). Matched as a host suffix, not a
# bare substring, so `about.me` or a `.be`-in-path never trips it.
HELD_OUT_CCTLDS = (".ba", ".mk", ".me", ".bg", ".fi", ".hr", ".se", ".be")


def _name_predicate(column: str) -> tuple[str, list[str]]:
    clause = " OR ".join(f"lower({column}) LIKE ?" for _ in HELD_OUT_NAME_FRAGMENTS)
    args = [f"%{frag}%" for frag in HELD_OUT_NAME_FRAGMENTS]
    return clause, args


def _held_out_refs(conn: sqlite3.Connection) -> tuple[set[str], set[str]]:
    """URLs and queries referenced by any held-out `phase2_*` row."""
    urls: set[str] = set()
    queries: set[str] = set()
    placeholders = ",".join("?" * len(HELD_OUT))
    for table in ("phase2_researcher_runs", "phase2_verifier_runs"):
        try:
            rows = conn.execute(
                f"SELECT fetched_urls, search_queries_used FROM {table} "
                f"WHERE country_code IN ({placeholders})",
                HELD_OUT,
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for fetched_urls, queries_used in rows:
            for raw, sink in ((fetched_urls, urls), (queries_used, queries)):
                if not raw:
                    continue
                try:
                    for item in json.loads(raw):
                        if item:
                            sink.add(str(item))
                except (json.JSONDecodeError, TypeError):
                    continue
    return urls, queries


def _host_on_held_out_cctld(url: str) -> bool:
    try:
        host = url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    except (IndexError, AttributeError):
        return False
    host = host.rstrip(".")
    return any(host == tld[1:] or host.endswith(tld) for tld in HELD_OUT_CCTLDS)


def scan(conn: sqlite3.Connection) -> dict[str, list]:
    """Return the row keys to delete per cache table. Read-only."""
    ref_urls, ref_queries = _held_out_refs(conn)

    to_delete: dict[str, list] = {"fetch": [], "serp": [], "snippet": []}

    # SERP + snippet: name-match OR referenced by a held-out phase2 row.
    name_clause, name_args = _name_predicate("query")
    for layer, table, key_col in (
        ("serp", "search_cache_serp", "cache_key"),
        ("snippet", "search_cache_snippet", "cache_key"),
    ):
        rows = conn.execute(
            f"SELECT {key_col}, query FROM {table} WHERE {name_clause}", name_args,
        ).fetchall()
        keys = {r[0] for r in rows}
        # Add rows whose exact query is referenced by a held-out phase2 row.
        for (key, query) in conn.execute(f"SELECT {key_col}, query FROM {table}"):
            if query in ref_queries:
                keys.add(key)
        to_delete[layer] = sorted(keys)

    # Fetch: referenced by a held-out phase2 row OR host on a held-out ccTLD.
    for (url,) in conn.execute("SELECT url FROM search_cache_fetch"):
        if url in ref_urls or _host_on_held_out_cctld(url):
            to_delete["fetch"].append(url)

    return to_delete


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    out = {}
    for layer, table in (
        ("fetch", "search_cache_fetch"),
        ("serp", "search_cache_serp"),
        ("snippet", "search_cache_snippet"),
    ):
        out[layer] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="Path to the odmi.db to purge.")
    ap.add_argument("--apply", action="store_true",
                    help="Delete the rows and VACUUM. Default is a dry-run.")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: {db} does not exist")
        return 2

    conn = sqlite3.connect(str(db))
    try:
        before = counts(conn)
        targets = scan(conn)
        n = {k: len(v) for k, v in targets.items()}
        print(f"DB: {db}")
        print(f"cache rows before: {before}")
        print(f"held-out rows identified: fetch={n['fetch']} "
              f"serp={n['serp']} snippet={n['snippet']}")

        if not args.apply:
            print("DRY-RUN: nothing deleted. Re-run with --apply to purge.")
            return 0

        cur = conn.cursor()
        for url in targets["fetch"]:
            cur.execute("DELETE FROM search_cache_fetch WHERE url = ?", (url,))
        for key in targets["serp"]:
            cur.execute("DELETE FROM search_cache_serp WHERE cache_key = ?", (key,))
        for key in targets["snippet"]:
            cur.execute("DELETE FROM search_cache_snippet WHERE cache_key = ?", (key,))
        conn.commit()

        # Verify: a fresh scan must find zero held-out rows.
        residual = {k: len(v) for k, v in scan(conn).items()}
        conn.execute("VACUUM")
        conn.commit()
        after = counts(conn)
        print(f"cache rows after:  {after}")
        print(f"residual held-out rows (must be 0): {residual}")
        ok = all(v == 0 for v in residual.values())
        print("VERIFIED CLEAN" if ok else "WARNING: residual held-out rows remain")
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
