# Held-out false-positive audit

Model: `claude-opus-4-6`  Countries: ['BA', 'MK', 'ME', 'BG', 'FI', 'HR', 'SE', 'BE']  DB snapshot per-country max phase2_final.id: {'FI': 2569, 'HR': 2630, 'SE': 2689, 'BA': 2808, 'MK': 2870, 'ME': 2901, 'BG': 2510, 'BE': 2748}

```
Held-out FP audit: 83/83 adjudicated (0 errored).

Pass 1 (charitable) verdicts:
  genuine_error               17  (20%)
  definitional_gap            60  (72%)
  defensible_or_stale_gold     6  (7%)
  -> genuine swarm error: 17/83 = 20%
  -> defensible/stale gold (swarm not clearly wrong): 6/83 = 7%

Pass 2 (adversarial advocate) verdicts:
  swarm_over_read   60  (72%)
  ambiguous         22  (27%)
  gold_wrong         1  (1%)
  -> swarm vindicated (gold_wrong, swarm right / ODMI wrong): 1/83 = 1%

By country:
  BA             n=7  genuine_error=1  stale_gold=1  gold_wrong=0
  BE             n=4  genuine_error=1  stale_gold=0  gold_wrong=0
  BG             n=6  genuine_error=1  stale_gold=0  gold_wrong=0
  FI             n=17  genuine_error=4  stale_gold=0  gold_wrong=0
  HR             n=4  genuine_error=1  stale_gold=0  gold_wrong=0
  ME             n=19  genuine_error=3  stale_gold=3  gold_wrong=0
  MK             n=16  genuine_error=5  stale_gold=1  gold_wrong=0
  SE             n=10  genuine_error=1  stale_gold=1  gold_wrong=1

By ODMI dimension:
  Impact         n=41  genuine_error=11  stale_gold=2  gold_wrong=1
  Policy         n=27  genuine_error=2  stale_gold=3  gold_wrong=0
  Portal         n=6  genuine_error=3  stale_gold=1  gold_wrong=0
  Quality        n=9  genuine_error=1  stale_gold=0  gold_wrong=0

By ODMI decision:
  change       n=39  genuine_error=10  gold_wrong=0
  complement   n=1  genuine_error=0  gold_wrong=0
  confirm      n=43  genuine_error=7  gold_wrong=1

HEADLINE: 1/83 held-out false positives had the swarm right and ODMI wrong (adversarial gold_wrong).
```
