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
