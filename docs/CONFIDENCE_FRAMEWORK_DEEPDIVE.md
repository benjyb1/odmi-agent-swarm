# Confidence framework deep dive

A read-only investigation of the two self-reported confidences that gate every
commit in the swarm. Built on 2026-06-24 from `data/odmi.db` by
`evaluation/confidence_deepdive.py`; the reliability diagram is
`evaluation/results/reliability_diagram.svg` and the full numbers are dumped to
`evaluation/results/confidence_deepdive.json`. No swarm run, no LLM call, no DB
write. Every figure below was reproduced from the stored rows; where it differs
from the figures in the original brief I say so and give the verified value.

This is the confidence companion to `docs/DECISION_SURFACE.md` (REAS-9/REAS-10,
"the quiet giant") and `docs/ABSTENTION_TAXONOMY.md`. It answers the question the
decision surface flagged and EXP-10 left half-open: is the confidence the whole
commit policy rests on actually a correctness signal, and can any single
threshold on it work.

## Reproduce

```bash
uv run python evaluation/confidence_deepdive.py --json
# prints sections A/A'/A''/B/C; writes results/confidence_deepdive.json
#   and results/reliability_diagram.svg
```

The script reads only `phase2_final`, `phase2_researcher_runs`,
`phase2_verifier_runs`, `phase2_adjudications`, `questions` and `ground_truth`,
and opens the DB with `mode=ro`.

---

## 0. What the confidences are and where they gate

Two numbers come out of the Researcher LLM on every web answer
(`agents/models.py:199-200`):

- `retrieval_confidence` is, per the prompt (`agents/prompts/researcher.py:104-108`),
  "how confident you are that the cited source is real, current, and
  authoritative".
- `answer_confidence` is "how confident you are that the quoted evidence
  supports the specific label you picked". On paper this is a self-reported
  entailment score.

Both are uncalibrated. The catalogue route does not ask the model at all: it
hard-codes `retrieval_confidence=1.0`, `answer_confidence=0.95`
(`agents/researcher.py:274-275`, decision CAT-22). The Verifier and Adjudicator
carry their own confidences, but `verifier_confidence` is defined as "your
confidence in your own verdict, not in the answer"
(`agents/prompts/verifier.py:84`), so it is a meta-confidence, not an evidence
score.

`answer_confidence` is the number the whole commit policy is built on:

| Gate | Rule | Where |
|---|---|---|
| Researcher abstain | emit `inconclusive` if answer_confidence would be < 0.5 | `agents/prompts/researcher.py:66,70` (REAS-5) |
| Verifier blind pass floor | pass only if the evidence supports an answer with confidence >= 0.6 | `agents/prompts/verifier.py:471` (VER-9) |
| Accept a Verifier pass | pass AND not abstain AND answer_confidence >= 0.65 | `scripts/run_coordinator.py:947-958` (LOOP-4) |
| Commit floor | answer_confidence >= 0.65 | `scripts/run_coordinator.py:926` (LOOP-7, D37) |
| Adjudicator auto-escalate | verdict forced to escalate if confidence < 0.6 | `agents/adjudicator.py:29` (ADJ-3) |

Five gates, three different cutoffs (0.5, 0.6, 0.65), all on numbers that have
never been checked against outcomes. That check is this document.

### Populations and the one trap to avoid

The project's prior confidence numbers (and the brief) pool **every**
`phase2_final` row across all experiments with no de-duplication per (question,
country). That cut is reproduced here as `pooled` for continuity, and it does
reproduce the brief exactly (below), but it is not a set of independent units: a
single (question, country) pair recurs across experiment arms, and the arms mix
configurations (verifier-search policy, chaining, model, prompt variant). Half
of it is one country under degraded arms (see 1.1). So three cuts are reported
throughout:

- **pooled**: all `phase2_final` rows, all experiments. Maximum n, matches the
  prior numbers, but correlated and config-mixed.
- **production**: `experiment_id IS NULL`, de-duplicated to the latest row per
  pair. Clean configuration, independent units, but small and `yes`-skewed.
- **dev**: the five D47 development countries (NL, MT, NO, FR, AL). Anything
  that could inform a threshold is read here.

The eight held-out countries (BA, MK, ME, BG, FI, HR, SE, BE) appear only as a
labelled out-of-sample diagnostic row and are never used to choose a threshold.
All confidence intervals are Wilson 95% (`evaluation/stats.py`). Because the
pooled rows are not independent, treat pooled CIs as optimistic.

---

## 1. Headline reproduction and decomposition

Binary committed answers (the answer shape with enough web volume to measure),
joined to a `yes`/`no` gold:

| Population | n | accuracy | FP | FN | neg golds | FP on negatives |
|---|---:|---:|---:|---:|---:|---:|
| pooled (all rows) | 1065 | 69.9% | 268 | 53 | 379 | 71% |
| pooled, dev only | 858 | 67.1% | 242 | 40 | 339 | 71% |
| production (dedup) | 243 | 88.1% | 6 | 23 | 33 | 18% |
| production, dev | 234 | 87.6% | 6 | 23 | 32 | 19% |
| NL only (all arms) | 549 | 57.6% | 223 | 10 | 266 | 84% |
| MT only (all arms) | 110 | 74.5% | 16 | 12 | 63 | 25% |
| held-out (diagnostic) | 198 | 80.3% | 26 | 13 | 39 | 67% |

The pooled row reproduces the brief to the digit: n=1065, 744 correct (69.9%),
268 false positives, 53 false negatives.

### 1.1 The pooled picture is mostly NL under degraded arms

The grim headline (70%, false-positive-skewed, 71% wrong on negative golds) is
not the production policy. It is dominated by NL experiment arms:

- NL alone is 549 of the 1065 binary commits, at 57.6% accuracy, carrying 266 of
  the 379 negative golds and an 84% false-positive rate on them.
- Those NL rows are mostly degraded arms: `exp14_verifier_search_nl` (51%),
  `exp16_adjudicator_selection_nl` (57%), `exp17_breadth/picker_nl` (62%),
  `exp19_verifier_search_multicountry` (57%). Production (`experiment_id IS NULL`)
  on the same questions is 88%.

So two true statements that answer different questions: the **production policy**
commits at 88% and is false-negative-skewed (it errs by abstaining, FP=6 vs
FN=23); the **swarm under stress arms on a negative-rich set** commits at 58% and
is false-positive-skewed. The brief measured the second and read it as the first.
Both belong in the writeup, clearly separated. The negative-gold evidence is
almost entirely NL: FR carries 1 negative binary gold, the SEL-1 yes-skew, so any
"says yes on X% of negatives" claim generalises only as far as NL and MT do.

---

## 1A. The decisive reframe: ODMI is self-report, and most false positives are measurement mismatches

Added 2026-06-24 after tracing the false positives to their source. This is the
most consequential finding in the document, and it reframes the headline.

**ODMI is a country self-report questionnaire validated by Capgemini, across all
four dimensions.** The official methodology confirms the answers are "collected
through a questionnaire sent to the national open data representatives",
coordinated by Capgemini for the Publications Office (data.europa.eu / Capgemini).
The validation action is recorded per (question, country) in
`ground_truth.decision`, with three values over all 5,148 rows:

- `confirm` 3,249 (63%): the country's self-reported answer was accepted as-is
- `complement` 1,385 (27%): the country's answer was kept and the assessor added evidence
- `change` 514 (10%): the assessor overrode the country's answer

This holds on every dimension, not only Quality. The earlier project assumption
(only some Quality questions self-report) was wrong: first-person country
explanations ("we chose not to invest in such activities last year") sit in
Portal and Impact too.

**Swarm accuracy is governed by whether the gold is itself web-evidenced, not by
dimension.** Deduplicated binary yes/no pairs, all countries, by decision:

| decision | pairs | abstain | accuracy (committed) | false positives |
|---|---:|---:|---:|---:|
| `complement` (assessor added evidence) | 249 | 24% | 92% | 1 |
| `confirm` (country's word accepted) | 360 | 29% | 78% | 36 |
| `change` (assessor overrode) | 55 | 42% | 62% | 10 |

The `complement` accuracy is ~92% on every dimension (policy 93, portal 92,
quality 89, impact 92); `confirm` runs 73-88%. So when ODMI's own answer carries
web evidence, the swarm matches it almost perfectly regardless of dimension. The
divergence concentrates where ODMI took the country's unverifiable word.

**This reinterprets the false positives.** The swarm measures the open web and the
national portal; a `confirm` gold often encodes the country's self-reported
*internal* action, which is not on the web. ODMI's own explanations for the NL
false positives show the pattern:

- PT27 / PT25 (gold `no`): "Last year we chose **not** to invest in such
  activities..." The swarm cited real 2019-2020 activity; the country reported it
  paused in the assessment period. The quote is real, on-topic and time-mismatched.
  A genuine error, but one the swarm cannot fix from the open web, because the
  truth is unpublished and lives only in the self-report (the deny-listed key).
- I22 (gold `no`): impact *stories* exist (ODMI lists them) but the question asks
  for impact *data*. A definitional gap.
- Q23 (gold `no`): the country self-reported it does not formally use a quality
  model; the portal merely documents the 5-star concept. The swarm over-read a
  mention.

This is why no confidence number and no second reader catches them. The
Researcher, the production Verifier (which passed 217 of 223 NL false positives,
agreeing `yes` after its own independent search, mean confidence 0.82, substring
gate passing on 221/223) and an added Opus entailment scorer all read the same
real portal evidence and reach the same `yes`. The failure is not low confidence
or thin evidence; it is a mismatch between what the web shows and what the country
reported.

**Consequence for the evaluation.** Stratify every accuracy, abstention and
false-positive figure by `decision`. A swarm-vs-`confirm` disagreement on an
internal-action question is a measurement mismatch, not automatically a swarm
error (the D22 caveat, quantified). The honest headline is conditional: where the
gold is web-evidenced (`complement`), the swarm is ~92% accurate across all
dimensions; where ODMI took the country's word (`confirm`), it is ~77%, and that
is where the false positives sit.

Definitions confirmed (2026-06-25). The three-way taxonomy is no longer inferred:
the official 2022 ODMI methodology paper lists "Complement the results with
additional desk research" as a named assessment step (step 4 of the work
approach), and the 2024 methodology describes the research team validating
submitted responses while respondents "confirm or change" prefilled prior-year
answers. The field values match these actions, and the score/explanation
signatures in the data corroborate them: `complement` rows are 100% explained,
their explanations average ~1,830 characters (4x the others) and they score 0.87
of max; `change` rows carry the highest zero-score rate (40%); `confirm` is the
accepted-as-submitted baseline. So `complement` = answer kept with assessor-added
web evidence, `change` = assessor overrode, `confirm` = the country's word
accepted. Reproduce the table with `evaluation/selfreport_decision_split.py` over
the canonical DB; counts drift by one or two while a dispatch window writes the
DB, so treat them as a snapshot, not a constant.

---

## 2. Task A: calibration

### 2.1 Reliability

Accuracy of committed binary answers by `answer_confidence` band:

| band | pooled | production | NL only |
|---|---:|---:|---:|
| [0.50,0.65) | 84% (n32) | 81% (n26) | 100% (n2) |
| [0.65,0.80) | 67% (n599) | 82% (n95) | 57% (n322) |
| [0.80,0.90) | 64% (n249) | 100% (n50) | 48% (n147) |
| [0.90,1.00) | 87% (n174) | 98% (n64) | 78% (n78) |
| ECE | 0.105 | 0.121 | 0.205 |
| MCE | 0.387 | 0.348 | 0.450 |
| Brier | 0.216 | 0.101 | 0.287 |

Read the pooled column and calibration looks broken: accuracy is non-monotonic,
it falls from the [0.50,0.65) band (84%) into the [0.80,0.90) band (64%) before
recovering. The fine-grained reliability diagram makes the worst point explicit:
the [0.80,0.90) bin has mean confidence 0.84 against 0.64 accuracy, a 0.20
overconfidence gap, the largest on the curve.

But the production column is roughly monotonic and well behaved (81 -> 82 -> 100
-> 98) with a Brier of 0.101, less than half the pooled 0.216. The NL column is
the worst of all, with a sharp dip to 48% accuracy at confidence 0.80-0.90. So
**the non-monotonicity is largely a pooling and config-mixing artefact, not a
fixed property of the confidence**: in clean production data a higher stated
confidence does track a higher accuracy. The honest claim is narrower than "the
confidence is miscalibrated": it is "the confidence is miscalibrated on the
hard, negative-rich data, and on the degraded arms, which is exactly where a
commit gate has to earn its place".

The reliability SVG (`evaluation/results/reliability_diagram.svg`) plots pooled
against production on the same axes and drops into the manuscript without
re-rendering.

### 2.2 The catalogue-route theory is refuted

The brief proposed that the high-accuracy 0.90-1.00 band is the deterministic
catalogue route rather than calibrated LLM confidence. It is not.

- There are exactly 9 catalogue-routed committed rows in the whole DB. All 9 are
  Finland (a held-out country), all Quality band questions, all at the hard-coded
  0.95.
- They are 9 of the 189 all-shapes commits in the >= 0.90 band, 5%.
- **Zero** of them are binary. The binary 0.90-1.00 band (n=174 pooled) contains
  no catalogue rows at all.

So the high-confidence accuracy on binary questions is the web LLM's own
confidence, not a deterministic bypass. A useful side effect: the dev and
production binary calibration above is measured with no catalogue contamination
whatsoever.

### 2.3 Theory 1 confirmed: the false positives are the confident answers

The brief's first theory was that `answer_confidence` tracks fluency, not
evidence, so it peaks exactly when the model has built a plausible-but-wrong
"yes". The data confirm it directly.

Mean `answer_confidence` by outcome, committed binary, pooled-dev:

| outcome | n | mean confidence |
|---|---:|---:|
| correct | 576 | 0.775 |
| false positive (said yes, gold no) | 242 | 0.767 |
| false negative (said no, gold yes) | 40 | 0.642 |

A correct commit and a false positive are **indistinguishable** by confidence
(0.775 vs 0.767). If the confidence reflected evidential support, the false
positives, where the evidence does not in fact support "yes", would sit lower.
They do not. NL repeats it: correct 0.782, false positive 0.773.

The false-positive rate on negative golds rises with confidence rather than
falling (pooled-dev, non-cumulative bands, Wilson CIs):

| confidence band | n negatives | FP rate |
|---|---:|---:|
| [0.50,0.65) | 16 | 6% [1,28] |
| [0.65,0.80) | 220 | 65% [58,71] |
| [0.80,0.90) | 82 | 98% [92,99] |
| [0.90,1.00) | 19 | 89% [69,97] |

The swarm's most confident commits on `no`-gold questions are 98% wrong. The few
correct `no` commits sit in the lowest band (94% of the 0.50-0.65 negatives are
correct). Confidence and correctness move in opposite directions on the negative
class. Section 4 shows why.

---

## 3. Task B: the threshold sweep and the precision-recall frontier

For each floor t from 0.50 to 0.90, commit a pair iff its candidate confidence
(the committed answer's, or the best pre-abstention candidate for an abstained
pair) is >= t. This recovers the commit/abstain decision at any floor, above and
below the current 0.65. The verifier verdict is held fixed at what it actually
was; for the downward direction this over-credits pairs the Verifier rejected,
so the script reports that count and it is shown below.

**pooled-dev binary** (N=1319 gold pairs, 592 negative golds; of 360
abstained-with-candidate pairs, 213 were verifier-rejected so the sub-0.65 rows
are optimistic):

| floor | committed | coverage | precision [95% CI] | recall | FP on committed negatives |
|---:|---:|---:|---:|---:|---:|
| 0.50 | 1093 | 83% | 67% [64,69] | 55% | 60% |
| 0.65 | 837 | 63% | 67% [63,70] | 42% | 75% |
| 0.70 | 646 | 49% | 67% [63,70] | 33% | 87% |
| 0.80 | 339 | 26% | 71% [66,76] | 18% | 96% |
| 0.85 | 242 | 18% | 77% [71,82] | 14% | 95% |
| 0.90 | 136 | 10% | 87% [80,91] | 9% | 89% |

The frontier is flat where it needs to bend. Raising the floor from 0.65 to 0.80
moves precision from 67% to 71% (overlapping CIs, not a real gain) while coverage
collapses from 63% to 26%. Precision only reaches a useful 87% at t=0.90, where
coverage is 10% and you have abstained on nine pairs in ten. And the
false-positive rate on the negatives you do commit gets **worse** as you raise
the floor, from 60% to 96%, because the correct `no` answers are the
low-confidence ones and they drop out first.

NL alone is worse: precision is pinned at 56-57% from 0.50 all the way to 0.85.
On the hard data the confidence is close to useless as a ranker at any floor.

Production-dev (N=295, only 41 negative golds, all easier) is the mirror image:
precision climbs cleanly from 88% to 99% as t goes 0.50 to 0.80, and the
negative false positives fall to zero. The floor works perfectly where you do not
need it (easy, yes-skewed) and fails where you do (NL, negative-rich).

**Conclusion for Task B: no single global threshold on `answer_confidence`
separates right from wrong on the data that matters.** This is the calibration
result made operational: where accuracy is non-monotonic in confidence, moving a
floor trades coverage for nothing.

By shape, this is a binary-question instrument in practice: the percentage,
ordinal and count shapes either abstain (their gold lives on the deny-listed MQA
or is a self-report) or route through the deterministic catalogue at a fixed
0.95, so a learned confidence floor has almost nothing to act on there.

### Reconciling with EXP-10

EXP-10 swept the floor **downward** only (0.65 / 0.55 / 0.50), found recovered-
answer precision below the 0.80 adoption bar, and kept 0.65, noting the negative
false-positive rate was "flat across floors" and that a future run "could revisit
the 0.80". This is consistent with the result here, not contradicted by it.
EXP-10's flat negative FPR uses the all-negatives denominator (lowering the floor
adds few new false positives because the new commits are mostly correct `no`s).
The sweep here uses the committed-negatives denominator (of the negatives we
commit, what share are wrong), which is the precision-relevant view and which
rises with the floor. Both are true; they answer different questions. The upward
direction EXP-10 deferred is the one that shows the floor cannot buy precision,
and that is the gap this document fills.

---

## 4. Task C: do the two confidences predict correctness?

AUROC of each confidence against committed-answer correctness, with Hanley and
McNeil 95% intervals:

| cut | AUROC answer_conf | AUROC retrieval_conf | corr(ans, ret) |
|---|---:|---:|---:|
| pooled binary | 0.553 | 0.587 | 0.825 |
| pooled-dev binary | 0.547 [0.506,0.587] | 0.587 [0.547,0.626] | 0.819 |
| NL binary | 0.521 [0.472,0.570] | 0.558 [0.510,0.606] | 0.742 |

Both are close to the 0.50 no-skill line. `answer_confidence`, the number five
gates depend on, is barely above chance and its NL interval includes 0.5.
`retrieval_confidence` is a shade better and significantly above chance, but
still inside the conventional "no useful discrimination" zone (< 0.6), and the
two are 0.82 correlated, so there is little independent signal to combine. Within
the modal `answer_confidence` value of 0.72, `retrieval_confidence` does separate
correct from wrong a little (AUROC ~0.62-0.68), so it carries marginal
incremental information, but not enough to gate on.

### Why the single number cannot work

The decomposition is the cleanest result in this document. On pooled-dev binary:

- mean confidence when the swarm says **yes** = 0.787; when it says **no** =
  0.661. The model is systematically about 0.13 more confident whenever it
  commits a "yes", whether or not "yes" is right.
- AUROC of `answer_confidence` **within positive golds** (correct = yes) =
  **0.837**: strongly pro-predictive.
- AUROC **within negative golds** (correct = no) = **0.173**: strongly
  anti-predictive. A higher confidence ranks the wrong "yes" answers above the
  correct "no" answers.

The two opposite-signed halves average to the pooled 0.547, near chance. So
`answer_confidence` is a proxy for "the answer is yes", not for "the answer is
correct". NL shows the same flip (0.757 within positives, 0.240 within
negatives). This is the mechanism behind every symptom above: the non-monotonic
calibration, the flat precision frontier, the rising false-positive rate. A
single threshold cannot work because the confidence-optimal cut has the opposite
sign on the two classes. You would want a high floor on `yes` claims and a low
floor (or none) on `no` claims, which is not a single number.

It also hands back a usable signal that the current policy throws away: a
**low** confidence on a committed answer is a weak indicator that the answer is a
correct "no". The 0.65 floor discards exactly those.

---

## 5. Redesign proposal

The findings point one way: stop gating on one self-reported scalar that encodes
the label, and gate on an evidence-grounded, class-aware, calibrated score.

### 5.1 Decompose the commit score

Replace the single `answer_confidence` gate with a product of three signals that
mean different things:

```
commit_score = retrieval_reliability  x  entailment  x  source_independence
```

- **retrieval_reliability**: is the source real, current, authoritative. The
  existing `retrieval_confidence` already aims at this and already ranks
  correctness slightly better than `answer_confidence`. The stored, computed
  `domain_trust_score` (VAL-3) is a second, deterministic estimate of the same
  thing that currently gates nothing at all (VAL-4, "a dial wired to nothing");
  fold it in.
- **entailment**: does the quoted passage actually prove the specific label.
  This is the signal the system lacks. The Verifier judges it qualitatively
  (pass/fail) but never emits it as a number; `verifier_confidence` is confidence
  in the verdict, not in the entailment. Have the Verifier return an explicit
  P(evidence entails claim), the way an NLI model would, and gate on it.
- **source_independence**: did the evidence come from somewhere other than the
  claimant (a self-report ceiling, D29). Deterministic from the URL and the
  question type.

### 5.2 Make the policy class-aware

Section 4 says a symmetric floor is the wrong shape. Treat the two directions
differently, the way `docs/ABSTENTION_TAXONOMY.md` argues the "no" asymmetry
demands:

- a **yes** commit needs positive entailment: a passage that states the feature
  or figure exists.
- a **no** commit needs a documented exhaustive non-discovery: a fixed,
  pre-registered set of targeted "does X exist" queries that all come back empty,
  not just a low confidence. This converts the large block of correct-`no`
  abstentions (the taxonomy's E+G with `no` gold, ~160 pairs) into commits
  without trusting a scalar, and it is the one change that attacks the
  false-negative tail of the production policy.

### 5.3 Calibrate, then gate

Whatever score is used, fit a post-hoc calibration map (isotonic or Platt) on the
dev set and apply it on held-out, so a stated 0.7 means 0.7. Calibration is a
monotone transform, so it cannot fix the within-negative sign flip on its own;
that is what 5.1 and 5.2 are for. But it makes the abstain/commit cutoff
interpretable and is close to free to fit from stored data.

### 5.4 What stays

Keep the 0.65 floor as the shipped default until something beats it on the
pre-registered rule; EXP-10 already validated it downward and nothing here
licenses lowering it. The change is to add the entailment and class-aware gates,
measure them against the floor, and adopt only on the evidence.

---

## 6. Task D: pre-registered designs

Four designs, each one variable, each following the R1-R12 rules of
`docs/EXPERIMENTS_PROTOCOL.md`. Standing constraints for all four: search is DIY
only (D43), pinned, never `--provider auto`; every other knob is pinned to the
production baseline so the named variable is the only thing that moves; dev
countries for tuning (NL is primary because it holds the negative golds, with
MT/NO/FR/AL secondary), the eight held-out countries reserved for one frozen
confirmation after a config is locked. Primary endpoint is the **false-positive
rate on negative golds** (the failure the confidence cannot currently catch),
with abstention rate and balanced accuracy (Youden's J) as co-endpoints, the
majority-class baseline printed beside every accuracy figure (R4). Statistics:
Wilson 95% intervals, McNemar exact on the paired accuracy change, one
confirmatory primary per experiment (R8). Opus is permitted for these runs;
Sonnet quota is exhausted, so the Researcher/Verifier calls would run on Opus and
that is recorded in the receipts.

### EXP-25, entailment-scored Verifier (one variable: entailment gate on/off)

- **Question.** Does gating the commit on an explicit Verifier entailment score
  cut the negative-gold false-positive rate without raising abstention beyond a
  fixed bound?
- **Hypothesis (directional).** The entailment gate lowers the negative-gold FP
  rate relative to the `answer_confidence`-only floor, because it conditions on
  evidence rather than on the label.
- **Arms** (identical pair set, identical evidence, only the gate differs):
  - `conf_floor` (baseline): current policy, commit iff `answer_confidence >= 0.65`.
  - `entailment_gate`: the Verifier additionally returns `entailment in [0,1]` =
    P(the quoted passage proves the label); commit iff `entailment >= 0.70` AND
    not abstain. The 0.70 is fixed here, before the run, from the section 2.3
    bands (the negative FP rate is tolerable only below ~0.65 confidence, so the
    entailment bar is set deliberately higher and independent of the label).
- **Dataset.** NL primary (its 266 negative binary golds give the FP rate power),
  MT/NO secondary; paired, dimension-stratified, achieved counts reported. The
  evidence is frozen from the existing stored snippets so the only new LLM work is
  the Verifier re-scoring; this keeps it a clean replay-plus-one-call design and
  removes retrieval variance.
- **Endpoints.** Primary: negative-gold FP rate, `entailment_gate` vs
  `conf_floor`, McNemar exact on the paired negative pairs. Co-primary: abstention
  rate and balanced accuracy. Secondary (Holm-corrected): per-dimension splits.
- **Adoption rule (fixed now).** Adopt the entailment gate iff the negative-gold
  FP rate drops by at least 15 percentage points AND balanced accuracy does not
  fall AND the abstention rate rises by no more than 10 percentage points. Lock
  the config, then measure once on the held-out set.
- **Registry.** `entailment_gate_v1`. Pre-run requirement: a committed Verifier
  prompt version that emits `entailment`, with a schema field and a unit test;
  the baseline prompt untouched.

### EXP-26, self-consistency confidence (one variable: single vs N-sample)

- **Question.** Does replacing the single self-reported confidence with the
  agreement rate over N independent answer samples predict correctness better and
  catch the confident false positive?
- **Hypothesis.** A confident-but-wrong "yes" is less stable across samples than a
  correct answer, so sample agreement separates them where the scalar does not
  (AUROC of agreement > AUROC of `answer_confidence`, which is 0.55).
- **Arms** (the temperature change is part of the treatment and is declared):
  - `single` (baseline): one Researcher answer at temperature 0, the production
    setting.
  - `self_consistency_n5`: five Researcher answers at temperature 0.7 on the same
    frozen evidence; the committed label is the majority; the confidence is the
    agreement fraction; gate on agreement >= 0.8 (4 of 5).
- **Dataset.** NL primary, MT/NO secondary; paired on the identical frozen
  evidence so only the sampling changes; dimension-stratified.
- **Endpoints.** Primary: AUROC of the agreement score vs correctness against the
  0.55 baseline, with the per-class (within-positive, within-negative) AUROC
  reported because the baseline's failure is the sign flip. Co-primary: negative-
  gold FP rate at the gate. Cost per committed pair (5x the calls) is the
  co-headline; a method that needs five calls to add nothing is a null result and
  is reported as one (R12).
- **Adoption rule.** Adopt iff AUROC rises above 0.65 AND the within-negative
  AUROC rises above 0.50 (it removes the anti-prediction) AND the cost rise is
  justified by the FP reduction under the EXP-25 bar.
- **Registry.** `self_consistency_n5_v1`.

### EXP-27, argue-the-opposite check (one variable: adversarial flip check on/off)

- **Question.** Does an explicit "could this same evidence support the opposite
  label?" pass catch the confident false positive that the current adversarial
  Verifier strategies miss?
- **Hypothesis.** False positives are built from tangential evidence that also
  fits the opposite label, so an opposite-label entailment check fires on them
  specifically.
- **Arms** (one variable, the check):
  - `baseline`: production Verifier.
  - `argue_opposite`: after the normal verdict, a second call asks whether the
    same quoted passage entails the opposite label; if the opposite entailment is
    not clearly lower than the chosen one, the commit is blocked and the pair
    abstains.
- **Dataset.** NL primary (negative-rich), MT/NO secondary; paired, frozen
  evidence; dimension-stratified.
- **Endpoints.** Primary: negative-gold FP rate vs baseline (McNemar exact).
  Co-primary: abstention rate and balanced accuracy. Secondary: how many of the
  caught pairs were the high-confidence (>= 0.80) false positives from section
  2.3, the population this check is designed for.
- **Adoption rule.** Adopt iff the negative-gold FP rate drops by at least 15
  points with an abstention rise under 10 points and no balanced-accuracy loss.
- **Registry.** `argue_opposite_v1`.

### EXP-30 (renumbered from EXP-28 on 2026-07-01), decomposed and calibrated commit score (one variable: scalar vs decomposed-calibrated)

- **Question.** Does the 5.1 decomposed score (retrieval x entailment x source-
  independence), post-hoc calibrated on dev, gate better than the raw
  `answer_confidence`?
- **Hypothesis.** The decomposed score, because entailment is class-symmetric and
  source-independence penalises self-reports, removes the within-negative sign
  flip and so admits a single working threshold.
- **Arms** (one variable, the gating score; both use the same committed answers):
  - `scalar` (baseline): gate on `answer_confidence`.
  - `decomposed_cal`: gate on the calibrated decomposed score. The isotonic
    calibration map is fit on the dev set only and frozen before the held-out
    measurement (no leakage).
- **Dataset.** Fit and tune on dev (NL/MT/NO/FR/AL); one frozen measurement on
  the eight held-out countries. This is the only design that touches held-out
  data, and only once, after the map is locked.
- **Endpoints.** Primary: AUROC and ECE of the decomposed-calibrated score vs the
  scalar, plus the precision-coverage frontier (section 3) for both, on held-out.
  Co-primary: negative-gold FP rate at matched coverage.
- **Adoption rule.** Adopt iff the decomposed score gives a strictly better
  precision-coverage frontier (higher precision at every coverage level present in
  both) on held-out AND its within-negative AUROC exceeds 0.50.
- **Registry.** `decomposed_commit_score_v1`. Note: a free, LLM-cheap precursor
  is in section 8 (re-score from stored columns) and should run first to size
  whether the new entailment call is even needed.

---

## 7. Task E: speculative architectures

Three designs beyond a better scalar, each with the evidence that would confirm
it.

### 7.1 Asymmetric evidence-of-absence protocol

Drop the symmetric floor entirely and make the commit bar depend on the claim
direction. A `yes` commits on positive entailment; a `no` commits only after a
bounded, pre-registered battery of "does X exist" queries all return nothing, a
documented exhaustive non-discovery rather than a low number. The confidence
becomes two separate quantities: strength of positive evidence, and completeness
of the absence search.

Confirming evidence: the within-class AUROC split is already the motivation
(0.84 positive, 0.17 negative). A prototype would be confirmed if it raises
negative-class precision and recall together without lifting the positive-class
false-positive rate, measured on NL and the held-out higher-resource stratum. The
risk to watch is the false positive this could create in reverse (a real feature
the search simply missed), so the absence battery size is the safety knob and is
reported.

### 7.2 Selective prediction with a distribution-free guarantee

Treat the commit/abstain decision as a learned reject option and set the
threshold by conformal risk control rather than a hand-set 0.65. Calibrate on dev
a threshold that bounds the false-positive rate on negative golds at a chosen
level (say 10%) with a finite-sample guarantee, then measure the realised risk
and coverage on held-out.

Confirming evidence: the held-out realised FP rate falls within the conformal
bound while coverage stays above the current policy's. This turns "we picked 0.65
and validated it downward" into "we can promise a negative-FP ceiling and report
the coverage it costs", which is a stronger and more examinable claim. It depends
on a score that is at least weakly predictive within each class, so it composes
with 5.1/EXP-30 (formerly EXP-28) rather than standing alone.

### 7.3 Two-agent debate, commit on the margin

Run two agents on the same frozen evidence, one arguing `yes` and one arguing
`no`, each citing only passages that survive the substring gate. Commit only if
one side concedes or cannot cite a qualifying passage; the confidence is the
margin between the two cases. This attacks the exact failure of section 2.3,
where a single agent is equally fluent for a correct and a fabricated "yes",
because the opposing agent has to find real counter-evidence or fold.

Confirming evidence: the debate margin separates correct commits from false
positives where the scalar confidence (AUROC 0.55) does not, ideally with a
within-negative AUROC well above 0.5. It is the most expensive option (two
argued cases plus a judge per pair), so the bar is that it beats the cheaper
EXP-25/24 on the same negative-gold FP endpoint, not merely that it beats the
scalar.

---

## 8. Prioritised do-next

### FREE (replay over stored rows, no quota)

1. **Re-score from stored signals.** Build a "poor-man's decomposed score" from
   columns already in the DB: `retrieval_confidence`, `domain_trust_score` (the
   VAL-4 dial wired to nothing), the Verifier `substring_check_result`, and
   `verifier_confidence`. Report its AUROC and within-class AUROC against the 0.55
   `answer_confidence` baseline. If a combination of existing signals already
   beats the scalar, EXP-30's new entailment call may be unnecessary; if it does
   not, that sizes the gap the entailment signal has to fill. Highest value, lowest
   cost. (Extends `evaluation/confidence_deepdive.py`.)
2. **Negative-class recovery ceiling.** Replay the abstention trail to count how
   many correct `no` answers the floor and the Verifier currently knock down
   (the section 5.2 target), so the asymmetric protocol has a measured prize
   before any run. (Joins `evaluation/abstention_taxonomy.py` to this analysis.)
3. **Isotonic calibration ceiling.** Fit isotonic regression on dev
   `answer_confidence`, apply on held-out, report the ECE before and after. This
   shows how much pure recalibration buys and confirms (it cannot fix the sign
   flip) that recalibration alone is not enough.
4. **Per-shape and per-dimension calibration tables** for the writeup, already
   emitted by the script, audited once against the dashboard match SQL.

### QUOTA (Opus; Sonnet exhausted)

5. **EXP-25, entailment-scored Verifier.** The single highest-leverage run:
   adds the missing signal, frozen evidence so only the Verifier call is new,
   directly targets the negative-gold FP rate. Run after free step 1 confirms the
   stored signals do not already suffice.
6. **EXP-27, argue-the-opposite.** Cheap second call, targets the same confident
   false positive from a different angle; run alongside EXP-25 on the same NL set
   for a paired comparison.
7. **EXP-26, self-consistency.** Five-sample agreement; run third because it is
   the costliest per pair and the prior (sampling stability helps) is the
   weakest.
8. **EXP-30 (formerly EXP-28), decomposed and calibrated score.** Last, because it depends on the
   entailment signal from EXP-25 and is the one design that spends the single
   held-out measurement.

---

## 9. Limitations

- The pooled population is not independent (a pair recurs across arms) and mixes
  configurations; its CIs are optimistic and it is reported only for continuity
  with the prior numbers. The clean cuts are production and dev.
- The negative-gold evidence is concentrated in NL, with a smaller MT
  contribution; the within-negative sign flip is shown on NL and pooled-dev and
  should be re-confirmed on the held-out higher-resource stratum (BE, SE) once a
  config is locked, never before.
- The downward portion of the threshold sweep over-credits verifier-rejected
  abstentions; the script reports that count (213 of 360 on pooled-dev) so the
  optimism is bounded and visible. The upward portion (the load-bearing result)
  is exact.
- AUROC is a ranking measure; it says the scalar cannot order correct above
  incorrect, not that no transform of it could help. Section 4's within-class
  split is the stronger, transform-invariant statement.
- All of this is binary-question evidence. The band shapes route through the
  catalogue or abstain on the deny-list, so the confidence framework as a gate is
  a binary-question instrument, and the writeup should say so.

## Change log

| Date | Change |
|---|---|
| 2026-06-24 | Created. Reproduced the pooled headline (1065 / 744 / 268 FP), decomposed it (NL-under-degraded-arms vs 88% production), refuted the catalogue-band theory, confirmed Theory 1 (FPs as confident as correct answers), showed the precision frontier is flat (no working single floor), and proved the mechanism (within-positive AUROC 0.84, within-negative 0.17; the confidence encodes the label, not correctness). Added the decomposed/class-aware/calibrated redesign, pre-registered EXP-25 to EXP-28, and the free-vs-quota do-next list. Analysis in `evaluation/confidence_deepdive.py`; SVG and JSON in `evaluation/results/`. |
| 2026-06-24 | Step 1 (free): no stored signal beats answer_confidence (`evaluation/confidence_signals_replay.py`); all anti-predictive on the negative class. Step 2 (Opus smoke, `evaluation/exp25_entailment_smoke.py`): an explicit entailment score does not separate correct from false positives (0.74 vs 0.75) because the FPs carry genuinely strong evidence. Traced the FPs to source: the production Verifier passed 217/223 NL FPs after its own independent search. Added section 1A, the self-report reframe: ODMI is a country self-report questionnaire validated by Capgemini (`decision` confirm/complement/change, all dimensions), source-verified; swarm is 92% accurate on web-evidenced (`complement`) golds and 78% on accepted-self-report (`confirm`) golds, where the false positives sit. `evaluation/selfreport_decision_split.py`. |
| 2026-06-25 | Confirmatory pass on production Sonnet (quota restored). **EXP-25 / EXP-27 both NULL and harmful** (`evaluation/confidence_gates.py`, NL n=50, 25 committed negative golds): the entailment gate raises the negative-gold FP rate 0.76 to 1.00 and halves Youden's J, the argue-opposite margin gate likewise, because the correct `no` commits are the low-entailment ones and abstain first while the confident FPs (entailment_for 0.74 vs correct 0.68) sail through. McNemar caught 3/19 and 2/19 FPs (p=0.25, 0.50), 0 high-confidence. Pre-registered `exp25_entailment_gate` / `exp27_argue_opposite`; EXP-26/25 held (same null mechanism; EXP-28 spends the frozen held-out set). **NL false-positive audit** (`evaluation/nl_fp_audit.py` + `nl_fp_audit_adversarial.py`, 22 questions over frozen evidence, two framings). Charitable pass: 1 genuine swarm error on Opus (PT25), 2 on Sonnet (I8-d, PT4), rest definitional/self-report — a ~5-9% error rate. Adversarial advocate pass (Opus told to defend the swarm's `yes` and argue ODMI's `no` is wrong): **0/22 gold_wrong** (the swarm is never vindicated), 11/22 clear over-reads with the gold standing, 11/22 genuinely ambiguous. So the genuine-error rate **brackets ~5% (charitable) to ~50% (strict over-read)** and is framing-dependent; the robust, framing-independent findings are that no NL FP is a case of the swarm being right against a stale gold, and the disagreements are strict-vs-loose question readings and self-report that no evidence gate can resolve. **Decision definitions confirmed** against the official 2022/2024 methodology (section 1A caveat resolved). **Dashboard**: `dashboard/lib/db.py::accuracy_by_decision` + Analytics self-report split surfaces the confirm/complement/change stratification; all 6 production FPs sit on `confirm` golds. Net: no evidence-grounded commit gate can catch the confident FPs; the answer is decision-stratified reporting + D22 staleness adjudication, not a better gate. |

| 2026-07-01 | The held decomposed-score design is renumbered EXP-28 -> EXP-30. It was never run and never registered (no `experiments` row, no data), and the live architecture-ablation ladder dispatched on 2026-07-01 claimed `exp28_arch_ablation` in the registry and in run data. Same reconciliation rule as D49: the programme with run data keeps the number. |
