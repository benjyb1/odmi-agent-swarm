# Held-out false-positive audit

Model: `claude-opus-4-6`  Countries: ['BA', 'MK', 'ME', 'BG', 'FI', 'HR', 'SE', 'BE']  DB snapshot per-country max phase2_final.id: {'FI': 4209, 'HR': 3832, 'SE': 4206, 'BA': 3843, 'MK': 4054, 'ME': 4166, 'BG': 4207, 'BE': 3831}

```
Held-out FP audit: 119/119 adjudicated (0 errored).

Pass 1 (charitable) verdicts:
  genuine_error               25  (21%)
  definitional_gap            86  (72%)
  defensible_or_stale_gold     8  (7%)
  -> genuine swarm error: 25/119 = 21%
  -> defensible/stale gold (swarm not clearly wrong): 8/119 = 7%

Pass 2 (adversarial advocate) verdicts:
  swarm_over_read   90  (76%)
  ambiguous         29  (24%)
  gold_wrong         0  (0%)
  -> swarm vindicated (gold_wrong, swarm right / ODMI wrong): 0/119 = 0%

By country:
  BA             n=13  genuine_error=3  stale_gold=1  gold_wrong=0
  BE             n=7  genuine_error=1  stale_gold=2  gold_wrong=0
  BG             n=12  genuine_error=0  stale_gold=1  gold_wrong=0
  FI             n=17  genuine_error=3  stale_gold=0  gold_wrong=0
  HR             n=8  genuine_error=3  stale_gold=0  gold_wrong=0
  ME             n=23  genuine_error=5  stale_gold=2  gold_wrong=0
  MK             n=26  genuine_error=7  stale_gold=1  gold_wrong=0
  SE             n=13  genuine_error=3  stale_gold=1  gold_wrong=0

By ODMI dimension:
  Impact         n=54  genuine_error=14  stale_gold=3  gold_wrong=0
  Policy         n=37  genuine_error=4  stale_gold=1  gold_wrong=0
  Portal         n=18  genuine_error=6  stale_gold=4  gold_wrong=0
  Quality        n=10  genuine_error=1  stale_gold=0  gold_wrong=0

By ODMI decision:
  change       n=54  genuine_error=13  gold_wrong=0
  complement   n=4  genuine_error=2  gold_wrong=0
  confirm      n=61  genuine_error=10  gold_wrong=0

HEADLINE: 0/119 held-out false positives had the swarm right and ODMI wrong (adversarial gold_wrong).
```
