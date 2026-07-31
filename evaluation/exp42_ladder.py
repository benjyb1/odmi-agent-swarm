#!/usr/bin/env python3
"""The architecture ladder and the verifier-stance contrast, on the held-out 1,144.

Section 4.2's ladder currently runs on the 156-pair dev battery. This is the
same ladder on the eight held-out countries the results chapter is framed
around, at seven times the power, and it costs nothing to produce: EXP-36 is a
completed trio run, so every rung below it is recoverable from its stored rows.

  1 researcher_only   attempt-1 answer at or above the D37 0.65 floor
  2 no_adjudicator    commit iff terminal_status == accepted_by_verifier
  3 trio              the EXP-36 outcome as it stands
  4 cooperative       EXP-42 arm B, the corroborative verifier (the one live arm)

Reconstructing backwards off a finished trio is not the same as building
forwards, and the difference matters. In the trio the Verifier's rejection is
what triggers a divergent-query retry, so attempt 2+ evidence exists *because*
the Verifier pushed for it. Replaying backwards keeps that causal chain intact.
Running researcher-only first and bolting a Verifier onto those attempt-1
answers would produce a Verifier arm that never retried, at roughly 50k calls
for a worse answer.

Metrics follow the house set in docs/RESULTS.md: coverage, commit accuracy,
negative-gold FPR, balanced accuracy, Youden's J. Wilson intervals throughout,
exact McNemar between adjacent rungs.

Usage:
    uv run python evaluation/exp42_ladder.py [--db PATH] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3

TRIO_RUN = "exp36_frozen_headline"
COOP_RUN = "exp42_stance_heldout"
COUNTRIES = ["FI", "BE", "HR", "BG", "ME", "MK", "BA", "SE"]
FLOOR = 0.65


def norm(x) -> str:
    return (x or "").strip().lower()


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((centre - half) / d, (centre + half) / d)


def mcnemar(b: int, c_: int) -> float:
    n = b + c_
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c_) + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def canonical(conn, eid: str) -> dict:
    """Latest final per pair. phase2_final can hold duplicates: a final with no
    researcher row is invisible to the orchestrator's resume skip-set."""
    return {
        (q, cc): (st, a) for q, cc, st, a, _ in conn.execute(
            "SELECT question_id, country_code, terminal_status, final_answer, "
            "MAX(id) FROM phase2_final WHERE experiment_id=? "
            "GROUP BY question_id, country_code", (eid,))
    }


def build(conn):
    trio = canonical(conn, TRIO_RUN)
    coop = canonical(conn, COOP_RUN)
    attempt1 = {
        (q, cc): (a, conf) for q, cc, a, conf in conn.execute(
            "SELECT question_id, country_code, answer, answer_confidence "
            "FROM phase2_researcher_runs WHERE experiment_id=? AND retry_count=0 "
            "ORDER BY id", (TRIO_RUN,))
    }
    gold = {
        (q, cc): norm(r) for q, cc, r in conn.execute(
            "SELECT question_id, country_code, response FROM ground_truth "
            f"WHERE country_code IN ({','.join('?' * len(COUNTRIES))})", COUNTRIES)
    }
    pairs = sorted(trio)

    def researcher_only(k):
        a, conf = attempt1.get(k, (None, None))
        ok = bool(a) and norm(a) != "inconclusive" and (conf or 0) >= FLOOR
        return ok, a

    def no_adjudicator(k):
        st, a = trio[k]
        return st == "accepted_by_verifier" and norm(a) != "inconclusive", a

    def full_trio(k):
        st, a = trio[k]
        return (st in ("accepted_by_verifier", "accepted_by_adjudicator")
                and norm(a) != "inconclusive"), a

    def cooperative(k):
        if k not in coop:
            return False, None
        st, a = coop[k]
        return st == "accepted_cooperative" and norm(a) != "inconclusive", a

    arms = [
        ("researcher_only", researcher_only),
        ("no_adjudicator", no_adjudicator),
        ("trio", full_trio),
        ("cooperative", cooperative),
    ]
    return pairs, gold, arms, attempt1


def score(pairs, gold, fn):
    binaries = [k for k in pairs if gold.get(k) in ("yes", "no")]
    negs = [k for k in pairs if gold.get(k) == "no"]
    poss = [k for k in pairs if gold.get(k) == "yes"]

    committed = sum(1 for k in pairs if fn(k)[0])
    n = ok = 0
    for k in binaries:
        c, a = fn(k)
        if c:
            n += 1
            ok += (norm(a) == gold[k])
    fp = sum(1 for k in negs if fn(k)[0] and norm(fn(k)[1]) == "yes")
    # balanced accuracy / Youden J over ALL binary golds, an abstention counting
    # as a miss, so an arm cannot look good by declining to answer.
    tp = sum(1 for k in poss if fn(k)[0] and norm(fn(k)[1]) == "yes")
    tn = sum(1 for k in negs if fn(k)[0] and norm(fn(k)[1]) == "no")
    tpr = tp / len(poss) if poss else 0.0
    tnr = tn / len(negs) if negs else 0.0
    return {
        "coverage": committed / len(pairs),
        "coverage_ci": wilson(committed, len(pairs)),
        "committed": committed,
        "commit_acc": ok / max(n, 1),
        "commit_acc_ci": wilson(ok, max(n, 1)),
        "commit_acc_n": n,
        "neg_fpr": fp / max(len(negs), 1),
        "neg_fpr_ci": wilson(fp, max(len(negs), 1)),
        "neg_fp": fp, "neg_total": len(negs),
        "balanced_acc": (tpr + tnr) / 2,
        "youden_j": tpr + tnr - 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/Users/benjyb/Desktop/MscProject/data/odmi.db")
    ap.add_argument("--json", default="evaluation/results/exp42_ladder.json")
    args = ap.parse_args()
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=30)

    pairs, gold, arms, attempt1 = build(conn)
    binaries = [k for k in pairs if gold.get(k) in ("yes", "no")]
    negs = [k for k in pairs if gold.get(k) == "no"]
    missing_a1 = sum(1 for k in pairs if k not in attempt1)

    print("=" * 78)
    print("ARCHITECTURE LADDER AND VERIFIER STANCE, held-out eight")
    print("=" * 78)
    print(f"\npairs {len(pairs)} | binary golds {len(binaries)} | "
          f"negative golds {len(negs)}")
    print(f"pairs with no attempt-1 researcher row: {missing_a1} "
          f"(catalogue-computed or seeded; counted as abstentions in arm 1)")

    print(f"\n{'arm':<18}{'coverage':>10}{'commit-acc':>12}"
          f"{'neg-gold FPR':>16}{'bal-acc':>9}{'J':>8}")
    print("-" * 78)
    results = {}
    for name, fn in arms:
        s = score(pairs, gold, fn)
        results[name] = s
        print(f"{name:<18}{s['coverage']:>10.3f}{s['commit_acc']:>12.3f}"
              f"{s['neg_fpr']:>10.3f} ({s['neg_fp']:>3}/{s['neg_total']})"
              f"{s['balanced_acc']:>9.3f}{s['youden_j']:>8.3f}")

    print("\nWilson 95% intervals")
    for name, _ in arms:
        s = results[name]
        print(f"  {name:<18} coverage [{s['coverage_ci'][0]:.3f}, "
              f"{s['coverage_ci'][1]:.3f}]  commit-acc "
              f"[{s['commit_acc_ci'][0]:.3f}, {s['commit_acc_ci'][1]:.3f}]  "
              f"FPR [{s['neg_fpr_ci'][0]:.3f}, {s['neg_fpr_ci'][1]:.3f}]")

    print("\nPaired exact McNemar between adjacent rungs "
          "(committed-correctness, binary golds)")
    fns = dict(arms)
    def correct(k, fn):
        c, a = fn(k)
        return c and norm(a) == gold[k]
    comparisons = [
        ("researcher_only", "no_adjudicator"),
        ("no_adjudicator", "trio"),
        ("no_adjudicator", "cooperative"),
    ]
    tests = {}
    for x, y in comparisons:
        fx, fy = fns[x], fns[y]
        only_x = sum(1 for k in binaries if correct(k, fx) and not correct(k, fy))
        only_y = sum(1 for k in binaries if correct(k, fy) and not correct(k, fx))
        p = mcnemar(only_x, only_y)
        tests[f"{x}_vs_{y}"] = {"only_first": only_x, "only_second": only_y, "p": p}
        print(f"  {x} vs {y}: {only_x} vs {only_y}, p = {p:.4f}")

    print("\nNegative-gold false positives, paired")
    for x, y in comparisons:
        fx, fy = fns[x], fns[y]
        def isfp(k, fn):
            c, a = fn(k)
            return c and norm(a) == "yes"
        ox = sum(1 for k in negs if isfp(k, fx) and not isfp(k, fy))
        oy = sum(1 for k in negs if isfp(k, fy) and not isfp(k, fx))
        p = mcnemar(ox, oy)
        tests[f"fpr_{x}_vs_{y}"] = {"only_first": ox, "only_second": oy, "p": p}
        print(f"  {x} vs {y}: {ox} vs {oy}, p = {p:.4f}")

    out = {
        "battery": {"pairs": len(pairs), "binary_golds": len(binaries),
                    "negative_golds": len(negs),
                    "pairs_without_attempt1": missing_a1},
        "arms": {k: {kk: (list(vv) if isinstance(vv, tuple) else vv)
                     for kk, vv in v.items()} for k, v in results.items()},
        "tests": tests,
        "provenance": {"trio_run": TRIO_RUN, "cooperative_run": COOP_RUN,
                       "floor": FLOOR,
                       "note": "rungs 1-3 are zero-cost replays off the trio run"},
    }
    import pathlib
    p = pathlib.Path(args.json)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2))
    print(f"\nwritten: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
