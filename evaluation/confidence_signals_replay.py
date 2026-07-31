#!/usr/bin/env python3
"""Step 1 (free replay): do the signals ALREADY in the DB predict correctness
better than the self-reported answer_confidence the floor currently gates on?

The confidence deep dive showed answer_confidence is a near-chance correctness
ranker (AUROC ~0.55) because it encodes the label, not the evidence: AUROC 0.84
within positive golds, 0.17 within negative golds. This asks whether a more
DETERMINISTIC score, built from columns the swarm already stores but does not
gate on, does better, especially whether any of them are NOT anti-predictive on
the negative class.

Signals tested (per committed binary pair vs yes/no gold):
  answer_confidence    self-reported (the incumbent floor signal)
  retrieval_confidence self-reported source-reality confidence
  domain_trust_score   DETERMINISTIC (validator.py); computed, stored, gates
                       nothing today (decision VAL-4)
  verifier_confidence  the Verifier's confidence in its own verdict
  substring_pass       DETERMINISTIC: the verbatim-quote gate result (1/0)
  combos               label-neutral products of the above

Endpoint per signal: AUROC vs correctness, overall and split within positive
and within negative golds (the split that exposes the label-coupling). Higher
is better; a within-negative AUROC above 0.5 means the signal is NOT
anti-predictive there, which answer_confidence (0.17) fails.

Read-only. No LLM calls.
  uv run python evaluation/confidence_signals_replay.py --db /abs/path/odmi.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "data" / "odmi.db"
RESULTS = REPO / "evaluation" / "results" / "confidence_signals_replay.json"

ABST = {"inconclusive", "not_applicable", "not applicable", "other",
        "i don't know", "idk", "", None}
DEV = {"NL", "MT", "NO", "FR", "AL"}


def norm(s):
    return (s or "").strip().lower()


def auroc(scores, labels):
    """P(score of a positive > score of a negative), ties .5; None if degenerate."""
    pairs = sorted(zip(scores, labels))
    n = len(pairs)
    npos = sum(labels)
    nneg = n - npos
    if npos == 0 or nneg == 0:
        return None
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and pairs[j][0] == pairs[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = avg
        i = j
    sum_pos = sum(ranks[k] for k in range(n) if pairs[k][1] == 1)
    return (sum_pos - npos * (npos + 1) / 2.0) / (npos * nneg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--countries", nargs="*", default=None,
                    help="restrict to these country codes (default: all)")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    n_final = con.execute("SELECT COUNT(*) FROM phase2_final").fetchone()[0]

    shape = {r["question_id"]: (r["answer_shape"] or "binary")
             for r in con.execute("SELECT question_id, answer_shape FROM questions")}

    def is_correct(qid, ans, gold):
        a, g = norm(ans), norm(gold)
        if not g or a in ABST:
            return False
        if a == g:
            return True
        if shape.get(qid, "binary") == "binary":
            return (a == "yes" and g.startswith("yes")) or (a == "no" and g == "no")
        return False

    # latest researcher run per pair carrying a committed answer (for the
    # deterministic domain_trust_score and the self-reported retrieval conf)
    res = {}
    for r in con.execute(
        "SELECT pair_run_id, retry_count, id, answer, domain_trust_score, "
        "retrieval_confidence, answer_confidence FROM phase2_researcher_runs "
        "ORDER BY retry_count, id"):
        if norm(r["answer"]) not in ABST:
            res[r["pair_run_id"]] = r  # last committed wins
    # latest verifier run per pair (substring gate + verifier confidence)
    ver = {}
    for r in con.execute(
        "SELECT pair_run_id, retry_count, id, substring_check_result, "
        "verifier_confidence, verdict FROM phase2_verifier_runs "
        "ORDER BY retry_count, id"):
        ver[r["pair_run_id"]] = r

    gt = {(r["question_id"], r["country_code"]): r["response"]
          for r in con.execute("SELECT question_id, country_code, response FROM ground_truth")}

    rows = []
    for f in con.execute("SELECT * FROM phase2_final"):
        if shape.get(f["question_id"]) != "binary":
            continue
        gold = gt.get((f["question_id"], f["country_code"]))
        if norm(gold) not in ("yes", "no"):
            continue
        if norm(f["final_answer"]) in ABST:
            continue
        if args.countries and f["country_code"] not in args.countries:
            continue
        rr = res.get(f["pair_run_id"])
        vv = ver.get(f["pair_run_id"])
        substr = vv["substring_check_result"] if vv else None
        rows.append(dict(
            cc=f["country_code"],
            correct=int(is_correct(f["question_id"], f["final_answer"], gold)),
            gold_neg=norm(gold) == "no",
            answer_confidence=f["final_answer_confidence"],
            retrieval_confidence=(f["final_retrieval_confidence"]
                                  if f["final_retrieval_confidence"] is not None
                                  else (rr["retrieval_confidence"] if rr else None)),
            domain_trust_score=(rr["domain_trust_score"] if rr else None),
            verifier_confidence=(vv["verifier_confidence"] if vv else None),
            substring_pass=(1.0 if substr == "pass" else 0.0 if substr in ("fail", "not_attempted") else None),
        ))

    # derived combos (only where both parts present)
    for r in rows:
        rc, dt, sp = r["retrieval_confidence"], r["domain_trust_score"], r["substring_pass"]
        r["combo_ret_x_trust"] = (rc * dt) if (rc is not None and dt is not None) else None
        r["combo_ret_x_trust_x_substr"] = (
            rc * dt * (0.5 + 0.5 * sp)
            if (rc is not None and dt is not None and sp is not None) else None)

    SIGNALS = ["answer_confidence", "retrieval_confidence", "domain_trust_score",
               "verifier_confidence", "substring_pass",
               "combo_ret_x_trust", "combo_ret_x_trust_x_substr"]

    def evaluate(pop, label):
        print(f"\n--- {label} (n={len(pop)}) ---")
        print(f"  {'signal':30s} {'cover':>6s} {'AUROC':>7s} {'within+':>8s} {'within-':>8s}")
        out = {}
        pos = [r for r in pop if not r["gold_neg"]]
        neg = [r for r in pop if r["gold_neg"]]
        for s in SIGNALS:
            have = [r for r in pop if r[s] is not None]
            cover = len(have) / len(pop) if pop else 0
            a = auroc([r[s] for r in have], [r["correct"] for r in have])
            havep = [r for r in pos if r[s] is not None]
            haven = [r for r in neg if r[s] is not None]
            ap_ = auroc([r[s] for r in havep], [r["correct"] for r in havep])
            an_ = auroc([r[s] for r in haven], [r["correct"] for r in haven])
            fmt = lambda x: "  n/a" if x is None else f"{x:.3f}"
            print(f"  {s:30s} {cover:6.0%} {fmt(a):>7s} {fmt(ap_):>8s} {fmt(an_):>8s}")
            out[s] = dict(coverage=cover, auroc=a, within_pos=ap_, within_neg=an_,
                          n=len(have))
        return out

    print("=" * 76)
    print("STEP 1  —  do stored signals beat answer_confidence as a correctness ranker?")
    print(f"DB: {args.db}  ({n_final} phase2_final rows)")
    print("AUROC vs correctness; within+ / within- = AUROC inside positive / negative golds.")
    print("answer_confidence is the incumbent floor signal (target to beat).")
    print("=" * 76)

    result = {"_db": args.db, "_n_final": n_final, "cuts": {}}
    result["cuts"]["pooled"] = evaluate(rows, "pooled (all rows, all experiments)")
    result["cuts"]["dev"] = evaluate([r for r in rows if r["cc"] in DEV],
                                     "dev countries (NL MT NO FR AL)")
    result["cuts"]["NL"] = evaluate([r for r in rows if r["cc"] == "NL"],
                                    "NL only (the negative-rich set)")

    if args.json:
        RESULTS.parent.mkdir(exist_ok=True)
        RESULTS.write_text(json.dumps(result, indent=2, default=str))
        print(f"\nWrote {RESULTS}")
    con.close()


if __name__ == "__main__":
    main()
