# Experiments Protocol (pre-registration)

Pre-registered 2026-06-02. This document fixes the design of the search
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
  (`dashboard/lib/db.py`). Objective, reproducible, no judge. Available wherever
  a finalised pair exists.
- **E2, adjudicated evidence quality.** A blind, position-swapped LLM judge
  compares two arms' retrieved evidence against the ODMI gold answer and returns
  one of `{arm_a, arm_b, tie, both_fail}`. Captures retrieval quality even when
  the answer both-fails (the open web cannot reach it). Harness:
  `evaluation/diy_vs_tavily.py` and its successors.
- **Agreement.** Whether the arm that wins on evidence quality (E2) also wins on
  final accuracy (E1) is reported as a finding, not assumed.

## 3. Sampling

- **Paired throughout.** Every arm sees the identical pair set and, for provider
  comparisons, the identical query string (the Researcher's first stored query
  for that pair). Differences are then attributable to the arm, not to a
  different question or a different query.
- **Stratified by ODMI dimension.** Samples are drawn round-robin across
  Policy / Portal / Quality / Impact (the existing `stratify_pairs`), so no one
  dimension dominates. The selection rule is fixed here, before the run. No
  hand-picking of individual pairs.
- **Web-answerable stratum.** Many Quality questions both-fail because the gold
  answer sits on the deny-listed `data.europa.eu` (the MQA) or is a national
  self-report. Those pairs carry no signal about relative retrieval quality.
  Where an experiment restricts to web-answerable pairs, the stratum is defined
  by a rule fixed in advance (exclude the Quality dimension; exclude questions
  whose ODMI answer is a self-report), **not** by conditioning on a prior run's
  verdict. EXP-2a is the one exception: it reuses the answerable FR pairs
  identified by EXP-1, which is conditioning on an earlier outcome. That is
  acceptable for a direct follow-up and is declared as such in EXP-2a.

## 4. Bias controls

| Threat | Control |
|---|---|
| Question difficulty varies pair to pair | Paired, within-pair comparison; same pairs across all arms. |
| Cherry-picking pairs | Pre-specified stratified sampling, rule fixed before the run. |
| Judge position bias | Each pair judged twice with arm positions swapped; a pure flip nets to a tie and is flagged inconsistent. Position-consistency rate reported. |
| Provider fingerprinting (a blind judge guessing the arm from snippet format) | Evidence normalisation before judging: equal maximum snippet length, the provider `score` field stripped, no provider name or URL-host tell left in the rendered block. |
| Same-family self-preference (Opus rating Claude-extracted DIY evidence) | A cross-family judge (Gemini) re-rates a random subsample; Cohen's kappa against the Opus verdicts is reported. |
| Data leakage from the evaluation cycle | The `data.europa.eu` deny-list (`agents/tools/blocked_domains.py`) is applied identically to every arm, including DIY's own extraction. Verified before each run. |
| Run-order / cache reuse inflating a later arm's apparent thrift | SERP and snippet caches (`search_cache_serp`, `search_cache_snippet`) are bypassed or cleared between cost conditions, so no condition inherits another's free hits. |
| Temperature noise | Temperature 0 in the LLM wrapper, unchanged. |

## 5. Statistics

Fixed in advance. One pre-specified **primary comparison** per experiment;
everything else (per-dimension, per-condition splits) is **secondary and
exploratory**, labelled as such, and Holm-corrected within the secondary family
before any claim is drawn from it.

- **Proportions** (E1 match rate, E2 not-worse rate): point estimate with a
  **Wilson score 95% confidence interval**. The interval, not just the point, is
  the result. Wilson is used because it behaves at small n where the normal
  approximation does not.
- **Paired binary outcome between two arms** (match vs not-match on the same
  pairs): **McNemar's exact test** (binomial on the discordant pairs). Discordant
  cell counts are reported.
- **Cost per pair** (paired, skewed, small n): **Wilcoxon signed-rank** on the
  per-pair total cost; median delta and IQR reported.
- **Non-inferiority (EXP-1, EXP-3, EXP-4):** DIY is declared non-inferior to the
  comparator on a dimension if the **lower bound** of the Wilson 95% interval on
  the decisive not-worse rate exceeds **0.40** (a pre-set margin of 0.10 below
  parity). "Not worse" is a one-sided claim; we never read a point estimate above
  0.50 as a win without the interval clearing the margin.
- **Judge reliability:** Cohen's kappa (Opus vs Gemini) on the subsample, plus
  raw agreement. Position consistency = fraction of pairs whose two swapped
  orientations agreed.
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
- **Primary endpoint.** E2 (this is a retrieval-quality question). E1 secondary,
  on the subset with a finalised answer.
- **Sample.** The full FR web-answerable stratum: the 104 finalised FR pairs,
  Quality dimension excluded (deny-list both-fail), self-report questions
  excluded. Target 60 to 80 judged pairs, which on EXP-1's both-fail rate should
  leave a decisive n of roughly 40 to 60, against the pilot's 18.
- **Primary comparison.** DIY decisive not-worse rate vs the 0.40 non-inferiority
  margin (section 5).
- **Reliability.** Gemini re-judges a 30% random subsample; kappa reported.
- **Output.** A fresh `evaluation/results/diy_vs_tavily_*.jsonl`, Wilson CIs,
  McNemar against parity, position consistency, kappa, and a per-dimension split
  (secondary).

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
  honest unit. SERP/snippet cache bypassed between conditions.
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

### EXP-3, DIY vs Tavily, multilingual / low-resource

- **Primary question.** Does DIY's FR parity with Tavily hold in lower-resource
  languages, and is any gap attributable to language rather than to data
  maturity?
- **Country selection.** Chosen to partly decouple maturity from language, which
  are otherwise tangled. Maturity is the published ODMI 2024 ranking; the
  language tier is an **investigator-assigned ordinal of Claude's capability in
  that language** (1 = strongest, 4 = weakest), not an external standard.

  | Country | ODMI maturity | Language | Language tier (investigator) | Pairs |
  |---|---|---|---|---|
  | Estonia (EE) | high (frontrunner) | Estonian | 3 | 15 ready |
  | Lithuania (LT) | 2nd most mature | Lithuanian | 3 | dispatch ~12-15 |
  | Iceland (IS) | lower | Icelandic | 4 (weakest) | dispatch ~12-15 |

  Lithuania is the decoupling case: high maturity but a tier-3 language, so a DIY
  shortfall there points to language rather than to a thin national data estate.
  Estonia holds maturity high at the same tier; Iceland drops both maturity and
  tier. Three countries cannot make a clean 2x2 factorial, so this is reported as
  an **observational, quasi-experimental** comparison, and the confound between
  maturity and language is named as a limitation rather than claimed away.
- **Endpoints.** Both. E1 from the finalised pairs vs ground truth (all three
  countries carry full 143-row ODMI coverage, verified). E2 from the adjudicated
  harness, extended to filter by country. Gemini kappa on a subsample.
- **Sample.** EE's existing 15, plus a fresh dimension-stratified dispatch of
  ~12-15 pairs each for LT and IS.
- **Primary comparison.** DIY decisive not-worse rate per country vs the 0.40
  margin; cross-country contrast (LT vs EE isolating language at fixed maturity)
  is the secondary, exploratory reading.

### EXP-4, Brave head-to-head (FR)

- **Primary question.** Where does Brave sit against DIY and Tavily on the same
  pairs?
- **Sample.** The EXP-1 FR web-answerable set.
- **Design.** Three arms (DIY, Tavily, Brave). A single three-way blind ranking
  is harder to keep unbiased, so the judge runs **pairwise round-robin**
  (DIY vs Tavily, DIY vs Brave, Tavily vs Brave), each pair position-swapped and
  blinded as in EXP-1. Provider win counts are assembled from the pairwise
  verdicts.
- **Endpoints.** Both. Gemini kappa on a subsample.

### EXP-5, four-provider A/B (FR)

- **Primary question.** A full paired comparison of the four wired providers:
  Tavily, Brave, DIY, Serper. (Four, not five. Only four search backends are
  implemented; there is no fifth.)
- **Sample.** The EXP-1 FR web-answerable set.
- **Design.** Pairwise round-robin across the four providers (six provider
  pairs), each position-swapped and blinded; both endpoints; Gemini kappa on a
  subsample. This is the parked June plan (see the project memory), now unparked.

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

## 9. Execution and the parallelism constraint

Every swarm dispatch (EXP-2, EXP-3) and every judge call (EXP-1, 3, 4, 5) draws
on the **same** Claude rate limit; the cross-family calls draw on one Gemini key.
Parallel agents therefore help orchestration, not raw throughput: firing six at
once would just contend on one quota. The plan is one orchestrating agent per
experiment, conditions that share quota run in sequence within an experiment, and
only the genuinely independent analysis runs concurrently. This is stated so the
"parallel" framing is not mistaken for a speed claim.

Order of execution: EXP-1 (refresh, also re-validates the harness changes) and
EXP-2a first; EXP-2b and EXP-3's LT/IS dispatch next; EXP-4 and EXP-5 last, as
they reuse EXP-1's pair set and harness.

## 10. Threats to validity (carried into the writeup)

- Small n on the decisive subsets; reported with Wilson intervals, never as bare
  percentages.
- Judge is an LLM. Mitigated by blinding, position-swap, evidence normalisation,
  and the Gemini cross-family kappa, but not eliminated. Stated as a limitation.
- ODMI ground truth can be one cycle old, so a swarm-vs-ODMI disagreement is not
  automatically a swarm error (D22).
- EXP-3 confounds maturity with language; named, not claimed away.
- EXP-2a reuses EXP-1's answerable set, which conditions on an earlier outcome.

## Change log

- 2026-06-02: created. Pre-registers EXP-1 refresh, EXP-2a/2b, EXP-3 (EE/LT/IS),
  EXP-4, EXP-5 (four providers). No runs yet.
