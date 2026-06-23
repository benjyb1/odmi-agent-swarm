#!/usr/bin/env python3
"""EXP-10 Phase B, generalised: confidence-floor sweep across every country we
have data for, not Malta alone.

The Malta-only sweep (n=60) is too thin to settle a floor that gates every
commit. This pools the finalised pairs from all countries with stored data and
re-runs the identical replay logic (`malta_failure_audit.floor_sweep` /
`decide_floor`), reporting each country on its own and the pooled set, then
applying the pre-registered decision rule to the pool.

Sources are production rows (`experiment_id IS NULL`) for every country, plus
NL's production-config experiment baseline (EXP-16 `standard` = full production
config: standard adjudicator, always-search verifier, picker on, DIY 5x3), since
NL has almost no `experiment_id IS NULL` rows yet its 26 negative golds are the
main non-Malta balanced-negative evidence. Free replay, no API calls.

  uv run python evaluation/floor_sweep_all.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from evaluation.malta_failure_audit import (  # noqa: E402
    DEFAULT_FLOORS, decide_floor, floor_sweep, load_pairs,
)

# (display label, country, experiment_id, condition_label)
SOURCES = [
    ("MT", "MT", None, None),
    ("NO", "NO", None, None),
    ("FR", "FR", None, None),
    ("EE", "EE", None, None),
    ("DE", "DE", None, None),
    ("RO", "RO", None, None),
    # NL production-config baseline (EXP-16 standard arm), for its 26 negative golds
    ("NL*", "NL", "exp16_adjudicator_selection_nl", "standard"),
]
RESULTS = REPO / "evaluation" / "results" / "floor_sweep_all.jsonl"


def _binary_yesno(p: dict) -> bool:
    return p["answer_shape"] == "binary" and (p["gold"] or "").strip().lower() in ("yes", "no")


def _row(label, n, neg, sweep, decision):
    s065, s050 = sweep[0.65], sweep[0.50]
    return (f"  {label:5s} {n:4d} {neg:4d}  "
            f"{s065['committed']:4d}/{s065['correct']:<4d} "
            f"{(s065['fpr_neg'] if s065['fpr_neg'] is not None else float('nan')):.2f}   "
            f"{s050['recovered']:3d} ({s050['recovered_correct']}/{s050['recovered_fp']})  "
            f"{(s050['recovery_precision'] if s050['recovery_precision'] is not None else float('nan')):.2f}    "
            f"{decision['recommended_floor']}")


def main() -> int:
    conn = sqlite3.connect(str(REPO / "data" / "odmi.db"))
    conn.row_factory = sqlite3.Row

    pooled: list = []
    per_country = []
    for label, cc, eid, cond in SOURCES:
        pairs = [p for p in load_pairs(conn, country=cc, experiment_id=eid,
                                       condition_label=cond) if _binary_yesno(p)]
        if not pairs:
            continue
        for p in pairs:
            p["_src"] = label
        neg = sum(1 for p in pairs if p["is_negative_gold"])
        sweep = floor_sweep(pairs, DEFAULT_FLOORS)
        decision = decide_floor(sweep, baseline=max(DEFAULT_FLOORS))
        per_country.append((label, len(pairs), neg, sweep, decision))
        pooled.extend(pairs)
    conn.close()

    pooled_sweep = floor_sweep(pooled, DEFAULT_FLOORS)
    pooled_decision = decide_floor(pooled_sweep, baseline=max(DEFAULT_FLOORS))
    pooled_neg = sum(1 for p in pooled if p["is_negative_gold"])

    print("\n" + "=" * 78)
    print("EXP-10 Phase B, all countries  —  confidence-floor sweep (free replay)")
    print("=" * 78)
    print("  NL* = EXP-16 standard arm (production-config baseline).\n")
    print(f"  {'cc':5s} {'n':>4s} {'neg':>4s}  {'@0.65 cmt/cor':13s} {'fpr':5s}  "
          f"{'@0.50 recov(ok/fp)':18s} {'prec':5s} {'rec_floor'}")
    for label, n, neg, sweep, decision in per_country:
        print(_row(label, n, neg, sweep, decision))
    print("  " + "-" * 74)
    print(_row("POOL", len(pooled), pooled_neg, pooled_sweep, pooled_decision))

    print("\n--- Pooled floor sweep (the bigger-sample decision) ---")
    print(f"  {'floor':>6s} {'committed':>10s} {'correct':>8s} {'recovered':>10s} "
          f"{'rec_correct':>11s} {'rec_fp':>7s} {'rec_prec':>9s} {'fpr_neg':>8s}")
    for f in sorted(pooled_sweep, reverse=True):
        r = pooled_sweep[f]
        rp = "  n/a" if r["recovery_precision"] is None else f"{r['recovery_precision']:.2f}"
        fn = "  n/a" if r["fpr_neg"] is None else f"{r['fpr_neg']:.2f}"
        print(f"  {f:6.2f} {r['committed']:>10d} {r['correct']:>8d} {r['recovered']:>10d} "
              f"{r['recovered_correct']:>11d} {r['recovered_fp']:>7d} {rp:>9s} {fn:>8s}")
    print(f"\n  Pooled n={len(pooled)} across {len(per_country)} countries, "
          f"{pooled_neg} negative golds.")
    print(f"  Decision rule (recovered precision>=0.80, neg-FPR rise<=0.05): "
          f"recommended floor = {pooled_decision['recommended_floor']}")
    for f, v in sorted(pooled_decision["verdicts"].items(), reverse=True):
        print(f"    floor {f}: {'ADOPT' if v['passes'] else 'reject'} "
              f"(recovered {v['recovered']}, precision_ok={v['precision_ok']}, fpr_ok={v['fpr_ok']})")
    print("=" * 78)

    RESULTS.parent.mkdir(exist_ok=True)
    with RESULTS.open("w") as fh:
        fh.write(json.dumps({"_record": "header", "sources": [s[0] for s in SOURCES],
                             "pooled_n": len(pooled), "pooled_neg": pooled_neg}) + "\n")
        for label, n, neg, sweep, decision in per_country:
            fh.write(json.dumps({"_record": "country", "cc": label, "n": n, "neg": neg,
                                 "sweep": {str(k): v for k, v in sweep.items()},
                                 "recommended_floor": decision["recommended_floor"]}) + "\n")
        fh.write(json.dumps({"_record": "pooled",
                             "sweep": {str(k): v for k, v in pooled_sweep.items()},
                             "decision": {**pooled_decision,
                                          "verdicts": {str(k): v for k, v in pooled_decision["verdicts"].items()}}}) + "\n")
    print(f"\nWrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
