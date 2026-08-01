#!/usr/bin/env python3
"""EXP-42: verifier stance on the held-out eight, registered endpoints.

Arm A  adversarial, `no_adjudicator`, replayed at zero cost from the stored
       `exp36_frozen_headline` rows. Commit iff terminal_status is
       `accepted_by_verifier` and the answer is not `inconclusive`; an
       adjudicated accept becomes an abstention, because without an Adjudicator
       it would never have committed.
Arm B  corroborative, `cooperative`, run live. Commit iff terminal_status is
       `accepted_cooperative` and the answer is not `inconclusive`.

Pre-registered endpoints (docs/EXPERIMENTS_EXP42_STANCE_HELDOUT.md):
  1. commit accuracy on binary golds, paired
  2. negative-gold false-positive rate over ALL negative golds, not just
     committed ones, so an arm cannot look precise by abstaining
  3. paired McNemar on committed-correctness, binary golds only
  4. TOST against a +/-0.05 margin fixed before data, since a McNemar null is
     not an equivalence result

Dedup is mandatory. A pair whose final has no researcher row is invisible to the
orchestrator's resume skip-set and can be re-dispatched, so `phase2_final` may
hold more than one row per pair. Both arms are collapsed to the latest row per
(question_id, country_code), as EXP-36 does.

Usage:
    uv run python evaluation/exp42_analysis.py
"""
from __future__ import annotations

import argparse
import math
import sqlite3
from collections import Counter

ARM_B = "exp42_stance_heldout"
ARM_A = "exp36_frozen_headline"
COUNTRIES = ["FI", "BE", "HR", "BG", "ME", "MK", "BA", "SE"]
TOST_MARGIN = 0.05          # fixed in the pre-registration, before data
COMMIT_A = "accepted_by_verifier"
COMMIT_B = "accepted_cooperative"


def norm(x) -> str:
    return (x or "").strip().lower()


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def binom_two_sided(b: int, cc: int) -> float:
    """Exact McNemar. b, cc are the two discordant counts."""
    n = b + cc
    if n == 0:
        return 1.0
    lo = min(b, cc)
    tail = sum(math.comb(n, k) for k in range(lo + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def canonical(c, eid: str) -> dict:
    """Latest final row per (question_id, country_code)."""
    rows = c.execute(
        "SELECT question_id, country_code, terminal_status, final_answer, MAX(id) "
        "FROM phase2_final WHERE experiment_id=? "
        "GROUP BY question_id, country_code", (eid,)
    ).fetchall()
    return {(q, cc): (st, ans) for q, cc, st, ans, _ in rows}


def deterministic_pairs(c) -> set:
    """Pairs decided by the D30 catalogue recompute rather than by the Verifier.

    On these the Verifier never runs an LLM call: it recomputes the statistic
    from the cached snapshot and passes iff the band matches. Stance cannot
    reach them, so both arms return the same thing by construction (verified:
    32 of 33 identical, the one difference being a snapshot taken at a
    different time, not a stance effect).

    They are therefore excluded from the stance contrast. Keeping them would
    add guaranteed-tied pairs that shrink the observed difference and make
    equivalence easier to declare than the evidence warrants, which matters
    most for the TOST.

    Both arms are scanned. The label differs by run epoch: the EXP-36 rows
    carry `unknown` where the current code writes `deterministic` (the D66
    logging inconsistency), so matching on either alone would miss half.
    """
    out = set()
    for eid in (ARM_B, ARM_A):
        for q, cc in c.execute(
            "SELECT DISTINCT question_id, country_code FROM phase2_verifier_runs "
            "WHERE experiment_id=? AND model_version IN ('deterministic','unknown')",
            (eid,),
        ):
            out.add((q, cc))
    return out


def gold(c) -> dict:
    return {
        (q, cc): norm(r) for q, cc, r in c.execute(
            "SELECT question_id, country_code, response FROM ground_truth "
            f"WHERE country_code IN ({','.join('?' * len(COUNTRIES))})", COUNTRIES
        )
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/odmi.db")
    args = ap.parse_args()
    c = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=30)

    raw_b = c.execute(
        "SELECT COUNT(*) FROM phase2_final WHERE experiment_id=?", (ARM_B,)
    ).fetchone()[0]
    B = canonical(c, ARM_B)
    A_all = canonical(c, ARM_A)
    G = gold(c)

    print("=" * 72)
    print("EXP-42  verifier stance on the held-out eight")
    print("=" * 72)
    print(f"\narm B rows {raw_b}, deduped to {len(B)} pairs "
          f"({raw_b - len(B)} duplicate row(s) collapsed)")
    if len(B) < 1144:
        print(f"*** INCOMPLETE: {len(B)}/1144 pairs. Figures below are interim. ***")

    # restrict both arms to the pairs arm B has actually produced
    all_pairs = sorted(set(B) & set(A_all))
    det = deterministic_pairs(c)
    pairs = [k for k in all_pairs if k not in det]
    dropped = len(all_pairs) - len(pairs)
    print(f"paired against arm A on {len(all_pairs)} pairs")
    print(f"excluding {dropped} decided by the D30 catalogue recompute "
          f"(stance cannot reach them)")
    print(f"stance-sensitive pairs analysed: {len(pairs)}")

    def committed(row, commit_status):
        st, ans = row
        return st == commit_status and norm(ans) != "inconclusive"

    cb = {k: committed(B[k], COMMIT_B) for k in pairs}
    ca = {k: committed(A_all[k], COMMIT_A) for k in pairs}

    # 1. coverage
    print("\n" + "-" * 72)
    print("1. COVERAGE (commit rate)")
    print("-" * 72)
    for lbl, d in (("arm A adversarial", ca), ("arm B corroborative", cb)):
        k = sum(d.values())
        lo, hi = wilson(k, len(pairs))
        print(f"  {lbl:<22} {k:>4}/{len(pairs)} = {k/len(pairs):.3f}  "
              f"[{lo:.3f}, {hi:.3f}]")

    # 2. commit accuracy, binary golds
    print("\n" + "-" * 72)
    print("2. COMMIT ACCURACY on binary golds (of pairs the arm committed)")
    print("-" * 72)
    binary = [k for k in pairs if G.get(k) in ("yes", "no")]
    print(f"  binary-gold pairs in scope: {len(binary)}")
    acc = {}
    for lbl, d, src in (("arm A adversarial", ca, A_all),
                        ("arm B corroborative", cb, B)):
        n = k = 0
        for key in binary:
            if not d[key]:
                continue
            n += 1
            if norm(src[key][1]) == G[key]:
                k += 1
        acc[lbl] = (k, n)
        lo, hi = wilson(k, n)
        print(f"  {lbl:<22} {k:>4}/{n} = {k/max(n,1):.3f}  [{lo:.3f}, {hi:.3f}]")

    # 3. negative-gold FPR over ALL negative golds
    print("\n" + "-" * 72)
    print("3. NEGATIVE-GOLD FALSE-POSITIVE RATE (denominator = all negative golds)")
    print("-" * 72)
    negs = [k for k in pairs if G.get(k) == "no"]
    print(f"  negative golds in scope: {len(negs)}  (full battery holds 370)")
    for lbl, d, src in (("arm A adversarial", ca, A_all),
                        ("arm B corroborative", cb, B)):
        fp = sum(1 for key in negs if d[key] and norm(src[key][1]) == "yes")
        lo, hi = wilson(fp, len(negs))
        print(f"  {lbl:<22} {fp:>4}/{len(negs)} = {fp/max(len(negs),1):.3f}  "
              f"[{lo:.3f}, {hi:.3f}]")

    # 4. paired McNemar on committed-correctness
    print("\n" + "-" * 72)
    print("4. PAIRED McNEMAR, committed-correctness on binary golds")
    print("-" * 72)

    def correct(key, d, src):
        return d[key] and norm(src[key][1]) == G[key]

    only_a = sum(1 for k in binary
                 if correct(k, ca, A_all) and not correct(k, cb, B))
    only_b = sum(1 for k in binary
                 if correct(k, cb, B) and not correct(k, ca, A_all))
    both = sum(1 for k in binary
               if correct(k, ca, A_all) and correct(k, cb, B))
    neither = len(binary) - only_a - only_b - both
    p = binom_two_sided(only_a, only_b)
    print(f"  both correct {both} | only A {only_a} | only B {only_b} | "
          f"neither {neither}")
    print(f"  exact two-sided p = {p:.4f}   (discordant n = {only_a + only_b})")

    # 5. TOST
    print("\n" + "-" * 72)
    print(f"5. TOST equivalence, margin +/-{TOST_MARGIN}")
    print("-" * 72)
    # On DELIVERED accuracy (correct out of every binary pair, an abstention
    # counting as a miss), not commit accuracy. Commit accuracy divides by a
    # different denominator in each arm, so it is not a paired quantity and
    # cannot carry a paired equivalence test. Delivered accuracy gives every
    # pair the same weight in both arms, which is what TOST needs.
    n = len(binary)
    pa = sum(1 for k in binary if correct(k, ca, A_all)) / max(n, 1)
    pb = sum(1 for k in binary if correct(k, cb, B)) / max(n, 1)
    diff = pb - pa
    # paired proportions: SE from the discordant cells (McNemar-style)
    se = math.sqrt(max(only_a + only_b, 1)) / max(n, 1)
    print(f"  arm A correct-of-all {pa:.3f} | arm B {pb:.3f} | diff {diff:+.3f}")
    print(f"  paired SE {se:.4f}")
    if se > 0:
        z_lo = (diff + TOST_MARGIN) / se
        z_hi = (diff - TOST_MARGIN) / se
        def cdf(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))
        p_lo = 1 - cdf(z_lo)      # H0: diff <= -margin
        p_hi = cdf(z_hi)          # H0: diff >= +margin
        p_tost = max(p_lo, p_hi)
        print(f"  TOST p = {p_tost:.4f}  "
              f"({'EQUIVALENT within margin' if p_tost < 0.05 else 'NOT equivalent: cannot rule out a difference beyond the margin'})")

    # per country
    print("\n" + "-" * 72)
    print("PER COUNTRY (commit rate, arm B)")
    print("-" * 72)
    per = Counter()
    tot = Counter()
    for (q, cc) in pairs:
        tot[cc] += 1
        per[cc] += cb[(q, cc)]
    for cc in COUNTRIES:
        if tot[cc]:
            print(f"  {cc}  {per[cc]:>3}/{tot[cc]:<4} = {per[cc]/tot[cc]:.3f}")

    print("\n" + "=" * 72)
    if len(B) < 1144:
        print("INTERIM. Do not report these figures; the battery is unfinished.")
    else:
        print("Complete battery. These are the registered endpoints.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
