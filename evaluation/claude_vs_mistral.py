"""Compare a Mistral swarm arm against the Claude baseline on the same pairs.

This is the read-out for the cross-family cost/accuracy experiment (EXP-9). It
takes two sets of finalised pairs, classifies each against ODMI ground truth
with the SAME CASE the dashboard uses (`dashboard.lib.db._MATCH_STATUS_SQL`, so
the numbers cannot drift from the rest of the project), restricts to the pairs
present in BOTH arms (a paired comparison), and prints per-arm accuracy,
abstention, modelled cost and tokens, plus how often the two arms landed on the
same final answer.

Cost note: the baseline `cumulative_cost_usd` is the arithmetic-equivalent
Claude price (the call was free under Max). The Mistral `cumulative_cost_usd` is
the real Mistral list price. Both are reported so the trade-off the experiment
exists to measure (accuracy lost vs cost saved) is on one screen. They are
different cost bases and are labelled as such, never summed.

Usage:
    # Mistral arm dispatched with --experiment-id exp9_mistral, baseline = main runs
    uv run python evaluation/claude_vs_mistral.py --mistral-experiment exp9_mistral

    # both arms tagged as experiments
    uv run python evaluation/claude_vs_mistral.py \
        --mistral-experiment exp9_mistral --baseline-experiment exp9_claude
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from dashboard.lib.db import _MATCH_STATUS_SQL

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "odmi.db"

_USD_TO_GBP = 0.79  # mirrors dashboard/lib/currency.py


def _arm_filter(experiment_id: str | None) -> tuple[str, list]:
    """SQL predicate + params selecting one arm by experiment_id.

    None means the main-run baseline (experiment_id IS NULL, D27).
    """
    if experiment_id is None:
        return "f.experiment_id IS NULL", []
    return "f.experiment_id = ?", [experiment_id]


def _load_arm(conn: sqlite3.Connection, experiment_id: str | None) -> dict:
    """One row per finalised pair for an arm, keyed by (question_id, country)."""
    pred, params = _arm_filter(experiment_id)
    rows = conn.execute(
        f"""
        SELECT
            f.question_id, f.country_code,
            f.final_answer,
            f.cumulative_cost_usd,
            f.cumulative_input_tokens, f.cumulative_output_tokens,
            f.cumulative_wall_clock_ms,
            s.adjudicator_model,
            gt.response AS odmi_response,
            {_MATCH_STATUS_SQL} AS match_status
        FROM phase2_final f
        LEFT JOIN subtrio_status s ON s.subtrio_id = f.pair_run_id
        LEFT JOIN ground_truth gt
              ON gt.question_id = f.question_id
             AND gt.country_code = f.country_code
        WHERE {pred}
        """,
        params,
    ).fetchall()
    out = {}
    for r in rows:
        out[(r[0], r[1])] = {
            "final_answer": r[2],
            "cost_usd": r[3] or 0.0,
            "in_tok": r[4] or 0,
            "out_tok": r[5] or 0,
            "wall_ms": r[6] or 0,
            "model": r[7],
            "odmi": r[8],
            "match_status": r[9],
        }
    return out


def _summarise(name: str, pairs: dict) -> None:
    n = len(pairs)
    if n == 0:
        print(f"\n[{name}] no pairs found.")
        return
    counts: dict[str, int] = {}
    cost = tok_in = tok_out = wall = 0
    models = set()
    for p in pairs.values():
        counts[p["match_status"]] = counts.get(p["match_status"], 0) + 1
        cost += p["cost_usd"]
        tok_in += p["in_tok"]
        tok_out += p["out_tok"]
        wall += p["wall_ms"]
        if p["model"]:
            models.add(p["model"])
    # Pairs with a usable ground-truth row (the denominator for accuracy).
    gt_n = n - counts.get("no_ground_truth", 0)
    match = counts.get("match", 0)
    near = counts.get("near_match", 0)
    abstained = counts.get("abstained", 0)
    print(f"\n[{name}] model(s)={sorted(models) or ['?']}  pairs={n}  with_gt={gt_n}")
    if gt_n:
        print(f"    exact match      {match}/{gt_n} = {match / gt_n:.0%}")
        print(f"    match+near_match {(match + near)}/{gt_n} = {(match + near) / gt_n:.0%}")
        print(f"    abstained        {abstained}/{gt_n} = {abstained / gt_n:.0%}")
        print(f"    differ           {counts.get('differ', 0)}/{gt_n}")
    print(f"    modelled cost    ${cost:.4f}  (£{cost * _USD_TO_GBP:.4f})  "
          f"= ${cost / n:.5f}/pair")
    print(f"    tokens in/out    {tok_in}/{tok_out}")
    print(f"    mean latency     {wall / n / 1000:.1f}s/pair")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mistral-experiment", required=True,
                        help="experiment_id tag of the Mistral arm")
    parser.add_argument("--baseline-experiment", default=None,
                        help="experiment_id of the Claude arm; omit for main runs")
    args = parser.parse_args()

    with sqlite3.connect(_DB_PATH) as conn:
        baseline = _load_arm(conn, args.baseline_experiment)
        mistral = _load_arm(conn, args.mistral_experiment)

    base_name = f"CLAUDE ({args.baseline_experiment or 'main runs'})"
    mist_name = f"MISTRAL ({args.mistral_experiment})"
    _summarise(base_name, baseline)
    _summarise(mist_name, mistral)

    # Paired view: only pairs present in both arms.
    shared = sorted(set(baseline) & set(mistral))
    print(f"\n[PAIRED] {len(shared)} pairs run by both arms")
    if not shared:
        print("    No overlap yet. Dispatch the Mistral arm on the baseline's "
              "(question, country) set to enable the paired comparison.")
        return 0

    same_answer = 0
    base_correct = mist_correct = both_correct = 0
    disagreements = []
    for key in shared:
        b, m = baseline[key], mistral[key]
        b_ans = (b["final_answer"] or "").strip().lower()
        m_ans = (m["final_answer"] or "").strip().lower()
        if b_ans == m_ans:
            same_answer += 1
        b_ok = b["match_status"] in ("match", "near_match")
        m_ok = m["match_status"] in ("match", "near_match")
        base_correct += b_ok
        mist_correct += m_ok
        both_correct += (b_ok and m_ok)
        if b_ans != m_ans:
            disagreements.append((key, b, m))

    print(f"    same final answer        {same_answer}/{len(shared)} = "
          f"{same_answer / len(shared):.0%}")
    print(f"    Claude correct           {base_correct}/{len(shared)}")
    print(f"    Mistral correct          {mist_correct}/{len(shared)}")
    print(f"    both correct             {both_correct}/{len(shared)}")
    print(f"    accuracy delta (Mistral - Claude) = "
          f"{(mist_correct - base_correct) / len(shared):+.0%}")

    if disagreements:
        print(f"\n    Disagreements ({len(disagreements)}) "
              f"[question country | ODMI | Claude | Mistral]:")
        for (q, c), b, m in disagreements:
            print(f"      {q:>5} {c}  | gt={b['odmi']!r:>12} "
                  f"| C={b['final_answer']!r:>12}({b['match_status']}) "
                  f"| M={m['final_answer']!r:>12}({m['match_status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
