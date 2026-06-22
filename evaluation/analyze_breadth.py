#!/usr/bin/env python3
"""EXP-17 breadth analysis: baseline_r5 vs breadth_r10 on NL.

Endpoint: candidate recall (gold answer in ANY Researcher attempt) -- the
retrieval signal, decoupled from selection -- plus balance-aware commit accuracy,
abstention, and cost/pair. Binary NL pairs with a yes/no gold.
"""
import sqlite3
from collections import defaultdict
ABST={"inconclusive","other","not_applicable","not applicable","i don't know","idk",""}
def norm(s): return (s or "").strip().lower()
c=sqlite3.connect("data/odmi.db").cursor()

# map each pair_run_id -> arm (condition_label) for this experiment
arm_of={}
for prid,lab in c.execute("""SELECT DISTINCT pair_run_id,condition_label FROM phase2_researcher_runs
    WHERE experiment_id='exp17_breadth_nl'"""): arm_of[prid]=lab

rows=c.execute("""
  SELECT f.pair_run_id,f.question_id,f.country_code,f.final_answer,g.response,f.cumulative_cost_usd
  FROM phase2_final f
  JOIN questions q ON q.question_id=f.question_id
  JOIN ground_truth g ON g.question_id=f.question_id AND g.country_code=f.country_code
  WHERE f.experiment_id='exp17_breadth_nl' AND q.answer_shape='binary'
    AND lower(trim(g.response)) IN ('yes','no')""").fetchall()

S=defaultdict(lambda:{"n":0,"recall":0,"commit_ok":0,"abst":0,"fp":0,"yes_n":0,"yes_ok":0,"no_n":0,"no_ok":0,"cost":0.0})
for prid,qid,cc,final,gold,cost in rows:
    arm=arm_of.get(prid,"?"); g=norm(gold); fin=norm(final)
    atts=[norm(a[0]) for a in c.execute("SELECT answer FROM phase2_researcher_runs WHERE pair_run_id=?", (prid,))]
    s=S[arm]; s["n"]+=1; s["cost"]+=cost or 0
    if any(a==g for a in atts): s["recall"]+=1
    if fin in ABST: s["abst"]+=1
    elif fin==g: s["commit_ok"]+=1
    else:
        if g=="no": s["fp"]+=1   # committed wrong on a no-gold (visible FP)
    if g=="yes": s["yes_n"]+=1; s["yes_ok"]+= int(fin==g)
    else:        s["no_n"]+=1;  s["no_ok"]+= int(fin==g)

print(f"{'arm':<14}{'n':>3}{'recall':>8}{'commit_acc':>11}{'yes_rec':>9}{'no_rec':>8}{'abstain':>9}{'FP':>4}{'£/pair':>8}")
for arm in sorted(S):
    s=S[arm]; n=s['n'] or 1
    print(f"{arm:<14}{s['n']:>3}{s['recall']/n:>8.2f}{s['commit_ok']/n:>11.2f}"
          f"{(s['yes_ok']/s['yes_n'] if s['yes_n'] else 0):>9.2f}{(s['no_ok']/s['no_n'] if s['no_n'] else 0):>8.2f}"
          f"{s['abst']/n:>9.2f}{s['fp']:>4}{0.79*s['cost']/n:>8.3f}")
print("\nrecall = gold in any Researcher attempt (retrieval signal); commit_acc = final==gold;")
print("yes_rec/no_rec = per-class commit recall; FP = committed wrong on a no-gold.")
