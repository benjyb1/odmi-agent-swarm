# Held-out false-positive audit

Model: `claude-opus-4-6`  Countries: ['BA', 'MK', 'ME', 'BG', 'FI', 'HR', 'SE', 'BE']  DB snapshot per-country max phase2_final.id: {'FI': 4209, 'HR': 3832, 'SE': 4206, 'BA': 3843, 'MK': 4054, 'ME': 4166, 'BG': 4207, 'BE': 3831}

```
Held-out FP audit: 6/6 adjudicated (0 errored).

Pass 1 (charitable) verdicts:
  genuine_error                1  (17%)
  definitional_gap             4  (67%)
  defensible_or_stale_gold     1  (17%)
  -> genuine swarm error: 1/6 = 17%
  -> defensible/stale gold (swarm not clearly wrong): 1/6 = 17%

Pass 2 (adversarial advocate) verdicts:
  swarm_over_read    3  (50%)
  ambiguous          3  (50%)
  gold_wrong         0  (0%)
  -> swarm vindicated (gold_wrong, swarm right / ODMI wrong): 0/6 = 0%

By country:
  BA             n=6  genuine_error=1  stale_gold=1  gold_wrong=0

By ODMI dimension:
  Impact         n=2  genuine_error=0  stale_gold=0  gold_wrong=0
  Policy         n=4  genuine_error=1  stale_gold=1  gold_wrong=0

By ODMI decision:
  confirm      n=6  genuine_error=1  gold_wrong=0

HEADLINE: 0/6 held-out false positives had the swarm right and ODMI wrong (adversarial gold_wrong).
```
