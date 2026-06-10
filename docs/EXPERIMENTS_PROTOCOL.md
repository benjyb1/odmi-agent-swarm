# Experiments Protocol (pre-registration)

Pre-registered 2026-06-02; amended 2026-06-02 after adversarial methodology
review (see change log). This document fixes the design of the search
experiments **before** the runs, so the results cannot be reverse-fitted to a
hypothesis. The git commit that adds this file is the pre-registration record;
its timestamp predates every result file it governs. The status board lives in
`EXPERIMENTS.md`; the machine registry is the `experiments` SQLite table (D27).
Rationale for individual choices lives in `SPEC.md` (D22, D27, D29, D31).

If a run forces a change to anything below, the change is made here first, in a
new dated commit, with a one-line note in the change log at the foot of this
file. No silent edits.

---

## 0. Rules every experiment follows

Sections 1 to 11 work the search experiments in detail. This section lifts the
parts that bind **every** experiment, search or not, into one numbered checklist.
Each per-experiment pre-registration (this file, `EXPERIMENTS_VERIFIER.md`, and
the optimisation sections below) states which of these it meets and names any it
cannot. A rule an experiment breaks is a limitation written into that experiment,
not a silent omission. Section 12 grades the existing experiments against the
list.

**R1. Pre-register before the data.** The design is fixed in a dated commit whose
timestamp predates the result file. Any change is a new dated commit with a
change-log line. The run decides the answer, nothing else.

**R2. Pair within the item.** Every arm sees the identical item set, and for
provider work the identical query, so a difference is attributable to the arm and
not to an easier question (sections 3, 4).

**R3. Sample by a rule fixed in advance.** Stratify by ODMI dimension, draw with a
named RNG seed, write the selected IDs into the results JSONL, and report the
achieved per-stratum counts. No hand-picking of individual items (section 3).

**R4. Refuse a base-rate-degenerate sample.** This is the France lesson, and it is
a rule rather than a footnote. France's binary gold answers run 119 `yes` to 1
`no`, so a model that answers `yes` to everything scores about 99% and a false
`yes` never surfaces. Accuracy on that sample measures nothing. Three
requirements follow.

- (a) **Report the majority-class baseline beside every accuracy figure**, and
  require the headline to beat it. The baseline is the score of the constant
  majority-class predictor on the same items. An accuracy that does not clear it
  is not a result.
- (b) **When the classes are skewed, the headline metric is balance-aware:**
  Youden's J, MCC, balanced accuracy, or the per-class rates (catch rate on the
  minority class, false-positive rate on the majority), in place of raw accuracy.
  EXP-6 already does this; the optimisation experiments below adopt it.
- (c) **Pick the evaluation country by minority-class share, subject to a
  well-resourced-language constraint.** A country needs enough negative golds for
  a false positive to show up (the discrimination requirement), and a
  well-resourced language so a poor result is the pipeline's doing and not the
  language channel (the no-confound requirement). The two pull the same way here.
  Malta is the clearest pick: English is an official language and most of its
  open-data estate is in English, and it still carries about 30 `no` binary golds.
  The selection table, computed from `ground_truth` over binary questions with a
  yes/no gold (this denominator, not the all-question yes-share quoted in EXP-7):

  | Country | Language | binary yes / no | No-share | majority baseline | Role |
  |---|---|---|---|---|---|
  | Malta (MT) | English (official) | 68 / 30 | 31% | 69% | primary test country |
  | Netherlands (NL) | Dutch (well-resourced) | 93 / 26 | 22% | 78% | secondary (pipeline already runs NL) |
  | Belgium (BE) | French / Dutch / German | 91 / 24 | 21% | 79% | viable, no pairs yet |
  | Sweden (SE) | Swedish | 94 / 27 | 22% | 78% | viable, no pairs yet |
  | France (FR) | French | 119 / 1 | 1% | 99% | **barred as a primary set**; degenerate-baseline contrast only |
  | Estonia (EE) | Estonian | 117 / 3 | 2% | 98% | barred as primary (and a low-resource language) |
  | Lithuania (LT) | Lithuanian | 120 / 0 | 0% | 100% | unusable: zero negative golds to discriminate |

  A country whose binary gold is more than roughly 90% one class is barred as a
  primary evaluation set. It may appear only as a deliberate degenerate-baseline
  contrast, labelled as such, to show the trap empirically. This rule lands on two
  already-pre-registered choices: EXP-1 ran on France, and EXP-3 anchors on
  Estonia with Lithuania as a "discriminating control" that holds zero negative
  binary golds. Both are graded in section 12.

**R5. Blind the judge, swap positions.** Any LLM judge reads blinded evidence,
each pair judged twice with the arms swapped, rendered at equal passage count and
reduced to the registrable domain, from a single frozen snapshot, at temperature
0 (sections 4, 5).

**R6. Check the judge against itself and another family.** A cross-family judge
re-rates a seeded subsample (Krippendorff's alpha), and an answer-blind variant
measures how far the gold label is doing the work. Agreement statistics use the
answer-blind variant (sections 4, 5).

**R7. Break a confound by design, then report the residual.** Where two factors
are tangled (maturity and language, provider and host), add a discriminating
control rather than assert independence. Report the part the design cannot
separate as the headline limitation, and state partial identification as
"consistent with", never "proven" (sections 3, 11; EXP-3).

**R8. Fix the statistics before the run.** Proportions as Wilson 95% intervals,
the interval being the result; paired tests on the discordant pairs (McNemar
exact for accuracy, sign test for win shares, Wilcoxon for cost); one
confirmatory primary per experiment, the rest secondary and Holm-corrected;
non-inferiority only against a margin justified by a decision rule (section 5).

**R9. Cost per item, retries counted, cold cache.** Cost is measured per item, not
per call or per search, because a leaner setting that retries more can cost more
per item. Every cost run starts cold with caching off, unless the cache is itself
the treatment, which is declared (sections 4, 5; EXP-2).

**R10. Apply the deny-list equally and before retrieval.** The evaluation-cycle
deny-list (`agents/tools/blocked_domains.py`) filters every arm pre-retrieval, so
no arm competes for a different number of usable slots. Verified before each run
(section 4).

**R11. Fix the sample, do not peek and extend.** Run the pre-specified n, then
analyse once. A quota-truncated run is reported as a partial with its achieved n;
no item is selectively re-run to move a number (section 5).

**R12. Report the negative, log what was dropped, keep the receipts.** A null or
unflattering result is the finding. Any coverage bound (a cost ceiling, a top-N
cap, a dropped country) is logged with what it removed. Every judgement streams to
JSONL with its raw output and evidence, and the experiment is entered in the D27
`experiments` table before the run, so an examiner replays it from logs alone
(sections 6, 8).

---

## 1. Why pre-register

EXP-1 reported a headline of "DIY not worse than Tavily 78% of the time" on a
decisive sample of n=18. A number that small, chosen after the fact, is easy to
flatter. Pre-registration commits us to the sample, the endpoints, the analysis,
and the stopping rule in advance, so the only thing the run decides is the
answer. EXP-1 is treated as a pilot that sizes the refreshed runs.

## 2. Endpoints (co-primary)

Every experiment reports two endpoints and the agreement between them.

- **E1, deterministic accuracy.** The finalised swarm answer joined to the ODMI
  `ground_truth` row for the same (question, country) and classified
  `match` / `near_match` / `differ` / `no_ground_truth` by `_MATCH_STATUS_SQL`
  (`dashboard/lib/db.py`). Objective, reproducible, no judge. Reported on the
  **full** finalised set, with the deny-list both-fail pairs shown, never hidden.
- **E2, adjudicated evidence quality.** A blind, position-swapped LLM judge
  compares two arms' retrieved evidence against the ODMI gold answer and returns
  one of `{arm_a, arm_b, tie, both_fail}`. Reported as the full four-way
  distribution first; the head-to-head among *decided* pairs (section 5) is a
  labelled conditional. Harness: `evaluation/diy_vs_tavily.py` and successors.
- **Agreement.** Whether the arm that wins on evidence quality (E2) also wins on
  final accuracy (E1) is reported as a finding. Because the answer-given judge
  can agree with E1 by construction (section 5, judge-leakage control), the
  agreement statistic is computed against the **answer-blind** judge variant.

## 3. Sampling

- **Paired throughout.** Every arm sees the identical pair set and, for provider
  comparisons, the identical query string (the Researcher's first stored query
  for that pair). Differences are then attributable to the arm, not to a
  different question or a different query.
- **Stratified by ODMI dimension, achieved counts reported.** Samples are drawn
  round-robin across Policy / Portal / Quality / Impact. Round-robin does not
  guarantee equal counts when the dimensions are uneven (once the smallest is
  exhausted the tail fills from the rest), so the **achieved per-dimension
  counts are reported with every result** and the sample is described as
  approximately balanced, not even. The selection rule is fixed here, before the
  run. No hand-picking of individual pairs.
- **The web-answerable restriction is never a system-wide claim.** Many Quality
  questions both-fail because the gold answer sits on the deny-listed
  `data.europa.eu` (the MQA) or is a national self-report; those pairs carry no
  signal about *relative* retrieval quality, so the E2 head-to-head is taken
  among decided pairs. But the primary report always shows the full set including
  both-fails, so "DIY at parity" can only ever be read as "on pairs the open web
  can answer", never as system-wide parity (the excluded Quality dimension is
  where the swarm most often fails). The web-answerable subset is a labelled
  conditional, not the headline denominator.
- **Pre-specified, not outcome-conditioned.** The web-answerable stratum is
  defined by one objective, fully enumerable rule fixed in advance: **exclude the
  Quality dimension** (`questions.dimension = 'Quality'`). Quality is excluded
  because its gold answers live on the deny-listed `data.europa.eu` MQA or are
  national self-reports, so they both-fail and carry no retrieval-quality signal;
  the empirical both-fail concentration in Quality (D29) confirms it. No finer
  per-question self-report judgement is applied, to keep the criterion a column
  filter rather than an investigator call. For FR this leaves 87 of the 103
  finalised pairs (Impact 31, Policy 21, Portal 35; Quality 16 excluded). The
  restriction is never conditioned on a prior run's verdict. EXP-2a is the one
  declared exception: it reuses the answerable FR pairs identified by EXP-1,
  which conditions on an earlier outcome. That is acceptable for a direct
  follow-up and is named as a limitation in EXP-2a.

## 4. Bias controls

Controls tagged **(pre-run)** are specified here and built per section 9 before
the first run; they are **not yet in force** in the current harness. The untagged
rows (paired design, position-swap, temperature, achieved-count reporting) are
already in force. Nothing below is a claim about apparatus that exists today
unless it is untagged.

| Threat | Control |
|---|---|
| Question difficulty varies pair to pair | Paired, within-pair comparison; same pairs across all arms. |
| Cherry-picking pairs | Pre-specified stratified sampling, rule fixed before the run; achieved per-dimension counts reported. |
| Judge position bias | Each pair judged twice with arm positions swapped; a pure flip nets to a tie and is flagged inconsistent. Position-consistency rate reported. |
| Provider fingerprinting from block length | **(pre-run)** Both arms rendered with an **equal passage count** (capped to `min(n_a, n_b)`) and an equal per-passage character cap, so neither block is systematically longer. |
| Provider fingerprinting from URL host | **(pre-run)** URLs reduced to the registrable domain before rendering. The host is still a partial tell (a judge may recognise a domain), so this is declared a **residual, uncontrolled tell** in section 11, not claimed closed. |
| Same-family self-preference (Opus rating Claude-extracted DIY evidence) | **(pre-run)** A cross-family judge (Gemini) re-rates a seeded random subsample; Krippendorff's alpha and raw agreement reported (section 5). |
| Judge answer-leakage (gold label collapses the task to keyword spotting) | **(pre-run)** An **answer-blind** judge variant (gold label withheld; judge ranks which evidence better establishes *an* answer) is run on the cross-family subsample; the delta against the answer-given judge is reported. The E1/E2 agreement statistic uses the answer-blind variant. |
| Data leakage from the evaluation cycle, applied **unequally** across arms | **(pre-run)** The `data.europa.eu` deny-list (`agents/tools/blocked_domains.py`) must be applied **pre-retrieval in every arm**. DIY currently fetches every Serper SERP slot and scrubs deny-listed URLs only afterwards, so a deny-listed slot is wasted in DIY but excluded at query time for Tavily/Brave. The pre-run requirement (section 9) is to filter the DIY SERP through `is_blocked` before fetching, so all arms compete for the same number of usable slots. Verified before each run. |
| Content drift between arms across a long throttled run | **(pre-run)** All arms' raw evidence for a given pair is fetched in a **single pass** and frozen to the results snapshot; the judge reads only the frozen snapshot, so a page edit or SERP rerank mid-run cannot confound the comparison. |
| Run-order / cache reuse inflating a later arm's apparent thrift | **(pre-run)** Every cost condition starts from a **cold** cache and caching is disabled for the duration, so no condition (including the first) gets free SERP/snippet hits. Verified as a pre-run check. |
| Temperature noise | Temperature 0 in the LLM wrapper, unchanged. |

## 5. Statistics

Fixed in advance. This document is written **before** the apparatus exists (the
change log records no runs), so it states the analysis in the future tense on
purpose: the analysis code does not yet exist and will be implemented,
unit-tested, and committed before the first run (section 9). Until then the tests
below are specifications, not yet running code. One pre-specified **primary
comparison** per experiment; everything else
(per-dimension, per-condition splits) is **secondary and exploratory**, labelled
as such, and Holm-corrected within the secondary family before any claim.

- **Proportions** (E1 match rate; E2 win shares): point estimate with a **Wilson
  score 95% confidence interval**. The interval, not the point, is the result.
- **The E2 primary is a paired test on decided head-to-heads.** Ties and
  both-fails are excluded from the test (and reported separately, never folded
  into a "not worse" numerator). Among pairs the judge decided for one arm, the
  count of DIY wins vs comparator wins is tested with an **exact binomial sign
  test** against the null of symmetry (0.5); for the paired accuracy outcome
  (match vs not), **McNemar's exact test** on the discordant pairs. Discordant
  and decided-pair counts are always reported.
- **Non-inferiority** is declared only if the lower bound of the Wilson 95%
  interval on the **DIY win share of decided pairs** exceeds `0.5 - delta`, with
  `delta = 0.10`. The margin is justified by a decision rule, not asserted: we
  would only change the swarm's default provider for a win share of 0.60 or more,
  so a shortfall under 0.10 below parity is not operationally meaningful. Ties
  are never counted as DIY successes.
- **Cost per pair** (paired, skewed, small n): **Wilcoxon signed-rank** on the
  per-pair total cost; median delta and IQR reported.
- **Judge reliability:** **Krippendorff's alpha** (nominal, four categories) for
  Opus vs Gemini on the subsample, plus raw agreement overall and **per
  category** (because the both-fail category dominates and a single kappa is
  distorted by that prevalence imbalance). Position consistency = fraction of
  pairs whose two swapped orientations agreed.
- **Reliability subsample:** a simple random sample without replacement,
  **30% of judged pairs, RNG seed 20260602**. The seed and the selected pair IDs
  are written into the results JSONL so the draw is reproducible and verifiably
  not post hoc.
- **Provider ranking from pairwise verdicts (EXP-4, EXP-5):** pairwise verdicts
  can be intransitive under a noisy judge, so the ranking is assembled by
  **Copeland count** (wins minus losses across the pairwise matrix), ties broken
  by total decided wins. Any intransitive triple is reported, not silently
  resolved.
- **Multiple comparisons across experiments:** EXP-1 is the single confirmatory
  primary. EXP-4 and EXP-5 reuse EXP-1's FR pair set and are treated as
  **exploratory** extensions, not independent confirmatory tests, so they do not
  each claim a fresh confirmatory result on the same sample. This shared-sample
  dependency is named in section 11.
- **Stopping rule:** fixed sample. No optional stopping, no peeking-then-extending.
  Run the pre-specified n, then analyse once. If quota is exhausted mid-run, the
  partial is reported as partial with the achieved n; we do not selectively
  re-run pairs to move a number.

## 6. Honest reporting

Negative results are findings (CLAUDE.md, METHODOLOGY.md). "DIY is no better than
Tavily", or "the lean knobs cost more once retries are counted", is the result
and is reported plainly. Any coverage bound (a cost ceiling, a top-N cap) is
logged with what it dropped. Every judgement is written to a JSONL with both raw
verdicts and the evidence, so an examiner can replay it.

---

## 7. Per-experiment protocols

### EXP-1, DIY vs Tavily, refreshed (FR)

- **Primary question.** On web-answerable French pairs, does DIY retrieve
  evidence that supports the ODMI gold answer at least as often as Tavily?
- **Primary endpoint.** E2 decided-pair win share with the non-inferiority test
  (section 5). E1 (accuracy) reported on the full finalised set as the
  co-endpoint. The web-answerable result is labelled conditional, never
  system-wide.
- **Sample.** The full FR finalised set (103 distinct pairs; 104 rows, one
  duplicate `pair_run_id`) for E1; the FR web-answerable stratum (Quality
  excluded, 87 pairs) for the E2 head-to-head. Exact counts are re-reported at
  run time. Target 60 to 80 judged pairs, which on EXP-1's both-fail rate should
  leave a decided n of roughly 40 to 60, against the pilot's 18.
- **Reliability.** Gemini re-judges the seeded 30% subsample; Krippendorff's
  alpha reported. Answer-blind variant run on that subsample.
- **Output.** A fresh `evaluation/results/diy_vs_tavily_*.jsonl`, Wilson CIs,
  the sign test and McNemar, position consistency, alpha, the answer-blind delta,
  and per-dimension splits with achieved counts (secondary).

### EXP-2a, search-knob cost vs quality (FR)

- **Primary question.** Do leaner DIY search knobs hold answer accuracy while
  cutting cost per pair?
- **Primary endpoint.** E1 (accuracy held?), with cost the co-headline. No judge
  (same provider across conditions), so no cross-family step.
- **Conditions** (provider, models, strategy and pair set held fixed; only the
  knobs vary):

  | condition_label | num-queries | max-results-per-query |
  |---|---|---|
  | `diy_full` | default (up to 3) | 5 |
  | `diy_lean` | 2 | 3 |
  | `diy_q3r3` | default (up to 3) | 3 |

  `diy_q3r3` isolates which knob carries the cost.
- **Sample.** 12 web-answerable FR pairs (from EXP-1's answerable set; this reuse
  is the declared exception in section 3), identical across all three conditions.
- **Cost metric.** Total Claude calls / tokens / cost **per pair**, not per
  search, plus mean `retry_count` per condition. A leaner search that fails more
  triggers a full Researcher+Verifier retry, so the per-pair total is the only
  honest unit. All three conditions start from a cold cache with caching disabled
  (section 4), so no condition inherits another's free hits.
- **Primary comparison.** McNemar on accuracy `diy_lean` vs `diy_full`; Wilcoxon
  on per-pair cost `diy_lean` vs `diy_full`. `diy_q3r3` vs `diy_full` is the
  secondary knob-isolation comparison.
- **Headline.** Accuracy delta set against the calls-per-pair delta. If a leaner
  condition retried more and erased the saving, that is stated as the result.

### EXP-2b, search-knob cost vs quality (low-resource)

- As EXP-2a, on Estonia (15 finalised pairs already exist, dimension-balanced).
- **Question.** Does the knob trade-off shift when the web is thinner, so that
  lean knobs hurt more where the answer is harder to find?
- Run after EXP-2a.

### EXP-3, DIY vs Tavily, multilingual / low-resource (descriptive)

- **Primary question and pre-registered hypothesis.** Does DIY's parity with
  Tavily degrade as language resource falls? **H1 (directional, pre-registered):**
  DIY's decided not-worse rate is non-increasing across EE, LT, IS as
  first-language speaker population decreases. Lithuania is the **discriminating
  control**: it holds ODMI maturity high while its language resource is lower, so
  underperformance there cannot be put down to a thin national data estate and
  points to a language channel. This is a quasi-experimental identification, not a
  bare description. It stops short of proof: at n=3, maturity and language remain
  partly confounded, so a positive result is reported as evidence **consistent
  with** a causal language effect and a basis for a larger country panel, not as a
  settled cause.
- **Country selection.** Chosen so maturity and language-resource are not
  perfectly collinear, since they are otherwise tangled. Maturity is the
  published ODMI 2024 ranking. The language-resource proxy is **first-language
  speaker population** (an external, objective figure), with the
  Claude-capability tier shown alongside as an investigator note, not as the
  independent variable:

  | Country | ODMI maturity | Language | L1 speakers (approx) | Pairs |
  |---|---|---|---|---|
  | Estonia (EE) | high (frontrunner) | Estonian | ~1.0 m | 15 ready |
  | Lithuania (LT) | 2nd most mature | Lithuanian | ~2.8 m | dispatch ~12-15 |
  | Iceland (IS) | lower | Icelandic | ~0.3 m | dispatch ~12-15 |

  The maturity/language confound is addressed **by design** rather than ignored:
  Lithuania's high maturity is what lets a shortfall there discriminate a language
  channel from data-estate thinness. With n=3 the identification is partial, so
  the confound is still reported as the headline limitation, and the strength of
  any claim is tied to the size of the observed effect: a large, consistent LT/IS
  shortfall against EE supports H1 far more than a marginal one. The framing is
  quasi-experimental and hypothesis-testing, not merely descriptive, but it does
  not assert proven causation at this sample size.
- **Endpoints.** Both. E1 from the finalised pairs vs ground truth (all three
  countries carry full 143-row ODMI coverage, verified). E2 from the adjudicated
  harness, extended to filter by country, single-pass snapshot per pair.
  Krippendorff's alpha and the answer-blind variant on the subsample.
- **Sample.** EE's existing 15, plus a fresh dimension-stratified dispatch of
  ~12-15 pairs each for LT and IS; achieved per-dimension counts reported.

### EXP-4, Brave head-to-head (FR)

- **Primary question.** Where does Brave sit against DIY and Tavily on the same
  pairs? Exploratory (reuses EXP-1's sample; section 5).
- **Sample.** The EXP-1 FR web-answerable set.
- **Design.** Three arms (DIY, Tavily, Brave). The judge runs **pairwise
  round-robin** (DIY vs Tavily, DIY vs Brave, Tavily vs Brave), each pair
  position-swapped, blinded, and rendered with equal passage count and
  registrable-domain URLs (section 4). Provider ranking by Copeland count;
  intransitive triples reported (section 5).
- **Endpoints.** Both. Krippendorff's alpha and answer-blind variant on the
  subsample.

### EXP-5, four-provider A/B (FR)

- **Primary question.** A full paired comparison of the four wired providers:
  Tavily, Brave, DIY, Serper. Four, not five: only four search backends are
  implemented, there is no fifth. Exploratory (reuses EXP-1's sample).
- **Sample.** The EXP-1 FR web-answerable set.
- **Design.** Pairwise round-robin across the four providers (six provider
  pairs), each position-swapped and blinded; Copeland ranking; both endpoints;
  Krippendorff's alpha and answer-blind variant on the subsample. This is the
  parked June plan (see the project memory), now unparked.

The remaining optimisation experiments are EXP-6 (Family 2, Verifier prompt
strategies), pre-registered separately in `EXPERIMENTS_VERIFIER.md`; EXP-7 (retry
chaining / evidence accumulation), parked in `EXPERIMENTS.md`; and EXP-8 and EXP-9
below. METHODOLOGY.md describes the three optimisation families; this section
pins the cost-side (Family 1) and model-variant (Family 3) families to the rules
in section 0, the part the methodology draft left open.

### EXP-8, cost-side optimisations (Family 1)

- **Primary question.** How much of the per-pair cost can be cut before accuracy
  drops below the `baseline`? The output is the cost axis of the accuracy-cost
  surface (METHODOLOGY, RQ5).
- **Arms** (`condition_label`, METHODOLOGY Family 1; pair set, country, and models
  held fixed, only the named knob varies):

  | condition_label | Change from baseline |
  |---|---|
  | `baseline` | Full prompt, full retrieval, no truncation. The reference accuracy and cost. |
  | `prompt-compressed` | Prompts compressed: examples dropped, instructions terser. Same loop. |
  | `retrieval-tight` | Search capped at top-3 hits, fetch capped at the first 4k characters (the D31 knobs). |
  | `cache-hot` | Identical query within the hour returns cached evidence. The cache is the treatment here, so R9's cold-cache rule is suspended for this arm only, and the arm is declared as cache-on. |
  | `model-fallback` | Cheaper model first, escalate to the baseline model only on a Verifier reject. Overlaps EXP-9's `model-tiered`; reported as the cost-knob view of it and cross-referenced. |

- **Endpoints.** E1 accuracy, read **balance-aware** per R4(b) (balanced accuracy
  and the per-class catch / false-positive rates, not raw accuracy), with the
  Malta majority baseline (69%) printed beside it per R4(a). Cost per pair (total
  Claude calls, tokens, cost, and mean `retry_count`) per R9 is the co-headline.
  No judge, so no cross-family step.
- **Sample.** Malta primary, Netherlands secondary, per R4(c). Paired: every
  condition runs the **identical** pair set (R2), stratified by ODMI dimension
  with achieved counts reported (R3). Target ~40 Malta pairs spanning the four
  dimensions, with the `no`-gold pairs deliberately retained so a false `yes`
  shows up.
- **Statistics.** McNemar exact on accuracy for each lean arm against `baseline`,
  Wilcoxon signed-rank on per-pair cost, Holm-corrected across the four
  non-baseline arms (R8). The one confirmatory comparison is the cheapest arm that
  holds accuracy against `baseline`; the rest are secondary.
- **Headline.** Each accuracy delta is set against the calls-per-pair delta. A
  lean arm that retries more and erases its own saving is reported as that result
  (the EXP-2 confound, R9).
- **Prerequisite.** The Malta dispatch is done (2026-06-03, 60/60), so the pairs
  exist. No longer quota-gated (20x plan, DIY-only per D43). `prompt-compressed`
  still needs a committed compressed prompt version and `model-fallback` the
  escalation path; both are pre-run requirements (section 9). EXP-8 is not in the
  current pass (EXP-9 is the running model experiment).

### EXP-9, model variants (Family 3)

- **Primary question.** How much of accuracy is model capability versus pipeline
  design, and does the tiered combination match the all-Sonnet baseline at
  materially lower cost? The output is the accuracy-cost surface across model
  tiers (METHODOLOGY Family 3).
- **Arms** (same models across Researcher / Verifier / Adjudicator unless tiered;
  exact version IDs are pinned at run time and recorded in `claude_usage_log` and
  the registry `conditions`, per the receipts standard, so a later catalogue
  change does not rewrite history):

  | condition_label | Researcher | Verifier | Adjudicator |
  |---|---|---|---|
  | `model-haiku` | Haiku | Haiku | Haiku |
  | `model-sonnet` (baseline) | Sonnet | Sonnet | Sonnet |
  | `model-opus` | Opus | Opus | Opus |
  | `model-tiered` | Haiku | Sonnet | Opus |
  | `model-mistral` | Mistral Large | Mistral Large | Mistral Large |

  The `model-mistral` arm was added 2026-06-09, after the original four-arm
  registration. It is a cross-family control: if a non-Claude model lands near
  the Sonnet baseline, the result is carried by the pipeline design, not by
  Claude specifically. The DIY snippet-picker stays on Claude for every arm, so
  it is a pinned constant. Version IDs at run time: Haiku
  `claude-haiku-4-5-20251001`, Sonnet `claude-sonnet-4-6`, Opus `claude-opus-4-6`
  (the pre-registered Opus, confirmed served by the proxy), Mistral
  `mistral-large-latest`.

- **Endpoints.** E1 accuracy, balance-aware per R4(b) against the Malta majority
  baseline per R4(a); cost per pair per R9. The accuracy-cost surface (accuracy on
  one axis, cumulative cost on the other, one marker per condition, coloured by
  ODMI dimension) is the headline figure for the dissertation.
- **Sample.** Malta primary, Netherlands secondary, per R4(c). Paired across the
  five model conditions on the identical pair set (R2), stratified by dimension
  (R3). Shares the EXP-8 Malta dispatch where the pairs overlap.
- **Statistics.** Per-condition balanced accuracy with Wilson 95% intervals (R8).
  The one confirmatory comparison is `model-tiered` vs `model-sonnet` (the
  deployment hypothesis: cheap drafting, mid-tier verification, premium reasoning
  only when the swarm fails to converge), tested by McNemar exact on accuracy and
  Wilcoxon on per-pair cost. `model-haiku` and `model-opus` against the baseline
  are secondary, Holm-corrected.
- **Honest framing.** "Model tier does not matter much on this regime, Haiku is
  enough" is as publishable a result as "only Opus reaches human-equivalent". A
  null is the finding (R12).
- **Prerequisite (met; running 2026-06-09).** The Malta dispatch is done and the
  per-agent model-override threading is committed and tested (section 9). Not
  quota-gated (20x plan). The five arms dispatch via
  `scripts/run_exp9_model_variants.sh`.

---

## 8. Experiment registry (D27)

Each experiment is inserted into the `experiments` SQLite table before its run,
with `conditions` as a JSON object. IDs:

| experiment_id | EXP | conditions (summary) |
|---|---|---|
| `diy_vs_tavily_fr_v2` | EXP-1 | arms: diy, tavily; FR answerable |
| `knob_cost_quality_fr` | EXP-2a | diy_full, diy_lean, diy_q3r3; FR |
| `knob_cost_quality_ee` | EXP-2b | diy_full, diy_lean, diy_q3r3; EE |
| `diy_vs_tavily_multilingual` | EXP-3 | arms: diy, tavily; EE, LT, IS |
| `brave_head_to_head_fr` | EXP-4 | arms: diy, tavily, brave; FR |
| `provider_ab_fr` | EXP-5 | arms: diy, tavily, brave, serper; FR |
| `verifier_strategy_disc_v1` | EXP-6 | strategies: disprove, negation, steelman, blind; MT primary, FR/INJ robustness |
| `cost_side_optim_mt` | EXP-8 | baseline, prompt-compressed, retrieval-tight, cache-hot, model-fallback; MT, NL |
| `model_variants_mt` | EXP-9 | model-haiku, model-sonnet, model-opus, model-tiered; MT, NL |
| `malta_failure_audit_v1` | EXP-10 | Phase A failure-mode taxonomy + Phase B confidence-floor sweep; MT (see `EXPERIMENTS_MALTA_FAILURES.md`) |

## 9. Pre-run requirements (must be committed and verified before any run)

The first draft pre-registered statistics and controls the harness did not yet
implement. A pre-registration is binding only if the analysis exists in advance,
so these are built, unit-tested, and committed **before** the first run:

1. **Stats module** (`evaluation/stats.py` or similar): Wilson interval, exact
   binomial sign test, McNemar exact, Wilcoxon signed-rank, Krippendorff's alpha.
   Unit-tested against known values.
2. **Deny-list parity:** filter the DIY Serper SERP through `is_blocked` before
   fetching, so every arm drops deny-listed domains pre-retrieval. Regression
   test that a `data.europa.eu` SERP slot is dropped in DIY, not merely scrubbed.
3. **Evidence normalisation:** equal passage count (`min(n_a, n_b)`), equal
   per-passage cap, registrable-domain URLs, in the adjudicator's evidence
   renderer.
4. **Answer-blind judge variant** and a **Gemini judge** wrapper, with the seeded
   30% subsample selector writing seed and IDs to the JSONL.
5. **Single-pass snapshot** of all arms' evidence per pair, frozen to the result
   record before judging.
6. **Cold-cache cost runs:** cache bypass wired into the EXP-2 dispatch path.
7. **Eval-set filtering:** a `--countries` filter and the Quality-dimension
   exclusion (`questions.dimension`) in `build_eval_set`, so EXP-1 can select the
   FR full set and the FR non-Quality stratum, and EXP-3 can select EE/LT/IS.
   Achieved per-dimension counts logged with the result.
8. **Harness cleanup:** remove the superseded `diy_not_worse_decisive`
   (wins+ties)/decided line and its keys from `aggregate()` so the discredited
   metric cannot be quoted from the harness or an old JSONL; fix the
   `stratify_pairs` docstring that still claims the sample spans dimensions
   "evenly".

A pre-run check script asserts deny-list parity and a cold cache, mirroring the
EXP-2a prompt's "did the swarm actually use DIY" sanity check. No experiment runs
until items 1 to 8 are committed and their tests pass.

For the optimisation experiments (EXP-6 retarget, EXP-8, EXP-9), three further
items. Item 9 (the Malta dispatch) is now done and these are no longer
quota-gated (20x plan, DIY-only per D43):

9. **Malta dispatch:** a Researcher run over Malta (target ~30 `no`-gold binary
   questions plus a matched ~30 `yes`-gold for the pass side, dimension-stratified),
   optionally Netherlands. The `no`-gold candidates do not exist in the DB yet, so
   this is the binding prerequisite for the base-rate rule (R4) to be satisfiable.
   Same quota gate as the parked D28 Phase 3.
   **Done (2026-06-03).** The canonical pair set is frozen and committed at
   `data/questions/malta_eval_pairs.json` (60 pairs, 30 `no` / 30 `yes`, seed
   20260603, dimension split Impact 17 / Portal 24 / Policy 10 / Quality 9;
   generator `scripts/build_malta_eval_pairs.py`). All 30 `no`-gold binary
   questions are included as the minority class; the 30 `yes`-gold pairs are a
   size-matched, dimension-stratified round-robin draw. The baseline dispatch
   (provider auto, `condition_label` baseline, no `experiment_id`; batches
   `exp6_malta` then `malta_baseline`) finalised all 60: 43 committed yes/no plus
   17 honest `inconclusive` abstentions (D37). The last two, I8-d and PT12, had
   failed on `search_empty` because their evidence URLs were on Cloudflare-protected
   data.gov.mt; they recovered to `inconclusive` once `head_ok` gained a Playwright
   fallback for WAF 403s. Balance-aware result (R4): exact match
   32/60 raw, 32/43 on committed answers; no-gold minority recall (TNR) 0.87 with 3
   false positives of 23 committed (I7, I8-b, PT29, the visible-error class Malta's
   `no`-gold questions exist to surface); yes-gold recall (TPR) 0.60; Youden's J
   0.47; mean commit confidence 0.58. Zero data-leakage in any finalised row; batch
   cost ~$4.98. The R4 base-rate metric is now satisfiable. EXP-7/8/9 reuse this
   same committed pair list with their own `condition_label` / `experiment_id`
   tags; the 13 baseline rows are plain (no `experiment_id`) and read identically
   to the `exp6_malta` set.

   Three faults found and fixed during the dispatch, none of them quota: a fresh
   worktree has no `.env`, and the desktop app injects an empty
   `ANTHROPIC_AUTH_TOKEN` that made the Anthropic SDK send a malformed `Bearer`
   header, surfacing as `APIConnectionError` (fixed in `agents/tools/llm.py`,
   blank token dropped at import); `_find_resumable_researcher` resumed from
   failed / `inconclusive` Researcher rows, stranding 11 pairs at stage
   'researching' with no `phase2_final` (fixed in `scripts/run_coordinator.py`, only
   clean committed results are now resumable); and `head_ok` reported
   Cloudflare-protected data.gov.mt as `url_unreachable`, killing answers grounded
   there, now cleared with a Playwright render on a WAF 403/429/503 (fixed in
   `agents/tools/fetch.py`). The not-done set is computed dynamically as the
   canonical question IDs minus the distinct MT `phase2_researcher_runs` question
   IDs, so any later re-run resumes cleanly.
10. **EXP-8 conditions:** a committed `prompt-compressed` prompt version in
    `prompt_versions`, the `model-fallback` escalation path, and a per-arm
    cache-bypass that leaves the `cache-hot` arm cache-on while every other arm
    runs cold.
    **Done (2026-06-03).** `prompt-compressed` is a distinct Researcher prompt
    (`agents/prompts/researcher.py`, NAME `phase2_researcher_compressed`,
    examples dropped and instructions condensed, the forbidden-source rule kept),
    selected by `--prompt-variant compressed`; the baseline `full` prompt is
    untouched. `model-fallback` is the `--researcher-escalation-model` /
    `--verifier-escalation-model` pair: attempt 0 runs the base model, a retry
    after a Verifier reject escalates (`_model_for_attempt`). The cache switch is
    the existing `--no-cache`: lean arms pass it (cold), `cache-hot` omits it
    (reads on). Tested in `tests/test_prompt_compressed.py` and
    `tests/test_model_threading.py`; `--no-cache` was already covered by
    `tests/test_dispatch_no_cache.py`.
11. **EXP-9 threading:** per-agent model overrides (Researcher / Verifier /
    Adjudicator independently settable) threaded through the dispatch path and the
    `model-tiered` assignment, with the resolved version IDs written to
    `claude_usage_log`.
    **Done (2026-06-03).** Before this, only the Adjudicator threaded its model;
    `run_researcher` / `run_verifier` recorded `researcher_model` /
    `verifier_model` in `subtrio_status` but never drove the LLM with them, so a
    tiered run would have silently used Sonnet for retrieval and verification.
    The model is now threaded through both agents (query-gen and main call) and
    `call_for_structured`; the wrapper logs `response.model` (the served version
    ID, not the requested alias) to `claude_usage_log`, so a `model-tiered` run's
    receipts are honest. `--researcher-model` / `--verifier-model` /
    `--adjudicator-model` cover all four EXP-9 arms. Tested in
    `tests/test_model_threading.py`.

## 10. Execution and the parallelism constraint

Every swarm dispatch (EXP-2, EXP-3) and every judge call (EXP-1, 3, 4, 5) draws
on the **same** Claude rate limit; the cross-family calls draw on one Gemini key.
Parallel agents therefore help orchestration, not raw throughput: firing six at
once would just contend on one quota. The plan is one orchestrating agent per
experiment, conditions that share quota run in sequence within an experiment, and
only the genuinely independent analysis runs concurrently. This is stated so the
"parallel" framing is not mistaken for a speed claim.

Order of execution: the section 9 requirements first; then EXP-1 (refresh, which
also re-validates the harness changes) and EXP-2a; EXP-2b and EXP-3's LT/IS
dispatch next; EXP-4 and EXP-5 last, as they reuse EXP-1's pair set and harness.

## 11. Threats to validity (carried into the writeup)

- Small n on the decided subsets; reported with Wilson intervals, never as bare
  percentages.
- Judge is an LLM. Mitigated by blinding, position-swap, equal passage count,
  registrable-domain URLs, the answer-blind variant, and the Gemini cross-family
  alpha, but not eliminated.
- **Residual host tell:** the registrable domain is still visible to the judge
  and could cue a provider; not fully controllable without discarding the
  authority signal the judge needs.
- **Answer-label leakage:** the answer-given judge can reward keyword presence;
  mitigated by the answer-blind variant, against which E1/E2 agreement is
  measured.
- ODMI ground truth can be one cycle old, so a swarm-vs-ODMI disagreement is not
  automatically a swarm error (D22).
- **EXP-3 confounds maturity with language** at n=3 countries. EXP-3 tests a
  pre-registered directional hypothesis (H1) using Lithuania as a discriminating
  control, with speaker population as the objective resource proxy; the
  identification is partial, so a positive result is reported as consistent with a
  language effect, not as settled causation. This confound is the headline EXP-3
  limitation.
- **EXP-2a reuses EXP-1's answerable set**, which conditions on an earlier
  outcome.
- **Shared-sample dependency:** EXP-1, 4, 5 reuse one FR pair set; only EXP-1 is
  confirmatory, EXP-4/5 are exploratory, so the primaries are not treated as
  independent replications.

## 12. Rubric audit: existing experiments against section 0

Every experiment graded against the rules, with the focus on R4 (the new
base-rate rule). The point is to find where already-pre-registered work breaks a
rule, so the breach is named and fixed rather than buried.

| EXP | R4 base-rate | Other notable | Verdict |
|---|---|---|---|
| EXP-1 (done, FR) | **Breach on the E1 accuracy co-endpoint** (FR binary 99% one class); E2 provider win-share is base-rate-robust | R6 reliability **done** 2026-06-03 via Mistral Large (Gemini dead, Groq per-org cap spent): 78% agreement, alpha 0.648, disagreements all Opus `both_fail` vs a commitment | Headline (E2, DIY 89% of 55 decided) **stands**; cross-family reliability now satisfies R6; the E1 accuracy figure must carry the 99% baseline and not be read as a swarm-accuracy claim |
| EXP-2a (queued, FR) | Breach: reuses FR answerable set for an accuracy-held claim | Cost endpoint is base-rate-independent | Move the accuracy claim to Malta; keep FR only for the cost mechanics |
| EXP-2b (planned, EE) | Breach: Estonia is degenerate (98%) and low-resource | Conflates "thin web" with "low resource" | Re-anchor to Malta for the trade-off; use a balanced low-resource country (IS) only as the declared language-confound contrast |
| EXP-3 (planned, EE/LT/IS) | **Breach: LT has zero negative binary golds**, so the "discriminating control" cannot discriminate a false positive on binary; EE degenerate | E2 win-share is base-rate-robust; the maturity x language claim (R7) leans on the broken binary accuracy | Restrict E1 to non-binary shapes where the gold varies, or re-anchor; keep E2 as the provider comparison |
| EXP-4, EXP-5 (planned, FR) | Satisfied: endpoints are paired provider win-shares, not accuracy vs a skewed gold | Shared-sample dependency disclosed (R8) | FR acceptable for these endpoints; no change |
| EXP-6 (running, retargeted) | Was a breach (should_fail 20/21 FR); the Malta retarget fixes R4(c) | R4(b) already met (J/MCC headline) | Compliant after retarget; pending Malta dispatch |
| EXP-7 (parked) | Satisfied by design (Malta, no-gold-rich) | - | Compliant; parked |
| EXP-8, EXP-9 (new) | Satisfied by design (Malta primary, NL secondary) | - | Compliant; pending Malta dispatch |

Two findings carry weight for the writeup.

- **EXP-1's provider result survives, its accuracy framing does not.** The
  confirmatory endpoint is a within-pair preference between two evidence blocks,
  which a skewed gold does not flatter, so "DIY wins 89% of 55 decided pairs"
  holds. But any France E1 *accuracy* number sits on a 99% majority baseline and
  cannot be presented as evidence the swarm answers well. R4(a) (print the
  baseline) is the missing step, not a re-run.
- **EXP-3's identification strategy is undercut by its own anchors.** Lithuania
  was chosen as the high-maturity control whose underperformance would point to a
  language channel, but on binary questions Lithuania has no negative golds at
  all, so a false positive cannot even occur there. The maturity x language claim
  (R7) therefore cannot rest on binary accuracy. Either move EXP-3's E1 to the
  percentage-band and ordinal shapes, where the gold actually varies, or re-anchor
  the country panel. This is the clearest case of the base-rate rule changing an
  already-pre-registered design.

## Change log

- 2026-06-02: created. Pre-registers EXP-1 refresh, EXP-2a/2b, EXP-3 (EE/LT/IS),
  EXP-4, EXP-5 (four providers). No runs yet.
- 2026-06-02: amended after adversarial methodology review. Fixed the
  non-inferiority metric (ties no longer count as DIY successes; test on decided
  pairs with a justified 0.10 margin); E1 now primary on the full finalised set
  with both-fails shown, web-answerable demoted to a labelled conditional; added
  the deny-list parity fix (DIY SERP filtered pre-fetch), equal-passage-count and
  registrable-domain normalisation, single-pass evidence snapshot, cold-cache
  cost runs, answer-blind judge variant, seeded 30% reliability subsample;
  switched reliability stat to Krippendorff's alpha; added Copeland ranking with
  intransitivity reporting for EXP-4/5; anchored the EXP-3 language proxy to
  speaker population and downgraded EXP-3 to descriptive; added section 9
  (pre-run requirements) so the analysis code exists before the runs.
- 2026-06-02: second review pass. Corrected the false present-tense claim that
  the analysis code was already committed (it is not; the document is written
  before the apparatus and now says so in the future tense); tagged every
  not-yet-built control in section 4 as (pre-run); made the web-answerable rule a
  single objective column filter (exclude Quality, 87 of 103 FR pairs) rather
  than an undefined self-report judgement; corrected the FR count to 103 distinct
  pairs; added eval-set country/Quality filtering and harness cleanup (drop the
  discredited diy_not_worse_decisive line, fix the stratify_pairs docstring) to
  section 9.
- 2026-06-02: EXP-3 strengthened at Benjy's instruction from descriptive to a
  quasi-experimental, pre-registered directional hypothesis (H1) with Lithuania
  as a discriminating control. Kept the speaker-population proxy and the
  partial-identification caveat (no proven causation at n=3); the maturity/language
  confound remains the headline EXP-3 limitation.
- 2026-06-03: added section 0 (the universal rules R1 to R12 that bind every
  experiment), with R4 the new base-rate rule that bars a degenerate evaluation
  set and pins country selection to minority-class share subject to a
  well-resourced-language constraint (Malta primary, NL secondary; the No-share
  table is computed from `ground_truth`). Pre-registered EXP-8 (Family 1
  cost-side) and EXP-9 (Family 3 model variants) under those rules; added their
  registry rows and the Malta-dispatch / condition-threading pre-run requirements
  (items 9 to 11), all gated on search quota. Added section 12, the rubric audit:
  it flags EXP-1's France E1 accuracy as base-rate degenerate (the E2 provider
  result is unaffected) and EXP-3's Lithuania control as undiscriminating on
  binary (zero negative golds). No runs in this commit.
- 2026-06-03: built the EXP-8 / EXP-9 apparatus (section 9 items 10 and 11),
  pure code with no quota use, ahead of the Malta dispatch. EXP-9: the per-agent
  model override is now threaded through `run_researcher` and `run_verifier`
  (previously only the Adjudicator obeyed its model), and the served version ID
  is logged to `claude_usage_log`. EXP-8: a `prompt-compressed` Researcher prompt
  (its own `prompt_versions` row, baseline untouched) and a `model-fallback`
  escalation (`--researcher-escalation-model` / `--verifier-escalation-model`,
  cheap on attempt 0, escalate on a Verifier-reject retry). The `--no-cache`
  cold-cache switch already covered the `cache-hot`-vs-lean split, and the
  answer-blind judge variant already exists (`adjudicate(answer_blind=True)`,
  `run_answer_blind_subsample`). New tests: `tests/test_model_threading.py`,
  `tests/test_prompt_compressed.py`. Both EXP-8 and EXP-9 are now runnable the
  moment the Malta pairs land; the dispatch (item 9, search-quota-gated) is the
  only remaining blocker. No runs in this commit.
- 2026-06-03: EXP-1 cross-family reliability (R6, section 4) run and closed. The
  pre-registered Gemini judge stayed dead (zero quota); the Groq / Llama-3.3-70B
  substitute is blocked because Groq caps tokens per organisation, not per key,
  so one spent daily pool 429s every key in the org. The judge of record for the
  reliability arm is therefore **Mistral Large**, a third independent family on a
  separate quota. It re-judged the frozen, seeded 27-pair subsample answer-given
  and position-swapped on byte-identical evidence (only the judge changed):
  raw agreement 78%, Krippendorff alpha 0.648 (nominal, four categories), all six
  disagreements Opus `both_fail` vs a Mistral commitment, none provider-vs-provider.
  Harness `evaluation/cross_family_backfill.py --judge mistral`, result
  `evaluation/results/cross_family_exp1_mistral.jsonl`. This is a judge
  substitution, not a change to the sample, endpoints, or statistics (R1 holds).
