#!/usr/bin/env python3
"""Phase 0, candidate-recall audit (LLM-free).

For each finalised production pair (experiment_id IS NULL) on a binary question
with a yes/no gold, ask: did ANY Researcher attempt produce the gold-correct
answer, even if the pair finalised wrong or abstained? The gap between
candidate recall (gold in hand somewhere) and observed accuracy (committed
correct) is the selection headroom: answers found but not committed.

This re-derives the Malta-only 74/44 oracle figure on real data, per country.
"""
import sqlite3
from collections import defaultdict

ABSTAIN = {"inconclusive", "other", "not_applicable", "not applicable",
           "i don't know", "idk", ""}

def norm(s):
    return (s or "").strip().lower()

c = sqlite3.connect("data/odmi.db").cursor()
rows = c.execute("""
  SELECT f.question_id, f.country_code, f.pair_run_id, f.final_answer,
         g.response AS gold
  FROM phase2_final f
  JOIN questions q ON q.question_id = f.question_id
  JOIN ground_truth g ON g.question_id = f.question_id
       AND g.country_code = f.country_code
  WHERE f.experiment_id IS NULL
    AND q.answer_shape = 'binary'
    AND lower(trim(g.response)) IN ('yes','no')
""").fetchall()

stat = defaultdict(lambda: {"n":0,"obs":0,"recall":0,"abstain_on_correct":0,"commit_wrong":0})
for qid, cc, prid, final, gold in rows:
    g = norm(gold); fin = norm(final)
    attempts = [norm(a[0]) for a in c.execute(
        "SELECT answer FROM phase2_researcher_runs WHERE pair_run_id=?", (prid,))]
    any_correct = any(a == g for a in attempts)
    final_correct = (fin == g)
    final_abstain = fin in ABSTAIN
    s = stat[cc]
    s["n"] += 1
    s["obs"] += int(final_correct)
    s["recall"] += int(any_correct)
    if any_correct and not final_correct:
        if final_abstain: s["abstain_on_correct"] += 1
    if (not final_abstain) and (not final_correct):
        s["commit_wrong"] += 1

print(f"{'CC':<4}{'n':>4}{'obs%':>7}{'recall%':>9}{'headroom':>10}{'abst_on_correct':>17}{'commit_wrong':>14}")
tot = defaultdict(int)
for cc in sorted(stat, key=lambda k:-stat[k]["n"]):
    s = stat[cc]; n=s["n"]
    obs=100*s["obs"]/n; rec=100*s["recall"]/n
    print(f"{cc:<4}{n:>4}{obs:>6.0f}%{rec:>8.0f}%{rec-obs:>9.0f}{s['abstain_on_correct']:>17}{s['commit_wrong']:>14}")
    for k,v in s.items(): tot[k]+=v
N=tot["n"] or 1
print(f"{'ALL':<4}{tot['n']:>4}{100*tot['obs']/N:>6.0f}%{100*tot['recall']/N:>8.0f}%{100*(tot['recall']-tot['obs'])/N:>9.0f}{tot['abstain_on_correct']:>17}{tot['commit_wrong']:>14}")
