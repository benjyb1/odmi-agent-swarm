# Researcher / Verifier / Adjudicator: empirical attribution and recommended changes

2026-06-11. This is the deliverable of the stack-attribution pass: where each
element of the swarm helps, where it hurts, and what to change, each claim tied
to a number with a confidence interval. Method and per-analysis detail are in
`docs/EXPERIMENTS_STACK_ATTRIBUTION.md`; the chaining experiment is
pre-registered in `docs/EXPERIMENTS_CHAINING.md`. Evidence base: the 386
finalised production pairs plus the EXP-7 paired run (Malta, 40 pairs per arm).
All "correct" figures are against the ODMI published gold, which can be one
cycle stale (D22); MT is read as primary because its binary gold is base-rate
balanced (R4).

## The one-paragraph version

The Verifier's pass/fail verdict carries almost no information about whether an
answer is right (pooled Youden's J = -0.02), yet the retry loop it drives is
what makes hard countries answerable at all (Malta 44% vs a Researcher-solo
10%). The single largest lever is not any one agent but candidate selection: an
oracle that simply commits the gold-correct candidate the Researcher already
generated would score 74% on Malta against the observed 44%, so the right
answer is usually in hand and the pipeline abstains on it. The Researcher's own
stated confidence is the best correctness signal in the stack (98% correct at
confidence >= 0.80). Chaining evidence across retries (EXP-7) moves the numbers
the right way (balanced accuracy +5 points, false positives down, three more
recoveries) but the result is underpowered by Malta's retrieval ceiling and is
not statistically significant on its own. The recommendations below follow
from these four facts.

## Per-element findings (the receipts)

| Element | Finding | Number |
|---|---|---|
| Verifier verdict | No correctness discrimination | Youden's J = -0.02 pooled (488 judgements); J = 0.01 on Norway with a 0.71 false-accept rate |
| Retry loop | Net positive on hard countries, net negative on easy ones | MT observed 44% vs solo 10%; FR observed 63% vs solo 69% |
| Retry recoveries | Real but slow, and costly when the Verifier false-rejects | 61 recovered / 15 degraded of 212 retried; 36 of 61 needed all 3 retries; of 42 correct first answers the Verifier rejected, 14 ended in abstention |
| Adjudicator | Conservative: abstains far more correct candidates than it rescues wrong ones | When the last candidate was correct, abstained on 42 / committed wrong on 4; when not correct, rescued only 2 of 47 |
| Researcher grounding | Not the problem | cited URL in the snippet set 99%; quote verbatim-findable 89% |
| Researcher breadth | The real retrieval constraint | mean 5.1 snippets/run; 24% of citations at rank >= 5 |
| Researcher confidence | The best signal available | 98% correct at confidence >= 0.80 (114/116); 92% at 0.65-0.79 |
| Substring gate | Anti-fabrication control, miscalibrated only on the legacy path | live-fetch path fails 58%, snippet path fails 7%; no softer variant beats 0.19 fire-precision-for-wrongness |
| Counter-evidence | Half of it is not independent | 48% of Verifier counter-evidence cites the same URL the Researcher cited |
| Whole loop, headroom | Selection, not retrieval, is the ceiling | oracle-over-generated-candidates 74% vs observed 44% on MT |

## EXP-7 result (chaining evidence across the retry loop)

Paired, 40 Malta pairs per arm, only `--chained` varies, all other knobs
pinned. Full JSON: `evaluation/results/chaining_retry_chaining_mt_v1.json`.

| Endpoint | baseline | chained | read |
|---|---|---|---|
| Balanced accuracy | 0.167 | 0.217 | +5 points, directional |
| Recoveries (of 40) | 6 | 9 | +3 |
| False-positive rate | 0.25 (2/8) | 0.18 (2/11) | not raised (the co-primary) |
| Abstention rate | 0.80 | 0.725 | chaining commits 3 more |
| Calls per resolved pair | 9.1 | 11.5 | up; per-pair median delta 0 (Wilcoxon p=0.83) |
| Recovery McNemar | discordant 1 vs 4 | | p = 0.375, not significant |
| Joint confirmatory (bal-acc non-decrease at no higher FP) | | | passes |

Honest reading: the direction is consistent (more recoveries, lower false
positives, same per-pair call median) and the pre-registered joint
non-inferiority claim passes, but the recovery gain is not significant. The
cause is power: 72 to 80% of Malta pairs abstain because the evidence is not on
the open web (the self-report / deny-list ceiling), so recovery is measured on
a base of 8 to 11 committed pairs. Chaining is "promising, not proven", which
is consistent with the 2026-06-09 decision to treat it as an optimisation
target rather than a confirmatory test.

## Recommendations, in priority order

### 1. Stop treating the Verifier verdict as a correctness signal; gate on Researcher confidence instead (high value, low risk)

The verdict's J is zero, but Researcher confidence at >= 0.80 is 98% correct.
Add a high-confidence fast path: accept an attempt-0 answer when its confidence
is >= 0.80 **and** the substring gate passes, skipping the adversarial Verifier
round. On the production mix this commits the 114/116 band immediately and
spends the Verifier budget only where confidence is lower, which is where the
loop earns its cost. This dovetails with the Verifier-redesign work already in
flight rather than competing with it: that work fixes *how* the Verifier
judges; this fixes *when* it is invoked. Pre-register as an EXP-8-family arm
(MT primary so a false `yes` is visible) before adopting; the win is mostly
cost on easy countries (FR has 71/108 attempt-0 candidates above 0.80, MT only
1/14), so the accuracy must be shown not to move on the balanced set.

### 2. Adopt chaining as the default retry path (moderate value, low risk)

It does not raise false positives, it lowers abstention, it recovers more, and
the per-pair call-count median is unchanged (the total rises because a few
pairs re-read a larger corpus). The headline gain is not significant on 40
Malta pairs, but the downside is bounded and the upside is real, so the
expected value is positive. Two honest conditions: (a) carry it as the
optimisation baseline and tune the corpus (dedup is already in; the 48%
counter-evidence overlap means feeding back the Verifier's *URL* adds little,
so feed back the *interpretation/quote* and dedup by URL); (b) if a confirmatory
claim is wanted for the dissertation, the run needs a country with a lower
abstention ceiling or a larger n, because Malta's retrieval ceiling caps the
power.

### 3. Make the Adjudicator commit the best candidate it already holds (high value, needs care)

The Adjudicator abstains on 42 correct candidates for every 2 wrong ones it
rescues, and the oracle headroom (74% vs 44%) is almost entirely correct
candidates the pipeline declined to commit. Have it prefer the highest-confidence
definite candidate across attempts when that confidence clears the floor,
rather than defaulting to `inconclusive`. This is the single largest accuracy
lever, but it is also where a careless change buys recovery with false
positives, so it must be gated on the MT false-positive co-primary and the D37
floor, and pre-registered. Chaining is a partial version of this already
(it committed 3 more at lower FP); the fuller change is confidence-ranked
selection.

### 4. Guarantee the substring gate always runs on stored snippets (low value, trivial)

The gate's false fires are concentrated in the live-fetch fallback (58% vs 7%).
Persist Researcher snippets on every path that reaches the gate so it never
falls back to a live re-fetch. Removes a class of false rejects at no
anti-fabrication cost. Mechanical change.

### 5. Do not cut retrieval breadth; if anything widen it on hard countries (informs EXP-2a)

24% of citations sit at rank >= 5 and runs average only 5.1 snippets, so the
tail of the result list does real work. This pre-registers the prediction that
EXP-2a's lean arm (2 queries x 3 results) will lose accuracy. The lever for
hard countries is more breadth, not less.

### 6. Keep the 0.65 commit floor (settled)

EXP-10's floor sweep: dropping to 0.55 or 0.50 recovers 4 to 10 answers but
fails the pre-set recovered-precision bound (0.50 and 0.70 against the required
0.80). No change.

### Reliability fix already shipped

The DIY render timeout was per-phase, not total: browser launch and the
Cloudflare settle waits sat outside the goto timeout, so a WAF-challenged URL
could spend ~38s against a ~24s budget and trip the 30s stage ceiling, halting
batches. Now a single total budget across launch / goto / settle
(`agents/tools/fetch.py`, four tests). This was the cause of the recurring DIY
"timeouts" and the EXP-7 baseline stop.

## What is stubbed, partial, or owed

- EXP-7 is one country (Malta), 40 pairs, underpowered by the abstention
  ceiling. The Netherlands secondary arm is not run.
- Recommendations 1 and 3 are designs, not yet run. They are the next
  experiments, both MT-primary and pre-registered before any dispatch.
- The 8 pre-fix EXP-7 finals (retagged `_aborted`) and the ~170 duplicate
  baseline finals from the driver loop are kept as audit trail; the analysis
  dedups them by canonical row, so the numbers above are clean.
