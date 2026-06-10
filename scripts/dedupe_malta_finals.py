"""Dedupe duplicate Malta phase2_final rows (EXP-6 primary dataset hygiene).

Malta was dispatched twice under the baseline condition (batches exp6_malta then
malta_baseline), and run_coordinator has no skip-if-finalised guard, so 12 pairs
carry duplicate phase2_final rows: mostly a first failed finalisation
(final_answer IS NULL) superseded by the real answer, plus a few exact-agreeing
copies and two genuine committed disagreements (PT29, Q6). A naive query over
phase2_final then double-counts or picks a NULL. The de-duplicated content already
matches the documented headline (43 committed / 17 inconclusive / 32 exact), so
this only removes redundant and stale rows; it does not change the result.

Rule, per (question_id) on MT baseline (experiment_id IS NULL):
  - keep the highest-id row that has a non-NULL final_answer (highest id = the
    later, canonical malta_baseline insert; this is the answer the documented
    figures already reflect, e.g. PT29 -> committed yes, the recorded no-gold
    false positive);
  - if every row is NULL (should not happen here), keep the highest-id row;
  - delete all other phase2_final rows for that pair.

phase2_researcher_runs / phase2_verifier_runs / phase2_adjudications are left
untouched, so the per-call receipts (the real audit trail) are intact; only the
derived summary table is cleaned.

Dry-run by default. Pass --apply to write. Always takes a timestamped .db backup
before deleting.

Usage:
    uv run python scripts/dedupe_malta_finals.py            # dry-run
    uv run python scripts/dedupe_malta_finals.py --apply
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "odmi.db"
COUNTRY = "MT"


def _is_pass(a: str, g: str) -> bool:
    a = (a or "").strip().lower()
    g = (g or "").strip().lower()
    if a == g and g:
        return True
    if a == "yes" and g.startswith("yes"):
        return True
    if a == "no" and g == "no":
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete (default dry-run)")
    ap.add_argument("--backup-suffix", default="predupe_malta")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "select id, question_id, final_answer, terminal_status, created_at "
        "from phase2_final where upper(country_code)=? and experiment_id is null "
        "order by question_id, id", (COUNTRY,),
    )]
    gold = {r[0]: (r[1] or "").strip().lower() for r in con.execute(
        "select question_id, response from ground_truth where country_code=?", (COUNTRY,),
    )}

    by_q: dict[str, list] = defaultdict(list)
    for r in rows:
        by_q[r["question_id"]].append(r)

    keep_ids, delete_ids = [], []
    for q, rs in by_q.items():
        non_null = [r for r in rs if (r["final_answer"] or "").strip() != ""]
        pool = non_null if non_null else rs
        winner = max(pool, key=lambda r: r["id"])
        keep_ids.append(winner["id"])
        for r in rs:
            if r["id"] != winner["id"]:
                delete_ids.append(r["id"])

    # Project the post-dedupe headline to confirm it matches the documented figures.
    kept = [r for r in rows if r["id"] in set(keep_ids)]
    committed = incon = exact = 0
    for r in kept:
        a = (r["final_answer"] or "").strip().lower()
        if a == "inconclusive":
            incon += 1
            continue
        if a == "":
            continue
        committed += 1
        if _is_pass(a, gold.get(r["question_id"], "")):
            exact += 1

    print(f"MT baseline phase2_final rows: {len(rows)}")
    print(f"distinct pairs: {len(by_q)}")
    print(f"keep: {len(keep_ids)}   delete: {len(delete_ids)}")
    print(f"post-dedupe headline -> committed={committed} inconclusive={incon} "
          f"exact_on_committed={exact}  (documented: 43 / 17 / 32)")
    dup_qs = {q: len(rs) for q, rs in by_q.items() if len(rs) > 1}
    print(f"deduped qids: {dup_qs}")
    for q, rs in by_q.items():
        if len(rs) > 1:
            tags = [(r["id"], r["final_answer"]) for r in rs]
            win = max((r for r in rs if (r['final_answer'] or '').strip()),
                      key=lambda r: r['id'], default=max(rs, key=lambda r: r['id']))
            print(f"  {q}: rows={tags} -> keep id={win['id']} ({win['final_answer']})")

    if not delete_ids:
        print("nothing to delete.")
        return 0

    if not args.apply:
        print("\n[dry-run] no changes written. Re-run with --apply to delete.")
        return 0

    backup = DB.with_suffix(f".{args.backup_suffix}.bak")
    shutil.copy2(DB, backup)
    print(f"\nbacked up DB -> {backup}")
    placeholders = ",".join("?" * len(delete_ids))
    con.execute(f"delete from phase2_final where id in ({placeholders})", delete_ids)
    con.commit()
    remaining = con.execute(
        "select count(*) from phase2_final where upper(country_code)=? "
        "and experiment_id is null", (COUNTRY,),
    ).fetchone()[0]
    dups_after = [q for q, n in Counter(
        r[0] for r in con.execute(
            "select question_id from phase2_final where upper(country_code)=? "
            "and experiment_id is null", (COUNTRY,))
    ).items() if n > 1]
    con.close()
    print(f"deleted {len(delete_ids)} rows. MT baseline finals now: {remaining} "
          f"(expect 60). remaining dup qids: {dups_after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
