#!/usr/bin/env python3
"""EXP-23 pre-read manipulation checks.

The brief declared three invariants that MUST pass before any endpoint is
read; if any fails the experiment is not measuring what it claims to be.

  1. wide_only must issue zero site-restricted queries on every pair.
  2. baseline_narrow_then_wide and narrow_only must produce identical
     narrow-stage queries on every pair where baseline did NOT widen
     (i.e. the narrow pass returned non-empty). The only divergence
     between those two arms is meant to be the widening step.
  3. data/trusted_domains/<cc>.json must exist and be non-empty for
     every condition country (NL, MT, AL), or the narrow_then_wide and
     narrow_only arms are not testing anything.

Prints PASS/FAIL per check and exits 0 only if all three pass.

Run:
    uv run python evaluation/manipulation_check_exp23.py
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "odmi.db"
COUNTRIES = ["NL", "MT", "AL"]
EXP_IDS = [f"exp23_narrow_then_widen_{cc.lower()}" for cc in COUNTRIES]
SITE_MARKER = "site:"


def load_queries_by_arm() -> dict[str, list[dict]]:
    """For each (pair_run_id, arm), the queries the Researcher actually issued."""
    conn = sqlite3.connect(DB)
    rows = conn.execute(f"""
        SELECT r.pair_run_id, r.condition_label, r.country_code, r.question_id,
               r.retry_count, r.search_queries_used
          FROM phase2_researcher_runs r
         WHERE r.experiment_id IN ({','.join('?' for _ in EXP_IDS)})
    """, EXP_IDS).fetchall()
    conn.close()

    by_arm: dict[str, list[dict]] = defaultdict(list)
    for prid, arm, cc, qid, retries, queries_j in rows:
        try:
            queries = json.loads(queries_j) if queries_j else []
        except json.JSONDecodeError:
            queries = []
        by_arm[arm].append({
            "pair_run_id": prid, "cc": cc, "qid": qid,
            "retries": retries, "queries": queries,
        })
    return by_arm


def check_wide_only_no_site_clauses(by_arm: dict[str, list[dict]]) -> tuple[bool, list[str]]:
    rows = by_arm.get("wide_only", [])
    if not rows:
        return (False, ["wide_only arm has no rows yet -- dispatch incomplete"])
    violations = []
    for row in rows:
        bad = [q for q in row["queries"] if SITE_MARKER in q]
        if bad:
            violations.append(f"  {row['qid']}:{row['cc']} retry={row['retries']} "
                              f"site-clause queries: {bad}")
    ok = not violations
    msgs = [f"  wide_only rows scored: {len(rows)} (all retries across all pairs)"]
    if violations:
        msgs.append("  VIOLATIONS:")
        msgs.extend(violations)
    return (ok, msgs)


def check_narrow_only_matches_baseline(by_arm: dict[str, list[dict]]) -> tuple[bool, list[str]]:
    """On the FIRST attempt (retry_count = 0) of each (qid, cc) pair, the
    narrow-stage queries must be byte-identical between baseline_narrow_then_wide
    and narrow_only. Both run the same trusted-domain include list on the
    first pass; they only diverge if/when baseline widens on empty.
    """
    base = {(r["qid"], r["cc"]): r for r in by_arm.get("baseline_narrow_then_wide", [])
            if r["retries"] == 0}
    narr = {(r["qid"], r["cc"]): r for r in by_arm.get("narrow_only", [])
            if r["retries"] == 0}
    common = sorted(set(base) & set(narr))
    if not common:
        return (False, ["no overlapping first-attempt rows between baseline and "
                        "narrow_only -- dispatch incomplete"])
    mismatches = []
    for key in common:
        b_qs = list(base[key]["queries"])
        n_qs = list(narr[key]["queries"])
        if b_qs != n_qs:
            mismatches.append(f"  {key[0]}:{key[1]}\n"
                              f"    baseline: {b_qs}\n"
                              f"    narrow  : {n_qs}")
    ok = not mismatches
    msgs = [f"  overlapping first-attempt pairs: {len(common)}"]
    if mismatches:
        msgs.append(f"  MISMATCHES ({len(mismatches)}):")
        msgs.extend(mismatches[:10])
        if len(mismatches) > 10:
            msgs.append(f"  ... +{len(mismatches)-10} more")
    return (ok, msgs)


def check_trusted_domains_present() -> tuple[bool, list[str]]:
    msgs = []
    ok = True
    for cc in COUNTRIES:
        path = REPO / "data" / "trusted_domains" / f"{cc}.json"
        if not path.exists():
            ok = False
            msgs.append(f"  {cc}: MISSING {path.relative_to(REPO)}")
            continue
        try:
            doc = json.loads(path.read_text())
            domains = doc.get("trusted_domains", [])
        except Exception as e:
            ok = False
            msgs.append(f"  {cc}: parse error: {e}")
            continue
        if not domains:
            ok = False
            msgs.append(f"  {cc}: trusted_domains is empty")
        else:
            msgs.append(f"  {cc}: {len(domains)} trusted domains "
                        f"(first 3: {domains[:3]})")
    return (ok, msgs)


def main() -> int:
    by_arm = load_queries_by_arm()

    results = []
    print("EXP-23 manipulation checks\n" + "="*42)

    print("\n1. wide_only issues zero site-restricted queries")
    ok, msgs = check_wide_only_no_site_clauses(by_arm)
    results.append(("wide_only_no_site", ok))
    for m in msgs:
        print(m)
    print(f"   -> {'PASS' if ok else 'FAIL'}")

    print("\n2. narrow_only first-attempt queries match baseline_narrow_then_wide")
    ok, msgs = check_narrow_only_matches_baseline(by_arm)
    results.append(("narrow_only_matches_baseline", ok))
    for m in msgs:
        print(m)
    print(f"   -> {'PASS' if ok else 'FAIL'}")

    print("\n3. trusted_domains JSON present and non-empty per country")
    ok, msgs = check_trusted_domains_present()
    results.append(("trusted_domains_present", ok))
    for m in msgs:
        print(m)
    print(f"   -> {'PASS' if ok else 'FAIL'}")

    all_ok = all(r for _, r in results)
    print("\n" + "="*42)
    print(f"OVERALL: {'ALL PASS' if all_ok else 'AT LEAST ONE FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
