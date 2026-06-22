#!/usr/bin/env python3
"""Phase 0, Researcher confidence calibration (LLM-free).

Tests whether the Researcher's stated answer_confidence is a reliable correctness
signal -- the basis for the "gate on confidence, not the verdict" recommendation.
Per Researcher attempt on a production binary pair with a yes/no gold, bucket
answer_confidence and report the fraction whose answer matches gold.
"""
import sqlite3
from collections import defaultdict
def norm(s): return (s or "").strip().lower()
ABST={"inconclusive","other","not_applicable","not applicable","i don't know","idk",""}
c=sqlite3.connect("data/odmi.db").cursor()
rows=c.execute("""
  SELECT r.answer, r.answer_confidence, g.response
  FROM phase2_researcher_runs r
  JOIN questions q ON q.question_id=r.question_id
  JOIN ground_truth g ON g.question_id=r.question_id AND g.country_code=r.country_code
  WHERE r.experiment_id IS NULL AND q.answer_shape='binary'
    AND lower(trim(g.response)) IN ('yes','no')
    AND r.answer_confidence IS NOT NULL AND r.answer IS NOT NULL
""").fetchall()
def bucket(c):
    if c<0.65: return "0.00-0.64"
    if c<0.80: return "0.65-0.79"
    if c<0.90: return "0.80-0.89"
    return "0.90-1.00"
B=defaultdict(lambda:{"n":0,"correct":0,"abst":0})
for ans,conf,gold in rows:
    a,g=norm(ans),norm(gold)
    if a in ABST: continue  # only committed answers
    b=B[bucket(conf)]; b["n"]+=1; b["correct"]+= int(a==g)
print(f"{'conf bucket':<12}{'n':>5}{'accuracy':>10}")
for k in ["0.00-0.64","0.65-0.79","0.80-0.89","0.90-1.00"]:
    b=B[k]
    if b["n"]: print(f"{k:<12}{b['n']:>5}{b['correct']/b['n']:>9.0%}")
hi=sum(B[k]['correct'] for k in ["0.80-0.89","0.90-1.00"]); hin=sum(B[k]['n'] for k in ["0.80-0.89","0.90-1.00"])
print(f"\n>= 0.80: {hi}/{hin} = {hi/hin:.0%} correct" if hin else "no >=0.80")
