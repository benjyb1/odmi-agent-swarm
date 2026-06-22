#!/usr/bin/env python3
"""Phase 0, Adjudicator standalone ablation (LLM-free).

Verifier open question 1, the cleanest unanswered one. EXP-13a measured removing
the whole verify+adjudicate layer; this isolates JUST the Adjudicator. For every
production pair that reached adjudication (adjudicator_involved=1), the
counterfactual "abstain at retry exhaustion" would turn its commit into an
abstention. So:

  gain  = adjudicated pairs the Adjudicator committed CORRECT (lost if we abstain)
  cost  = adjudicated pairs the Adjudicator committed WRONG  (avoided if we abstain)
  net   = gain - cost

A net well above zero means the Adjudicator earns its keep on its own. Binary
questions with a yes/no gold only; production rows (experiment_id IS NULL).
"""
import sqlite3
from collections import defaultdict

ABSTAIN = {"inconclusive","other","not_applicable","not applicable","i don't know","idk",""}
def norm(s): return (s or "").strip().lower()

c = sqlite3.connect("data/odmi.db").cursor()
rows = c.execute("""
  SELECT f.country_code, f.final_answer, g.response
  FROM phase2_final f
  JOIN questions q ON q.question_id=f.question_id
  JOIN ground_truth g ON g.question_id=f.question_id AND g.country_code=f.country_code
  WHERE f.experiment_id IS NULL AND f.adjudicator_involved=1
    AND q.answer_shape='binary' AND lower(trim(g.response)) IN ('yes','no')
""").fetchall()

st = defaultdict(lambda: {"adj":0,"gain":0,"cost":0,"abstain":0})
for cc, final, gold in rows:
    fin, g = norm(final), norm(gold)
    s = st[cc]; s["adj"] += 1
    if fin in ABSTAIN: s["abstain"] += 1
    elif fin == g:     s["gain"] += 1
    else:              s["cost"] += 1

print(f"{'CC':<5}{'adjud':>7}{'gain':>6}{'cost':>6}{'abstain':>9}{'net':>6}  (net = correct commits - wrong commits)")
tot = defaultdict(int)
for cc in sorted(st, key=lambda k:-st[k]['adj']):
    s=st[cc]; net=s['gain']-s['cost']
    print(f"{cc:<5}{s['adj']:>7}{s['gain']:>6}{s['cost']:>6}{s['abstain']:>9}{net:>6}")
    for k,v in s.items(): tot[k]+=v
net=tot['gain']-tot['cost']
print(f"{'ALL':<5}{tot['adj']:>7}{tot['gain']:>6}{tot['cost']:>6}{tot['abstain']:>9}{net:>6}")
if tot['gain']+tot['cost']:
    prec = tot['gain']/(tot['gain']+tot['cost'])
    print(f"\nAdjudicator commit precision: {prec:.2f} ({tot['gain']}/{tot['gain']+tot['cost']}); "
          f"it rescues {tot['gain']} correct for {tot['cost']} wrong vs abstaining all {tot['adj']}.")
