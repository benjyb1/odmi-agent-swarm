# Experiments

The status board for swarm experiments: what is planned, queued, running, and
done, with results once they land. Decisions and rationale live in `SPEC.md`;
the machine registry is the `experiments` SQLite table (D27). This file is the
human-readable view, updated whenever an experiment changes state.

**Status values:** `planned` (designed, not scheduled) · `queued` (next to
run) · `running` · `done`.

| ID | Experiment | Status | Scope | Result (short) |
|---|---|---|---|---|
| EXP-1 | DIY vs Tavily, adjudicated (refreshed) | done | FR, 90 pairs | DIY wins 89% of 55 decided pairs (49/6/1), Wilson CI [78,95], p<1e-4; 42/45 = 93% [82,98] under strict both-orientation exclusion; leads all 3 dimensions |
| EXP-2a | Search-knob cost vs quality | queued | FR subset | pending |
| EXP-2b | Search-knob cost vs quality | planned | low-resource countries | pending |
| EXP-3 | DIY vs Tavily, multilingual | planned | RO / EE / HU and other thin-web countries | pending |
| EXP-4 | Brave head-to-head | planned | FR first | pending |
| EXP-5 | Five-provider search A/B | planned | TBD (the parked June plan) | pending |
| EXP-6 | Verifier strategy discrimination (4-arm signal detection) | dropped (this round, 2026-06-09) | primary Malta natural errors, NL secondary, FR + injected robustness | parked by decision; the four-arm verifier-strategy comparison is not a priority for the current pass. Apparatus and the partial run stay in the repo so it can be revived. Not run. |
| EXP-7 | Retry chaining: accumulate evidence across the loop | done (2026-06-11) | Malta primary, 40 pairs/arm | chained beats baseline directionally: balanced accuracy 0.217 vs 0.167, recoveries 9 vs 6, false-positive rate 0.18 vs 0.25 (not raised, the co-primary), abstention 0.725 vs 0.80. Recovery McNemar p=0.375 (not significant; underpowered by Malta's 72-80% abstention ceiling). Per-pair call median delta 0 (Wilcoxon p=0.83). Pre-registered joint non-inferiority claim passes. Verdict: promising, not proven; adopt as the optimisation baseline. Result: `evaluation/results/chaining_retry_chaining_mt_v1.json`. |
| EXP-8 | Cost-side optimisations (Family 1) | planned | baseline + prompt-compressed / retrieval-tight / cache-hot / model-fallback; MT primary, NL secondary | unblocked; Malta baseline done (60/60), condition-tagged runs over the same pair list are runnable |
| EXP-9 | Model variants (Family 3) | running (2026-06-09) | Haiku / Sonnet / Opus / tiered / Mistral; MT primary, NL secondary | dispatching all five arms over the Malta 60 via `scripts/run_exp9_model_variants.sh`, knobs pinned (provider diy, cold cache, disprove, 5 results, 3 retries, full prompt, unchained), only the model varies. Mistral-large-latest added as a cross-family arm. Caveat: overlaps the Norway dev sweep, so the latency endpoint may be contention-inflated; token-cost and accuracy unaffected. |
| EXP-10 | Malta failure-mode audit + confidence-floor recovery | planned | MT finalised pairs vs ground truth; Phase A taxonomy, Phase B floor sweep | unblocked; 60 finalised Malta pairs available (batches exp6_malta + malta_baseline), failure taxonomy drafted (search-empty, resume-orphan, abstention, conservative-FN, FP); floor sweep is free |

---

## EXP-1: DIY vs Tavily, adjudicated (done)

**Refreshed 2026-06-02 (diy_vs_tavily_fr_v2), per the pre-registered protocol
(`EXPERIMENTS_PROTOCOL.md`).** Harness: `evaluation/diy_vs_tavily.py`. Results:
`evaluation/results/diy_vs_tavily_20260602_175403.jsonl` (git 533284b). The full
FR non-Quality web-answerable stratum, 90 pairs, judged blind and
position-swapped by Opus, with the deny-list applied pre-fetch to every arm and
evidence normalised to equal passage count and registrable-domain URLs.

Result: DIY 49 wins, 1 tie, 6 Tavily wins, 34 both_fail. On the 55 decided pairs
the DIY win share is 89% (Wilson 95% CI [78%, 95%]), exact sign test p < 1e-4
against parity. DIY leads every dimension (Impact 13/2, Policy 12/2, Portal
24/2). This supersedes the n=18 pilot below and clears the pre-registered
non-inferiority margin decisively.

"Decided" here means the combined two-orientation verdict is diy or tavily (a
non-zero DIY-signed score over the two position-swapped judgements). A
single-orientation `both_fail` scores zero and so is overridden when the other
orientation is decisive; it is not excluded. This affects 10 of the 55 decided
pairs. As a pre-registered sensitivity check, requiring both orientations to be
decisive (dropping those 10) gives 42/45 = 93% (Wilson [82%, 98%]): the
direction and significance are unchanged, so the disclosure is for
completeness, not because the result is fragile.

Caveats (honest): position consistency 81%; the answer-blind robustness check
agrees with the answer-given verdict on only 67% of the 27-pair subsample (9
flips), so the judge is somewhat sensitive to seeing the gold answer. France
only, Tavily basic tier.

Cross-family reliability (done 2026-06-03). The planned Gemini re-judge stayed
dead (zero quota), and Groq's free tier caps tokens per organisation not per
key, so all available Groq keys shared one exhausted daily pool. Mistral Large,
a third independent family, re-judged the same frozen 27-pair subsample
(answer-given, position-swapped, byte-identical evidence; only the judge
changed). Harness: `evaluation/cross_family_backfill.py --judge mistral`;
result: `evaluation/results/cross_family_exp1_mistral.jsonl`. All 27 pairs
judged: raw agreement 78% (21/27), Krippendorff alpha 0.648 (nominal, four
categories). All six disagreements turn on Opus calling `both_fail` (five of
six) where Mistral committed to a provider or a tie; where both judges committed
to a provider they never disagreed (DIY 13, Tavily 3). This rebuts the
same-family self-preference concern, that the Claude judge favours
Claude-extracted DIY evidence. Mistral was position-inconsistent on 6 of 27
pairs, more than Opus, which is reported alongside.

---

Pilot (superseded, n=18 decisive), SPEC D29. Run:
`evaluation/results/diy_vs_tavily_20260601_220315.jsonl`. A blind,
position-swapped Opus judge on 36 dimension-stratified French pairs: DIY 12 wins,
2 ties, 4 losses, 18 both_fail; not worse 78% on the 18 decisive, wins 3:1.
Caveats then: n=18, France only, Tavily basic tier, position consistency 67%.

## EXP-2: Search-knob cost vs quality

SPEC: D31. DIY costs five to eight times the Claude calls of Tavily per pair,
because it runs extraction on our own model (up to five snippet-picks per
search). This tests whether cutting the knobs keeps the quality.

Conditions (hold provider=diy, models, strategy, and the pair set fixed; vary
only the knobs):

| condition_label | queries | results/query |
|---|---|---|
| `diy_full` | 3 | 5 |
| `diy_lean` | 2 | 3 |
| `diy_q3r3` | 3 | 3 |

`diy_q3r3` isolates which knob carries the cost. Metrics per condition:
accuracy against ODMI ground truth (`_MATCH_STATUS_SQL`), and Claude calls /
tokens / cost / mean retry count per pair from `claude_usage_log`.

The confound to watch is retries. A leaner search that fails more often
triggers another full Researcher+Verifier round, so a cheaper per-search
config can cost more per pair. Judge on total calls per pair, not per search.

**EXP-2a (FR subset) — queued.** Run now on a web-answerable French subset.
The agent prompt for this run is in `docs/prompts/run_knob_experiment_fr.md`.

**EXP-2b (low-resource countries) — planned.** Repeat on less well-resourced
countries (see EXP-3 candidates) once the FR result is in. The interesting
question is whether the knob trade-off shifts when web sources are thinner: lean
knobs may hurt more where the answer is hard to find.

Result: pending.

## EXP-3: DIY vs Tavily, multilingual / low-resource (planned)

EXP-1 was France only. France is data-rich and the sources are mostly French
and English. The harder test is countries with thinner open-data webs and
lower-resource languages: Romania, Estonia, Hungary, and similar. This repeats
the adjudicated comparison there.

Blocker: the DB has very few finalised pairs outside France (DE 3, NL 3, RO 2),
so this needs a fresh dispatch for the target countries first. Plan the pairs,
dispatch them, then run the EXP-1 harness on the new set.

Result: pending.

## EXP-4: Brave head-to-head (planned)

Brave is the credit-exhaustion fallback but has never been in an adjudicated
comparison. Add Brave as a third arm so the paradigm is fully characterised
(DIY vs Tavily vs Brave on the same pairs, same judge).

Result: pending.

## EXP-5: Five-provider search A/B (planned)

The parked plan: a paired A/B across five providers, agreed as the June
starting point. Scope and provider list to be confirmed before running.

Result: pending.

## EXP-6: Verifier strategy discrimination (retargeted to Malta)

Pre-registered in `docs/EXPERIMENTS_VERIFIER.md`. Treats each of the four D15
verifier strategies (disprove / negation / steelman / blind) as a binary
classifier over a Researcher candidate answer (pass = accept, fail = reject) and
measures how well each tells a wrong answer from a correct one, per unit of token
cost. Paired design on frozen evidence, so the only between-arm variable is the
system prompt. Primary endpoint Youden's J; secondary MCC, balanced accuracy, the
two error rates with Wilson CIs, per-dimension splits, paired McNemar (Holm), and
a Wilcoxon token-cost comparison.

**Retargeted 2026-06-03 under the new base-rate rule (R4,
`EXPERIMENTS_PROTOCOL.md` section 0).** The first design built its should_fail
class almost entirely from France (20 of 21 natural errors), where the binary gold
is 99% `yes` and a false positive can barely occur. The primary should_fail source
is now Malta (English official, ~30 `no`-gold binary questions), with Netherlands
secondary and the France-dominated natural errors plus the injected label-flips
kept as a robustness arm, reported separately. The earlier partial run on the
France/injected set (committed at 3 of 89, extended to ~40 of 89 in working state)
is superseded as the primary and retained only as robustness data.

Harness: `evaluation/verifier_strategies.py` (resumable; sleeps through Anthropic
rate-limit cooldowns). The strata are now role-based (primary MT, secondary NL,
robustness FR/EE + injection). The primary Youden's J needs the Malta dispatch,
which is now done.

Malta dispatch (done 2026-06-03): the canonical pair set is frozen and committed at
`data/questions/malta_eval_pairs.json` (60 pairs, 30 `no` / 30 `yes`, seed
20260603). The baseline dispatch (provider auto, `condition_label` baseline, no
`experiment_id`, batches `exp6_malta` then `malta_baseline`) finalised all 60:
43 committed yes/no plus 17 honest `inconclusive` abstentions (D37). The last two,
I8-d and PT12, had failed on `search_empty` because their evidence URLs were on
Cloudflare-protected data.gov.mt; they recovered to `inconclusive` once `head_ok`
gained a Playwright fallback for WAF 403s. Balance-aware quality (R4): exact match 32/60 raw, 32/43 on
committed answers; no-gold minority recall (TNR) 0.87 with 3 false positives of 23
committed (I7, I8-b, PT29); yes-gold recall (TPR) 0.60; Youden's J 0.47; mean
commit confidence 0.58. Zero data-leakage in any finalised row. Batch cost ~$4.98.
The natural-error pool for the should_fail arm is now populated.

Three faults surfaced and fixed during the dispatch, none of them quota: a missing
worktree `.env` plus an empty `ANTHROPIC_AUTH_TOKEN` injected by the desktop app
made every LLM call fail with a misleading `APIConnectionError` (fixed in
`agents/tools/llm.py`); the resume path reused failed/`inconclusive` Researcher
rows, stranding 11 pairs at stage 'researching' with no `phase2_final` (fixed in
`scripts/run_coordinator.py` `_find_resumable_researcher`); and `head_ok` marked
Cloudflare-protected data.gov.mt as `url_unreachable`, killing answers grounded
there, which it now clears with a Playwright render on a WAF 403/429/503 (fixed in
`agents/tools/fetch.py`), recovering the final two pairs.

Result: pending (apparatus and Malta natural-error set both ready; the four-arm
judge run has not been executed).

## EXP-8: Cost-side optimisations, Family 1 (planned)

Pre-registered in `EXPERIMENTS_PROTOCOL.md` (section 7). Holds the country, pair
set, and models fixed and varies one cost knob at a time: `baseline`,
`prompt-compressed`, `retrieval-tight`, `cache-hot`, `model-fallback`. Endpoints:
balance-aware accuracy against the Malta majority baseline (R4) and cost per pair
with retries counted (R9). Run on Malta primary, Netherlands secondary.

Prerequisite: the Malta dispatch is done (not quota-gated; 20x plan), so what
remains is a committed `prompt-compressed` prompt version and the
`model-fallback` escalation path. EXP-8 is not in the current pass (EXP-9 is the
running model experiment). The apparatus is built (2026-06-03): the compressed Researcher prompt
(`--prompt-variant compressed`, its own `prompt_versions` row, baseline
untouched), the `model-fallback` escalation (`--researcher-escalation-model` /
`--verifier-escalation-model`), and the cold-cache switch (`--no-cache`) for the
lean-vs-`cache-hot` split. The Malta baseline dispatch is now done (60/60 over the
committed pair list), so the condition-tagged runs can proceed over the same set.

Result: pending.

## EXP-9: Model variants, Family 3 (running)

Pre-registered in `EXPERIMENTS_PROTOCOL.md` (section 7). Compares `model-haiku`,
`model-sonnet` (baseline), `model-opus`, `model-tiered` (Haiku draft, Sonnet
verify, Opus adjudicate), and `model-mistral` on the same Malta pairs. The
confirmatory comparison is tiered vs all-Sonnet on accuracy and cost; the
accuracy-cost surface is the headline figure. Run on Malta primary, Netherlands
secondary.

**Mistral arm (added 2026-06-09).** A fifth, cross-family arm runs the whole
swarm on `mistral-large-latest`. It tests how much of the accuracy is the
pipeline versus Claude specifically: if Mistral lands near Sonnet, the design
carries the result, not the model family. Enabled by a lean provider branch in
`call_for_structured` (structured output is prompt-based JSON, so no separate
agent stack was needed). The DIY snippet-picker stays on Claude for every arm,
so it is a pinned constant, not part of the variant. Mistral is off the Claude
budget; its cost is a real-money figure. Watch for a Mistral monthly-quota stop
on this arm (it runs last, so the four Claude arms complete regardless).

**Model ids.** Haiku `claude-haiku-4-5-20251001`, Sonnet `claude-sonnet-4-6`,
Opus `claude-opus-4-6` (confirmed served by the proxy, matches the
pre-registration; `claude-opus-4-8` is not served). Mistral
`mistral-large-latest`.

**Dispatch.** `scripts/run_exp9_model_variants.sh`, the five arms sequentially
over the canonical Malta 60. One variable (the model); provider diy, cold cache,
disprove, 5 results, 3 retries, full prompt, unchained all pinned. Each arm
tagged `experiment_id=model_variants_mt` and a per-arm `condition_label`; the
fresh dispatch writes new rows alongside the baseline (canonical-row dedup keeps
the analysis honest).

**Caveat (contention).** This run overlaps the Norway development sweep, so the
wall-clock latency endpoint may be inflated by machine contention. The headline
token-cost endpoint is token-based and unaffected; arms run sequentially under
roughly constant background load, so the relative accuracy comparison holds.

Result: pending (running 2026-06-09).

## EXP-10: Malta failure-mode audit + confidence-floor recovery (planned)

Pre-registered in `docs/EXPERIMENTS_MALTA_FAILURES.md`. Looks at why Malta swarm
answers diverge from ODMI ground truth, to find the fixable bottleneck. The full
baseline set is now available (60 of 60 finalised, batches `exp6_malta` +
`malta_baseline`). The pattern from the earlier 13-pair pilot holds: losses are
dominated by recall, not precision. Across all 60, 17 pairs abstain (`inconclusive`)
and 27 of 60 commit below the D37 0.65 floor; yes-gold recall is 0.60 against
no-gold recall 0.87, so the swarm is far more willing to confirm a `no` than a
`yes` on sparse Malta evidence. False positives are rare but present: 3 of 23
committed no-gold answers (I7, I8-b, PT29), the visible-error class Malta exists to
expose. The retrieval ceiling (exhausted Tavily, DIY-only, self-report / deny-list
questions) is the single largest driver; the `data.gov.mt` Cloudflare 403 part of
it is now mitigated by the `head_ok` Playwright fallback, leaving the self-report
and thin-SERP cases as the residual bottleneck.

Phase A codes every Malta non-match to one cause from a pre-specified taxonomy
(fetch 4xx/5xx, no source, substring-gate failure, below-floor abstention, wrong
answer, near-miss band, self-report/deny-list ceiling, stale ground truth),
deterministically where the DB signal is unambiguous and with an Opus judge over
frozen evidence only for the genuine-error vs stale-gold residual. Phase B is a
free confidence-floor sweep (0.65 / 0.55 / 0.50) replayed on the stored Researcher
confidences, reporting the recovery-precision trade-off and adopting a lower floor
only under a pre-set precision and false-positive bound. Malta being base-rate
balanced (R4) is what makes the false-positive check meaningful.

Harness: `evaluation/malta_failure_audit.py` (to build). Phase A runs incrementally
on whatever Malta pairs exist; the floor sweep needs no quota. Tavily-independent.

Result: pending.

## EXP-7: Retry chaining / evidence accumulation (code built, pre-registered)

Pre-registered in `docs/EXPERIMENTS_CHAINING.md` under the universal rules
(`EXPERIMENTS_PROTOCOL.md` section 0). The chained code path is **built and
committed**, gated behind `--chained` (default off), so production and the
EXP-8/9 baseline are byte-identical to the independent-retry loop.

Up to eight calls run per pair (four Researcher, four Verifier across the retry
budget), but today they are independent shots. The Verifier searches the web
every round and often finds real evidence, then the loop keeps only its verdict
and bins the evidence. The Researcher on retry 3 does not know what the Verifier
turned up on rounds 1 and 2. The calls are spent, the findings are thrown away.
SPEC D33 carries queries and the rejection reason forward, D34 persists snippets,
D37 applies the commit floor, but no round sees what the earlier rounds gathered.

What the `--chained` arm now does (all flag-gated, default off):
- Feeds the Verifier's counter-evidence (its `counter_evidence_quote` /
  `counter_source_url`) back into the `ResearcherInput` on retry, not just the
  verdict and a suggested query (`VerifierFeedback` extended).
- Accumulates an evidence corpus across rounds (the Researcher's and Verifier's
  snippets, already persisted under D34; new `EvidenceItem` model) and carries it
  forward via `ResearcherInput.prior_evidence`, so each round sees everything
  found so far. The coordinator merges with de-dup and a 40-item cap.
- Has the Adjudicator synthesise over the whole corpus
  (`AdjudicatorInput.evidence_corpus`), committing only above the D37 floor and
  abstaining honestly otherwise. The floor and abstention rules are unchanged
  across both arms; the treatment only changes what each call sees.

Carried evidence and its using-instruction travel in the per-call user message,
not the system prompt, so `prompt_versions` rows are identical across arms and an
empty corpus renders byte-for-byte as the pre-EXP-7 prompt. Offline tests in
`tests/test_chained_evidence.py` pin all three: the chained path carries evidence
forward, the baseline path is byte-identical, and the flag defaults off.

Hypothesis: chaining recovers more correct answers per call than independent
retries, without raising the false-positive rate.

Conditions: `baseline` (current independent retries, D33 / D37) vs `chained`.
Endpoints, read balance-aware per R4: recovery (balanced accuracy + per-class
rates against ground truth), false-positive rate (committed but wrong, the
co-primary), abstention rate, and calls per resolved pair. Paired McNemar (×2)
and Wilcoxon; one confirmatory joint claim (balanced-accuracy non-decrease at a
non-increased false-positive rate). Full design in `EXPERIMENTS_CHAINING.md`.

Where to run: Malta primary (English official, ~30 `no`-gold binary questions so
a false `yes` is visible), Netherlands secondary. France is barred (99% `yes`,
recovery indistinguishable from majority-class guessing, the D35 / D37 / R4
lesson). The lower-resource `no`-heavy countries (BA, MK, ME, BG, IS) are deferred
to a follow-on so a poor result there is not blamed on language.

Prerequisite: the Malta dispatch is done (60/60, shared with EXP-6/8/9), so the
`no`-gold candidates now exist and the run is no longer quota-gated (20x plan).
The code and pre-registration are done.

Status: code built and committed (flag-gated, default off), pre-registered. Run
not started, pending the Malta dispatch and quota.

Result: pending.
