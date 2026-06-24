#!/usr/bin/env python3
"""Self-report stratification: swarm accuracy by ODMI's `decision` field.

ODMI is a country self-report questionnaire validated by Capgemini; the
`ground_truth.decision` field records the validation per (question, country):
confirm (country's answer accepted), complement (kept + assessor added evidence),
change (assessor overrode). This stratifies the swarm's binary accuracy /
abstention / false-positive rate by that field, the operational self-report vs
independently-evidenced split. Read-only; pairs deduped to the latest row per
(question, country) to avoid the across-arms pooling inflation.

  uv run python evaluation/selfreport_decision_split.py --db /abs/path/odmi.db
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "odmi.db"
ABST = {"inconclusive", "not_applicable", "not applicable", "other",
        "i don't know", "idk", "", None}
DECS = ["confirm", "complement", "change"]
DIMS = ["policy_dimension", "portal_dimension", "quality_dimension", "impact_dimension"]


def norm(s):
    return (s or "").strip().lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    shape = {r["question_id"]: (r["answer_shape"] or "binary")
             for r in con.execute("SELECT question_id, answer_shape FROM questions")}
    gt, dec, dim = {}, {}, {}
    for r in con.execute("SELECT question_id, country_code, response, decision, dimension FROM ground_truth"):
        k = (r["question_id"], r["country_code"])
        gt[k], dec[k], dim[k] = r["response"], r["decision"], r["dimension"]

    def correct(q, a, g):
        a, g = norm(a), norm(g)
        if a in ABST or not g:
            return False
        if a == g:
            return True
        return shape.get(q) == "binary" and ((a == "yes" and g.startswith("yes")) or (a == "no" and g == "no"))

    # dedup latest per (q,c), binary yes/no gold
    best = {}
    for f in con.execute("SELECT * FROM phase2_final"):
        if shape.get(f["question_id"]) != "binary":
            continue
        k = (f["question_id"], f["country_code"])
        if norm(gt.get(k)) not in ("yes", "no"):
            continue
        if k not in best or f["id"] > best[k]["id"]:
            best[k] = f

    agg = defaultdict(lambda: [0, 0, 0, 0])  # total, committed, correct, fp
    md = defaultdict(lambda: [0, 0])  # (dim,dec) -> committed, correct
    for k, f in best.items():
        d = dec.get(k) or "(null)"
        agg[d][0] += 1
        if norm(f["final_answer"]) in ABST:
            continue
        agg[d][1] += 1
        c = correct(f["question_id"], f["final_answer"], gt[k])
        agg[d][2] += c
        if norm(f["final_answer"]) == "yes" and norm(gt[k]) == "no":
            agg[d][3] += 1
        md[(dim.get(k), d)][0] += 1
        md[(dim.get(k), d)][1] += c

    print("Swarm binary accuracy by ODMI decision (deduped per question x country):")
    print(f"  {'decision':11s} {'total':>5s} {'cmt':>5s} {'abst%':>6s} {'acc':>6s} {'FP':>4s}")
    for d, (t, cm, cor, fp) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        print(f"  {d:11s} {t:5d} {cm:5d} {(t-cm)/t:6.0%} {(cor/cm if cm else 0):6.0%} {fp:4d}")

    print("\nAccuracy on committed, dimension x decision:")
    print("  " + "dimension".ljust(10) + " ".join(d[:9].rjust(12) for d in DECS))
    for dm in DIMS:
        cells = []
        for dc in DECS:
            n, c = md.get((dm, dc), [0, 0])
            cells.append((f"{c/n*100:.0f}% (n={n})" if n else "-").rjust(12))
        print("  " + dm.replace("_dimension", "").ljust(10) + " ".join(cells))
    con.close()


if __name__ == "__main__":
    main()
