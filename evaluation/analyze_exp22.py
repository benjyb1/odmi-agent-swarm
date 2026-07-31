"""EXP-22 analysis: foreign-language ablation on AL (bilingual vs English-only).

Reads the finalised exp22 rows from the canonical DB and reports the
pre-registered endpoints per arm:
  - candidate recall: a pair is recalled if ANY Researcher attempt committed an
    answer that matches the ODMI gold (the arm could reach the right answer).
  - abstention rate: final_answer = 'inconclusive'.
  - commit accuracy: of committed finals, the share matching gold.
  - mean retries; native-source hit rate (share of fetched/cited evidence in
    Albanian), which tests whether the bilingual arm actually surfaces more
    native pages.

Adoption rule (pre-registered): keep bilingual as production only if it lifts AL
candidate recall by >= 0.05 over English-only with no abstention rise. Otherwise
the native query is a no-op on AL and the deficit is thin-web / structural.

Read-only. Usage: python evaluation/analyze_exp22.py
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path("/Users/benjyb/Desktop/MscProject/data/odmi.db")
EXP = "exp22_foreign_lang_al"

# Heuristic Albanian detector (same signature as the language pass).
_SQ_STOP = set("të dhe për është nuk janë me një që nga ose hapja dhënave ripërdorim sipas kombëtar qeveria publike portali shqipëri".split())
_WORD = re.compile(r"[a-zà-ÿçë]+", re.I)


def is_albanian(text: str) -> bool:
    if not text or len(text.strip()) < 12:
        return False
    toks = _WORD.findall(text.lower())
    if len(toks) < 4:
        return False
    stop = sum(1 for w in toks if w in _SQ_STOP) / len(toks)
    dia = sum(text.lower().count(c) for c in "ëç") / max(len(toks), 1)
    return stop >= 0.04 or dia >= 0.05


def norm(s):
    return (s or "").strip().lower()


def matches_gold(ans, gold):
    a, g = norm(ans), norm(gold)
    if not a or not g or a in ("inconclusive", "other", "none"):
        return False
    if a == g:
        return True
    if a == "yes" and g.startswith("yes"):
        return True
    if a == "no" and g == "no":
        return True
    return False


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    finals = con.execute(
        "SELECT pair_run_id, question_id, country_code, final_answer, terminal_status, retry_count "
        "FROM phase2_final WHERE experiment_id=?", (EXP,)).fetchall()
    # arm label lives on the researcher/verifier rows (condition_label)
    arm_of = {}
    for r in con.execute(
        "SELECT DISTINCT pair_run_id, condition_label FROM phase2_researcher_runs WHERE experiment_id=?", (EXP,)):
        arm_of[r["pair_run_id"]] = r["condition_label"]

    gt = {}
    for r in con.execute("SELECT question_id, country_code, response FROM ground_truth WHERE country_code='AL'"):
        gt[r["question_id"]] = r["response"]

    # researcher attempts per pair (for candidate recall + native-source rate)
    attempts = defaultdict(list)
    for r in con.execute(
        "SELECT pair_run_id, answer, evidence_quote FROM phase2_researcher_runs WHERE experiment_id=?", (EXP,)):
        attempts[r["pair_run_id"]].append(r)

    arms = defaultdict(lambda: {"n": 0, "recalled": 0, "abstain": 0, "committed": 0,
                                "commit_correct": 0, "retry_sum": 0, "native_ev": 0, "ev_total": 0})
    for f in finals:
        arm = arm_of.get(f["pair_run_id"])
        if arm is None:
            continue
        a = arms[arm]
        a["n"] += 1
        a["retry_sum"] += f["retry_count"]
        gold = gt.get(f["question_id"])
        # candidate recall: any attempt's answer matches gold
        if any(matches_gold(at["answer"], gold) for at in attempts[f["pair_run_id"]]):
            a["recalled"] += 1
        # abstention / commit accuracy
        if norm(f["final_answer"]) == "inconclusive" or f["terminal_status"] == "agent_failure":
            a["abstain"] += 1
        else:
            a["committed"] += 1
            if matches_gold(f["final_answer"], gold):
                a["commit_correct"] += 1
        # native-source rate over attempts
        for at in attempts[f["pair_run_id"]]:
            if at["evidence_quote"]:
                a["ev_total"] += 1
                if is_albanian(at["evidence_quote"]):
                    a["native_ev"] += 1

    print(f"=== EXP-22 foreign-language ablation (AL): {len(finals)} finalised pairs ===\n")
    print(f"{'arm':<12}{'n':>5}{'recall':>9}{'abstain':>9}{'commit':>8}{'commit_acc':>12}{'retries':>9}{'native_ev':>11}")
    res = {}
    for arm in ("bilingual", "en"):
        a = arms.get(arm)
        if not a or a["n"] == 0:
            print(f"{arm:<12}{'(no data yet)':>30}")
            continue
        rec = a["recalled"] / a["n"]
        abst = a["abstain"] / a["n"]
        cacc = a["commit_correct"] / a["committed"] if a["committed"] else 0
        nat = a["native_ev"] / a["ev_total"] if a["ev_total"] else 0
        res[arm] = {"recall": rec, "abstain": abst}
        print(f"{arm:<12}{a['n']:>5}{rec*100:>8.0f}%{abst*100:>8.0f}%{a['committed']:>8}"
              f"{cacc*100:>11.0f}%{a['retry_sum']/a['n']:>9.2f}{nat*100:>10.0f}%")

    if "bilingual" in res and "en" in res:
        d_rec = res["bilingual"]["recall"] - res["en"]["recall"]
        d_abst = res["bilingual"]["abstain"] - res["en"]["abstain"]
        print(f"\nbilingual - english recall delta: {d_rec*100:+.1f} pts")
        print(f"bilingual - english abstain delta: {d_abst*100:+.1f} pts")
        print("\nADOPTION RULE: keep bilingual only if recall delta >= +5 pts with no abstain rise.")
        verdict = ("KEEP bilingual" if d_rec >= 0.05 and d_abst <= 0
                   else "NATIVE QUERY IS A NO-OP on AL -> deficit is thin-web / structural")
        print("VERDICT:", verdict)
        print("(pre-registered prediction: English-only within noise of bilingual)")


if __name__ == "__main__":
    main()
