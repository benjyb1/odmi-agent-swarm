#!/usr/bin/env python3
"""EXP-28/29 analysis: architecture ablation ladder + model contrast.

Balance-aware (R4) per-arm report over the 156-pair dev battery, plus the
pre-registered paired McNemar comparisons on overlapping committed sets
(R10, Holm-corrected within the EXP-28 three-comparison family).

Canonical row rule (runbook): latest phase2_final per (question, country,
condition); duplicates from interrupted runs are superseded by the latest.

Usage:
    uv run python evaluation/analyze_exp28.py
    uv run python evaluation/analyze_exp28.py --json evaluation/results/exp28.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "odmi.db"
sys.path.insert(0, str(REPO))

from evaluation.stats import wilson_interval, mcnemar_exact  # noqa: E402

ARMS = [
    ("exp28_arch_ablation", "trio_s5"),
    ("exp28_arch_ablation", "no_adjudicator_s5"),
    ("exp28_arch_ablation", "researcher_only_s5"),
    ("exp29_sonnet5_model", "trio_s46"),
]
COMPARISONS = [
    # (label, arm_a, arm_b) — pre-registered ladder + model contrast.
    ("adjudicator (trio vs no_adjudicator)", "trio_s5", "no_adjudicator_s5"),
    ("verifier loop (no_adjudicator vs researcher_only)",
     "no_adjudicator_s5", "researcher_only_s5"),
    ("whole layer (trio vs researcher_only)", "trio_s5", "researcher_only_s5"),
    ("model (trio_s46 vs trio_s5)", "trio_s46", "trio_s5"),
]

_NORM = "REPLACE(LOWER(TRIM({x})), '_', ' ')"


def _norm(s: str | None) -> str:
    return (s or "").strip().lower().replace("_", " ")


def load_arm(conn, experiment_id: str, condition_label: str):
    """Canonical rows for one arm: latest final per pair, joined to gold."""
    rows = conn.execute(
        """
        SELECT f.question_id, f.country_code, f.terminal_status,
               f.final_answer, f.final_answer_confidence, f.retry_count,
               f.adjudicator_involved, f.cumulative_cost_usd,
               f.cumulative_wall_clock_ms, gt.response AS gold, gt.decision,
               f.created_at
        FROM phase2_final f
        JOIN phase2_researcher_runs r
          ON r.pair_run_id = f.pair_run_id AND r.retry_count = 0
        JOIN ground_truth gt
          ON gt.question_id = f.question_id
         AND gt.country_code = f.country_code
        WHERE f.experiment_id = ? AND r.condition_label = ?
        ORDER BY f.created_at
        """,
        (experiment_id, condition_label),
    ).fetchall()
    canonical = {}
    for r in rows:  # latest wins
        canonical[(r["question_id"], r["country_code"])] = r
    return canonical


def classify(row) -> str:
    """three-outcome: correct / wrong / abstain (+ failure)."""
    if row["terminal_status"] == "agent_failure":
        return "failure"
    ans = _norm(row["final_answer"])
    if not ans or ans == "inconclusive":
        return "abstain"
    gold = _norm(row["gold"])
    if ans == gold:
        return "correct"
    # bare yes vs 'yes, ...' band golds: count as correct only on exact
    # binary gold, consistent with the strict cut in _MATCH_STATUS_SQL.
    if ans == "yes" and gold.startswith("yes") and gold != "yes":
        return "wrong"  # under-specified on a band gold (strict)
    return "wrong"


def arm_summary(canonical) -> dict:
    n = len(canonical)
    out = {"n_finalised": n, "correct": 0, "wrong": 0, "abstain": 0,
           "failure": 0, "cost_usd": 0.0}
    yes_gold = {"correct": 0, "wrong": 0, "abstain": 0, "n": 0}
    no_gold = {"correct": 0, "wrong": 0, "abstain": 0, "n": 0}
    for row in canonical.values():
        c = classify(row)
        if c == "failure":
            out["failure"] += 1
            continue
        out[c] += 1
        out["cost_usd"] += row["cumulative_cost_usd"] or 0.0
        gold = _norm(row["gold"])
        bucket = no_gold if gold == "no" else (
            yes_gold if gold.startswith("yes") else None)
        if bucket is not None:
            bucket["n"] += 1
            bucket[c] += 1
    committed = out["correct"] + out["wrong"]
    out["coverage"] = committed / n if n else None
    out["commit_precision"] = out["correct"] / committed if committed else None
    if committed:
        lo, hi = wilson_interval(out["correct"], committed)
        out["commit_precision_ci"] = [round(lo, 3), round(hi, 3)]
    # per-class (binary golds only)
    for name, b in (("yes_gold", yes_gold), ("no_gold", no_gold)):
        com = b["correct"] + b["wrong"]
        out[name] = {
            "n": b["n"], "recall": b["correct"] / b["n"] if b["n"] else None,
            "committed": com, "abstain": b["abstain"],
            "fp_rate_committed": b["wrong"] / com if com else None,
        }
    tpr = out["yes_gold"]["recall"]
    tnr = out["no_gold"]["recall"]
    out["balanced_accuracy"] = (
        (tpr + tnr) / 2 if tpr is not None and tnr is not None else None
    )
    return out


def paired_mcnemar(a, b):
    """On pairs BOTH arms committed: b = a correct & b wrong, c = reverse."""
    both = set(a) & set(b)
    x_only = y_only = 0
    for k in both:
        ca, cb = classify(a[k]), classify(b[k])
        if ca not in ("correct", "wrong") or cb not in ("correct", "wrong"):
            continue
        if ca == "correct" and cb == "wrong":
            x_only += 1
        elif ca == "wrong" and cb == "correct":
            y_only += 1
    return {"n_overlap_committed_pairs": len(both),
            "a_correct_b_wrong": x_only, "a_wrong_b_correct": y_only,
            "p": mcnemar_exact(x_only, y_only)}


def holm(pvals: list[float]) -> list[float]:
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m = len(pvals)
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row

    arms = {}
    for eid, label in ARMS:
        arms[label] = load_arm(conn, eid, label)

    report = {"arms": {}, "comparisons": {}}
    print(f"{'arm':>20} {'n':>4} {'cov':>6} {'prec':>6} {'balacc':>7} "
          f"{'TPR':>6} {'TNR':>6} {'FPcom':>6} {'abst':>5} {'£':>7}")
    for label, canonical in arms.items():
        s = arm_summary(canonical)
        report["arms"][label] = s

        def fmt(v):
            return f"{v:.3f}" if isinstance(v, float) else "-"
        print(f"{label:>20} {s['n_finalised']:>4} {fmt(s['coverage']):>6} "
              f"{fmt(s['commit_precision']):>6} {fmt(s['balanced_accuracy']):>7} "
              f"{fmt(s['yes_gold']['recall']):>6} {fmt(s['no_gold']['recall']):>6} "
              f"{fmt(s['no_gold']['fp_rate_committed']):>6} "
              f"{s['abstain']:>5} {s['cost_usd']*0.79:>7.2f}")

    exp28_ps = []
    for label, a_lbl, b_lbl in COMPARISONS:
        cmp_res = paired_mcnemar(arms[a_lbl], arms[b_lbl])
        report["comparisons"][label] = cmp_res
        if "model" not in label:
            exp28_ps.append(cmp_res["p"])
        print(f"\n{label}: overlap={cmp_res['n_overlap_committed_pairs']} "
              f"a+/b-={cmp_res['a_correct_b_wrong']} "
              f"a-/b+={cmp_res['a_wrong_b_correct']} p={cmp_res['p']:.4f}")
    if exp28_ps:
        adj = holm(exp28_ps)
        report["exp28_holm_adjusted_p"] = adj
        print(f"\nEXP-28 family Holm-adjusted p: "
              f"{[f'{p:.4f}' for p in adj]}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
