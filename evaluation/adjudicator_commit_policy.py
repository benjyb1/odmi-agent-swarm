"""Rec-3 experiment: confidence-ranked candidate selection at adjudication.

The attribution showed the Adjudicator abstains on far more correct candidates
than it rescues wrong ones (42 vs 2), and that an oracle selecting the
gold-correct candidate the Researcher already produced would score 74% on Malta
against the observed 44%. The verifier programme independently found the
Adjudicator is the load-bearing decider and flagged its conservatism as the
cleanest open question (VERIFIER_FINDINGS.md section 7.1). This tests one
realistic, no-oracle selection policy against the observed Adjudicator decision.

Free replay over stored trails, no API calls. Unit: gold-bearing pairs that
reached adjudication (`adjudicator_involved = 1`) or escalated, the tail where
the Adjudicator's choice differs from a bare floor. Paired (same pairs, every
policy), MT primary (base-rate balanced, R4). The false-positive rate on
negative golds is the co-primary: a policy that recovers by committing more
`yes` must show up here, so it cannot be passed off as recovery.

Policies (none sees the gold):
  observed     the actual finalised answer (the Adjudicator's decision).
  confrank     across all definite Researcher attempts in the trail, commit the
               highest answer_confidence one iff it clears the 0.65 floor, else
               inconclusive. The realistic version of the oracle bound.
  confrank_adj confrank, but the Adjudicator's own answer+confidence joins the
               candidate pool (so a confident adjudication can still win).

Endpoints per policy and country: committed share, recovery (match vs gold over
all pairs), committed accuracy, false positives on negative (binary `no`) golds,
abstention. Paired McNemar (recovery, and committed-wrong) confrank vs observed.

Usage:
  uv run python evaluation/adjudicator_commit_policy.py --countries MT NO FR
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.stats import mcnemar_exact, wilson_interval
from evaluation.stack_attribution import answers_match, is_definite, _norm

DB_PATH = REPO_ROOT / "data" / "odmi.db"
FLOOR = 0.65


def _wilson(k: int, n: int) -> str:
    if n == 0:
        return "n=0"
    lo, hi = wilson_interval(k, n)
    return f"{k}/{n} = {k / n:.2f} [{lo:.2f}, {hi:.2f}]"


def load(conn, countries):
    ph = ",".join("?" for _ in countries)
    qshape = {r["question_id"]: r["answer_shape"]
              for r in conn.execute("SELECT question_id, answer_shape FROM questions")}
    gold = {(r["question_id"], r["country_code"]): r["response"]
            for r in conn.execute(
                f"SELECT question_id, country_code, response FROM ground_truth "
                f"WHERE country_code IN ({ph}) AND response IS NOT NULL AND TRIM(response) <> ''",
                countries)}
    attempts = defaultdict(list)
    for r in conn.execute(
        f"""SELECT pair_run_id, question_id, country_code, retry_count, answer, answer_confidence
            FROM phase2_researcher_runs
            WHERE country_code IN ({ph}) AND experiment_id IS NULL
            ORDER BY pair_run_id, retry_count, id""", countries):
        attempts[r["pair_run_id"]].append(dict(r))
    adj = {}
    for r in conn.execute(
        f"""SELECT pair_run_id, adjudicator_answer, adjudicator_confidence
            FROM phase2_adjudications WHERE country_code IN ({ph}) AND experiment_id IS NULL""",
        countries):
        adj[r["pair_run_id"]] = dict(r)
    finals = [dict(r) for r in conn.execute(
        f"""SELECT pair_run_id, question_id, country_code, final_answer,
                   terminal_status, adjudicator_involved
            FROM phase2_final WHERE country_code IN ({ph}) AND experiment_id IS NULL""",
        countries)]
    return qshape, gold, attempts, adj, finals


def best_definite(pool):
    """Highest-confidence definite (answer, conf) in the pool, or None."""
    cands = [(a["answer"], a["answer_confidence"] or 0.0) for a in pool
             if is_definite(a["answer"])]
    return max(cands, key=lambda x: x[1]) if cands else None


def decide(policy, f, attempts, adj):
    if policy == "observed":
        a = f["final_answer"]
        return a if is_definite(a) and f["terminal_status"] in (
            "accepted_by_verifier", "accepted_by_adjudicator") else None
    pool = list(attempts.get(f["pair_run_id"], []))
    if policy == "confrank_adj" and f["pair_run_id"] in adj:
        ar = adj[f["pair_run_id"]]
        pool = pool + [{"answer": ar["adjudicator_answer"],
                        "answer_confidence": ar["adjudicator_confidence"]}]
    best = best_definite(pool)
    if best and best[1] >= FLOOR:
        return best[0]
    return None


def summarise(rows, gold, qshape, attempts, adj, policy):
    committed = correct = fp_neg = n_neg = 0
    for f in rows:
        g = gold[(f["question_id"], f["country_code"])]
        shape = qshape.get(f["question_id"])
        neg = shape == "binary" and _norm(g) == "no"
        n_neg += neg
        a = decide(policy, f, attempts, adj)
        if a is None:
            continue
        committed += 1
        ok = answers_match(a, g, shape)
        correct += ok
        if neg and not ok:
            fp_neg += 1
    n = len(rows)
    return {
        "committed": f"{committed}/{n}",
        "recovery_over_all_pairs": _wilson(correct, n),
        "committed_accuracy": _wilson(correct, committed),
        "fp_on_negative_golds": _wilson(fp_neg, n_neg) if n_neg else "n/a",
        "abstention": round(1 - committed / n, 2) if n else None,
    }


def paired(rows, gold, qshape, attempts, adj, a_pol, b_pol):
    """McNemar on recovery and on committed-wrong, a_pol vs b_pol."""
    rec_a_only = rec_b_only = fp_a_only = fp_b_only = 0
    for f in rows:
        g = gold[(f["question_id"], f["country_code"])]
        shape = qshape.get(f["question_id"])
        out = {}
        for pol in (a_pol, b_pol):
            a = decide(pol, f, attempts, adj)
            ok = a is not None and answers_match(a, g, shape)
            wrong = a is not None and not ok
            out[pol] = (ok, wrong)
        if out[a_pol][0] and not out[b_pol][0]:
            rec_a_only += 1
        if out[b_pol][0] and not out[a_pol][0]:
            rec_b_only += 1
        if out[a_pol][1] and not out[b_pol][1]:
            fp_a_only += 1
        if out[b_pol][1] and not out[a_pol][1]:
            fp_b_only += 1
    return {
        "recovery_discordant": {f"{a_pol}_only": rec_a_only, f"{b_pol}_only": rec_b_only,
                                "p": round(mcnemar_exact(rec_a_only, rec_b_only), 4)},
        "committed_wrong_discordant": {f"{a_pol}_only": fp_a_only, f"{b_pol}_only": fp_b_only,
                                       "p": round(mcnemar_exact(fp_a_only, fp_b_only), 4)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", default=["MT", "NO", "FR"])
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    qshape, gold, attempts, adj, finals = load(conn, args.countries)

    report = {}
    for cc in args.countries:
        allrows = [f for f in finals if f["country_code"] == cc
                   and (f["question_id"], cc) in gold]
        adjrows = [f for f in allrows if f["adjudicator_involved"]
                   or f["terminal_status"].startswith("escalated")]
        if not allrows:
            continue
        block = {"n_all": len(allrows), "n_adjudication_tail": len(adjrows)}
        for scope, rows in (("all_pairs", allrows), ("adjudication_tail", adjrows)):
            block[scope] = {
                pol: summarise(rows, gold, qshape, attempts, adj, pol)
                for pol in ("observed", "confrank", "confrank_adj")
            }
            block[scope]["paired_confrank_vs_observed"] = paired(
                rows, gold, qshape, attempts, adj, "confrank", "observed")
        report[cc] = block

    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text)


if __name__ == "__main__":
    main()
