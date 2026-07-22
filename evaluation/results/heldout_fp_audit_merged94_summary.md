# Held-out false-positive audit — merged over the canonical 94

Model: `claude-opus-4-6`  Countries: ['BA', 'MK', 'ME', 'BG', 'FI', 'HR', 'SE', 'BE']

Canonical FP set: EXP-36 (`exp36_frozen_headline`), corrected per commit 0d06c09 (dedup `phase2_final` on (question_id, country_code), 1,144 pairs). FP filter: `is_negative_gold AND is_committed AND NOT is_match` = 94 pairs.

Coverage: 91 of 94 are `final='yes'` over-reads, all adjudicated in the two prior audits and reused here (no re-audit): 91 from the 20260721 rerun, 0 from the original. The 3 uncovered pairs are `final='not_applicable'` against a `no` gold (MK I4/Q5/Q6); the yes-defending rubric does not apply, so they are flagged for manual review, not adjudicated. Zero model calls were added this run.

Provenance caveat: the two prior audits ran against a different DB copy, not the exp36-run DB. Their recorded `final_id`s are from a foreign id space (91/91 do not map to the same pair in the exp36-run DB), so an id-level match is not expected and is not a staleness signal. Reuse is therefore by (question_id, country_code) identity, per the instruction not to re-audit covered pairs. The verdicts pertain to the same swarm-vs-ODMI disagreement; byte-identity of the frozen evidence text between the prior DB and the exp36-run canonical row was not re-verified (doing so would mean re-auditing).

```
Merged over the canonical 94 EXP-36 negative-gold false positives:
  adjudicated (yes-FPs, reused prior verdicts): 91/94
  flagged for manual review (not_applicable vs no): 3/94  ['MK:I4', 'MK:Q5', 'MK:Q6']

Held-out FP audit: 91/91 adjudicated (0 errored).

Pass 1 (charitable) verdicts:
  genuine_error               16  (18%)
  definitional_gap            69  (76%)
  defensible_or_stale_gold     6  (7%)
  -> genuine swarm error: 16/91 = 18%
  -> defensible/stale gold (swarm not clearly wrong): 6/91 = 7%

Pass 2 (adversarial advocate) verdicts:
  swarm_over_read   68  (75%)
  ambiguous         23  (25%)
  gold_wrong         0  (0%)
  -> swarm vindicated (gold_wrong, swarm right / ODMI wrong): 0/91 = 0%

By country:
  BA             n=10  genuine_error=2  stale_gold=1  gold_wrong=0
  BE             n=6  genuine_error=0  stale_gold=2  gold_wrong=0
  BG             n=10  genuine_error=0  stale_gold=1  gold_wrong=0
  FI             n=14  genuine_error=2  stale_gold=0  gold_wrong=0
  HR             n=6  genuine_error=3  stale_gold=0  gold_wrong=0
  ME             n=13  genuine_error=3  stale_gold=0  gold_wrong=0
  MK             n=22  genuine_error=4  stale_gold=1  gold_wrong=0
  SE             n=10  genuine_error=2  stale_gold=1  gold_wrong=0

By ODMI dimension:
  Impact         n=36  genuine_error=8  stale_gold=2  gold_wrong=0
  Policy         n=33  genuine_error=2  stale_gold=1  gold_wrong=0
  Portal         n=15  genuine_error=5  stale_gold=3  gold_wrong=0
  Quality        n=7  genuine_error=1  stale_gold=0  gold_wrong=0

By ODMI decision:
  change       n=41  genuine_error=8  gold_wrong=0
  complement   n=3  genuine_error=2  gold_wrong=0
  confirm      n=47  genuine_error=6  gold_wrong=0

HEADLINE: 0/91 held-out false positives had the swarm right and ODMI wrong (adversarial gold_wrong).

HEADLINE over all 94: gold_wrong = 0/94 (swarm right / ODMI wrong, adversarial). 3/94 flagged not_applicable are not adjudicated.
```

## Flagged for manual review (not overturned here)

- gold_wrong (adversarial says swarm right / ODMI wrong): 0 — none
- defensible_or_stale_gold (charitable): 6 — ['BA:P27', 'BE:I12', 'BE:PT9', 'BG:PT35', 'MK:PT35', 'SE:I27']
- not_applicable vs no (uncovered, un-auditable by yes-rubric): 3 — ['MK:I4', 'MK:Q5', 'MK:Q6']
