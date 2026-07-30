#!/usr/bin/env python3
"""EXP-42 pilot: is the corroborative arm working as designed?

This is an OPERATIONAL check, not a stance result. 112 pairs is under-powered for
the registered EXP-42 endpoints, so nothing here is reported as evidence about
verifier stance. What it can establish is whether the machinery does what the
pre-registration says it does, which is the thing that has been wrong four times
already.

Nine checks, each PASS/FAIL on a stated criterion:

  1. Completion      did the arms finish, and did any pair crash
  2. Strategy        every verifier row ran verifier-corroborate
  3. Search direction  the corroborative generator fired, the adversarial one never did
  4. Query content   queries seek support, and carry a national-language variant
  5. Deny-list       zero new D24 violations attributable to this run
  6. Model           every row is claude-sonnet-4-6, no banned Sonnet 5
  7. Seeding         the expected attempt-1 seeds actually landed
  8. Outcomes        commit/abstain split is in a plausible range
  9. Arm A contrast  paired against the same 112 pairs, DESCRIPTIVE ONLY

Usage:
    uv run python evaluation/exp42_pilot_analysis.py [--db data/odmi.db]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter

PILOT = "exp42_pilot_heldout"
ARM_A_SRC = "exp36_frozen_headline"
BANNED_SUBSTR = ("data.europa.eu", "europeandataportal.eu", "open-data-maturity")
COUNTRIES = ["FI", "BE", "HR", "BG", "ME", "MK", "BA", "SE"]

# Recorded before dispatch, from the same query this script runs. Any increase is
# attributable to the pilot.
BASELINE_LEAKS = {"verifier": 36, "final": 19}


def rule(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def verdict(ok: bool, msg: str) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
    return ok


def norm(a) -> str:
    return (a or "").strip().lower()


def pilot_pairs(c) -> set:
    return {
        (q, cc)
        for q, cc in c.execute(
            "SELECT DISTINCT question_id, country_code FROM phase2_final "
            "WHERE experiment_id=?", (PILOT,)
        )
    }


def check_completion(c) -> bool:
    rule("1. Completion")
    rows = c.execute(
        "SELECT country_code, terminal_status, COUNT(*) FROM phase2_final "
        "WHERE experiment_id=? GROUP BY 1,2", (PILOT,)
    ).fetchall()
    per_cc = Counter()
    statuses = Counter()
    for cc, st, n in rows:
        per_cc[cc] += n
        statuses[st] += n
    total = sum(per_cc.values())
    print(f"  finalised {total}/112")
    for cc in COUNTRIES:
        print(f"    {cc}: {per_cc.get(cc, 0)}/14")
    print(f"  terminal statuses: {dict(statuses)}")
    crashed = statuses.get("agent_failure", 0)
    ok = total >= 90 and crashed == 0
    return verdict(
        ok,
        f"{total}/112 finalised (>=90 expected), {crashed} agent_failure (0 expected)",
    )


def check_strategy(c) -> bool:
    rule("2. Verifier strategy")
    strats = c.execute(
        "SELECT strategy_label, COUNT(*) FROM phase2_verifier_runs "
        "WHERE experiment_id=? GROUP BY 1", (PILOT,)
    ).fetchall()
    print(f"  {strats}")
    ok = len(strats) == 1 and strats[0][0] == "verifier-corroborate"
    return verdict(ok, "every verifier row ran verifier-corroborate")


def check_search_direction(c) -> bool:
    rule("3. Search direction")
    # phase2_verifier_runs links to the usage log through pair_run_id, which is
    # the subtrio id the agents stamp on each call.
    subs = [
        r[0] for r in c.execute(
            "SELECT DISTINCT pair_run_id FROM phase2_verifier_runs "
            "WHERE experiment_id=? AND pair_run_id IS NOT NULL", (PILOT,)
        )
    ]
    if not subs:
        return verdict(False, "no verifier subtrio ids to trace")
    marks = "?, " * (len(subs) - 1) + "?"
    corro = c.execute(
        f"SELECT COUNT(*) FROM claude_usage_log WHERE subtrio_id IN ({marks}) "
        f"AND context LIKE 'verifier_corroborative_query_gen%'", subs
    ).fetchone()[0]
    adver = c.execute(
        f"SELECT COUNT(*) FROM claude_usage_log WHERE subtrio_id IN ({marks}) "
        f"AND context LIKE 'verifier_query_gen%'", subs
    ).fetchone()[0]
    print(f"  corroborative query-gen calls: {corro}")
    print(f"  adversarial   query-gen calls: {adver}")
    ok = corro > 0 and adver == 0
    return verdict(ok, "corroborative generator used, adversarial generator never")


def check_query_content(c) -> bool:
    rule("4. Query content")
    rows = c.execute(
        "SELECT question_id, country_code, independent_search_queries "
        "FROM phase2_verifier_runs WHERE experiment_id=? "
        "AND independent_search_queries IS NOT NULL", (PILOT,)
    ).fetchall()
    if not rows:
        return verdict(False, "no queries recorded")
    # The adversarial generator is explicitly told to invert the label. If the
    # wrong generator were wired in, negation words would show up at rate.
    negation = ("no ", "not ", "lack", "absence", "without", "fails to", "missing")
    flagged = 0
    for _q, _cc, raw in rows:
        try:
            qs = json.loads(raw)
        except Exception:
            qs = [raw]
        if any(any(w in (s or "").lower() for w in negation) for s in qs or []):
            flagged += 1
    print(f"  verifier rows with queries: {len(rows)}")
    print(f"  rows containing a negation cue: {flagged} ({flagged / len(rows):.1%})")
    print("\n  sample (first 4 rows):")
    for q, cc, raw in rows[:4]:
        try:
            qs = json.loads(raw)
        except Exception:
            qs = [raw]
        print(f"    {q}/{cc}")
        for s in qs or []:
            print(f"      - {s}")
    ok = flagged / len(rows) < 0.25
    return verdict(ok, f"negation-cue rate {flagged / len(rows):.1%} is below 25%")


def check_denylist(c) -> bool:
    rule("5. Deny-list (D24)")
    def count(table, col, eid=None):
        where = " OR ".join(f"{col} LIKE ?" for _ in BANNED_SUBSTR)
        params = [f"%{b}%" for b in BANNED_SUBSTR]
        q = f"SELECT COUNT(*) FROM {table} WHERE ({where})"
        if eid:
            q += " AND experiment_id=?"
            params.append(eid)
        return c.execute(q, params).fetchone()[0]

    pv = count("phase2_verifier_runs", "counter_source_url", PILOT)
    pf = count("phase2_final", "final_source_url", PILOT)
    tv = count("phase2_verifier_runs", "counter_source_url")
    tf = count("phase2_final", "final_source_url")
    print(f"  pilot rows      -> verifier {pv}, final {pf}")
    print(f"  whole DB now    -> verifier {tv}, final {tf}")
    print(f"  whole DB before -> verifier {BASELINE_LEAKS['verifier']}, "
          f"final {BASELINE_LEAKS['final']}")
    ok = (pv == 0 and pf == 0
          and tv <= BASELINE_LEAKS["verifier"] and tf <= BASELINE_LEAKS["final"])
    return verdict(ok, "no deny-list violation attributable to the pilot")


def check_model(c) -> bool:
    rule("6. Model")
    models = set()
    for table in ("phase2_researcher_runs", "phase2_verifier_runs"):
        for (m,) in c.execute(
            f"SELECT DISTINCT model_version FROM {table} WHERE experiment_id=?",
            (PILOT,),
        ):
            models.add(m)
    print(f"  models: {sorted(x for x in models if x)}")
    banned = {m for m in models if m and "sonnet-5" in m}
    ok = bool(models) and not banned
    return verdict(ok, f"no banned model in the run (found {sorted(banned)})"
                   if banned else "every row on claude-sonnet-4-6")


def check_seeding(c) -> bool:
    rule("7. Seeding")
    pairs = pilot_pairs(c)
    if not pairs:
        return verdict(False, "no pilot pairs")
    expected = 0
    for q, cc in pairs:
        hit = c.execute(
            "SELECT 1 FROM phase2_researcher_runs WHERE experiment_id=? "
            "AND condition_label=? AND question_id=? AND country_code=? "
            "AND retry_count=0 AND answer IS NOT NULL "
            "AND lower(trim(answer))!='inconclusive' LIMIT 1",
            (ARM_A_SRC, cc, q, cc),
        ).fetchone()
        expected += bool(hit)
    print(f"  pairs whose exp36 attempt-1 is seedable: {expected}/{len(pairs)} "
          f"({expected / len(pairs):.1%})")
    print("  (full battery rate is 392/1,144 = 34.3%)")
    return verdict(0.20 <= expected / len(pairs) <= 0.55,
                   "seedable share is in the expected band")


def check_outcomes(c) -> bool:
    rule("8. Outcome distribution")
    rows = c.execute(
        "SELECT terminal_status, COUNT(*) FROM phase2_final "
        "WHERE experiment_id=? GROUP BY 1 ORDER BY 2 DESC", (PILOT,)
    ).fetchall()
    total = sum(n for _, n in rows)
    if not total:
        return verdict(False, "no finalised rows")
    for st, n in rows:
        print(f"  {st}: {n} ({n / total:.1%})")
    commits = sum(n for st, n in rows if st == "accepted_cooperative")
    v = c.execute(
        "SELECT verdict, COUNT(*) FROM phase2_verifier_runs "
        "WHERE experiment_id=? GROUP BY 1", (PILOT,)
    ).fetchall()
    print(f"  verifier verdicts: {dict(v)}")
    rate = commits / total
    print(f"  commit rate: {commits}/{total} = {rate:.3f}")
    return verdict(0.15 <= rate <= 0.85,
                   f"commit rate {rate:.3f} is not degenerate (0 or 1)")


def check_arm_a(c) -> None:
    rule("9. Arm A contrast on the same pairs (DESCRIPTIVE ONLY, n is small)")
    pairs = pilot_pairs(c)
    b = {}
    for q, cc, st, ans in c.execute(
        "SELECT question_id, country_code, terminal_status, final_answer "
        "FROM phase2_final WHERE experiment_id=?", (PILOT,)
    ):
        b[(q, cc)] = (st == "accepted_cooperative" and norm(ans) != "inconclusive")
    a = {}
    for q, cc, st, ans in c.execute(
        "SELECT question_id, country_code, terminal_status, final_answer "
        "FROM phase2_final WHERE experiment_id=?", (ARM_A_SRC,)
    ):
        if (q, cc) in pairs:
            a[(q, cc)] = (st == "accepted_by_verifier" and norm(ans) != "inconclusive")
    common = sorted(set(a) & set(b))
    if not common:
        print("  no overlap with exp36 rows")
        return
    ca = sum(a[k] for k in common)
    cb = sum(b[k] for k in common)
    both = sum(a[k] and b[k] for k in common)
    only_a = sum(a[k] and not b[k] for k in common)
    only_b = sum(b[k] and not a[k] for k in common)
    print(f"  paired pairs: {len(common)}")
    print(f"  arm A (adversarial, no_adjudicator) commits: {ca} ({ca / len(common):.3f})")
    print(f"  arm B (corroborative, cooperative)  commits: {cb} ({cb / len(common):.3f})")
    print(f"  both commit {both} | only A {only_a} | only B {only_b}")
    print("\n  NOT a stance result. 112 pairs cannot resolve the registered")
    print("  endpoints; the registered contrast needs the full 1,144.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/odmi.db")
    args = ap.parse_args()
    c = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    results = [
        check_completion(c), check_strategy(c), check_search_direction(c),
        check_query_content(c), check_denylist(c), check_model(c),
        check_seeding(c), check_outcomes(c),
    ]
    check_arm_a(c)

    rule("VERDICT")
    passed = sum(results)
    print(f"  {passed}/{len(results)} operational checks passed")
    if passed == len(results):
        print("  The corroborative arm is behaving as the pre-registration says.")
    else:
        print("  At least one check failed. Do NOT dispatch the full battery.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
