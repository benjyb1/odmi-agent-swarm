# Experiments

The status board for swarm experiments: what is planned, queued, running, and
done, with results once they land. Decisions and rationale live in `SPEC.md`;
the machine registry is the `experiments` SQLite table (D27). This file is the
human-readable view, updated whenever an experiment changes state.

**Status values:** `planned` (designed, not scheduled) · `queued` (next to
run) · `running` · `done`.

| ID | Experiment | Status | Scope | Result (short) |
|---|---|---|---|---|
| EXP-1 | DIY vs Tavily, adjudicated (refreshed) | done | FR, 90 pairs | DIY wins 89% of 55 decided pairs (49/6/1), Wilson CI [78,95], p<1e-4; leads all 3 dimensions |
| EXP-2a | Search-knob cost vs quality | queued | FR subset | pending |
| EXP-2b | Search-knob cost vs quality | planned | low-resource countries | pending |
| EXP-3 | DIY vs Tavily, multilingual | planned | RO / EE / HU and other thin-web countries | pending |
| EXP-4 | Brave head-to-head | planned | FR first | pending |
| EXP-5 | Five-provider search A/B | planned | TBD (the parked June plan) | pending |
| EXP-6 | Verifier strategy discrimination (4-arm signal detection) | retargeted (pending Malta dispatch) | primary Malta natural errors, NL secondary, FR + injected robustness | pending; primary J needs the Malta dispatch (search-quota gated); FR/injected partial superseded |
| EXP-7 | Retry chaining: accumulate evidence across the loop | planned | high-resource-language, low-maturity country first (false-positive risk) | pending |
| EXP-8 | Cost-side optimisations (Family 1) | planned | baseline + prompt-compressed / retrieval-tight / cache-hot / model-fallback; MT primary, NL secondary | pending (Malta dispatch, quota-gated) |
| EXP-9 | Model variants (Family 3) | planned | Haiku / Sonnet / Opus / tiered; MT primary, NL secondary | pending (Malta dispatch, quota-gated) |
| EXP-10 | Malta failure-mode audit + confidence-floor recovery | planned | MT finalised pairs vs ground truth; Phase A taxonomy, Phase B floor sweep | pending (Phase A runs incrementally on the exp6_malta set; floor sweep is free) |

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

Caveats (honest): position consistency 81%; the answer-blind robustness check
agrees with the answer-given verdict on only 67% of the 27-pair subsample (9
flips), so the judge is somewhat sensitive to seeing the gold answer; the
cross-family Gemini reliability check is pending quota (key authenticates but the
Google project allows zero generations). France only, Tavily basic tier.

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
robustness FR/EE + injection). The primary Youden's J is not computable until the
Malta dispatch lands, which is gated on search quota.

Result: pending (primary run blocked on the Malta dispatch).

## EXP-8: Cost-side optimisations, Family 1 (planned)

Pre-registered in `EXPERIMENTS_PROTOCOL.md` (section 7). Holds the country, pair
set, and models fixed and varies one cost knob at a time: `baseline`,
`prompt-compressed`, `retrieval-tight`, `cache-hot`, `model-fallback`. Endpoints:
balance-aware accuracy against the Malta majority baseline (R4) and cost per pair
with retries counted (R9). Run on Malta primary, Netherlands secondary.

Prerequisite: the Malta Researcher dispatch (search-quota gated), a committed
`prompt-compressed` prompt version, and the `model-fallback` escalation path.
The apparatus is built (2026-06-03): the compressed Researcher prompt
(`--prompt-variant compressed`, its own `prompt_versions` row, baseline
untouched), the `model-fallback` escalation (`--researcher-escalation-model` /
`--verifier-escalation-model`), and the cold-cache switch (`--no-cache`) for the
lean-vs-`cache-hot` split. Only the Malta dispatch remains.

Result: pending.

## EXP-9: Model variants, Family 3 (planned)

Pre-registered in `EXPERIMENTS_PROTOCOL.md` (section 7). Compares `model-haiku`,
`model-sonnet` (baseline), `model-opus`, and `model-tiered` (Haiku draft, Sonnet
verify, Opus adjudicate) on the same Malta pairs. The confirmatory comparison is
tiered vs all-Sonnet on accuracy and cost; the accuracy-cost surface is the
headline figure. Run on Malta primary, Netherlands secondary.

Prerequisite: the Malta dispatch and per-agent model-override threading. The
threading is built (2026-06-03): `--researcher-model` / `--verifier-model` /
`--adjudicator-model` now all drive the LLM (previously only the Adjudicator
did), and the served version ID is written to `claude_usage_log`. All four arms
are runnable. Only the Malta dispatch remains.

Result: pending.

## EXP-10: Malta failure-mode audit + confidence-floor recovery (planned)

Pre-registered in `docs/EXPERIMENTS_MALTA_FAILURES.md`. Looks at why Malta swarm
answers diverge from ODMI ground truth, to find the fixable bottleneck. A pilot on
the in-progress `exp6_malta` dispatch showed Malta's losses are abstentions, not
wrong answers (8 match / 5 abstain / 0 wrong of the first 13 finalised; the
abstentions split 7 below the D37 confidence floor and 3 on a fetch 403). So the
problem looks like recall, not precision.

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

## EXP-7: Retry chaining / evidence accumulation (planned, future)

Up to eight calls run per pair (four Researcher, four Verifier across the retry
budget), but they are independent shots. The Verifier searches the web every
round and often finds real evidence, then the loop keeps only its verdict and
bins the evidence. The Researcher on retry 3 does not know what the Verifier
turned up on rounds 1 and 2. The calls are spent, the findings are thrown away.

Idea: chain the calls into one cumulative investigation.
- Feed the Verifier's independent evidence (its snippets and counter-evidence)
  back to the Researcher on retry, not just the verdict and a suggested query.
- Accumulate an evidence corpus across rounds (snippets are already persisted,
  D34) and carry it forward, so each round sees everything found so far.
- Let the Adjudicator synthesise over the whole corpus as the final call,
  committing only when the evidence supports a confident label (the D37 floor)
  and abstaining honestly otherwise.

Hypothesis: chaining recovers more correct answers per call than independent
retries, without raising the false-positive rate.

Conditions: baseline (current independent retries, D33 / D37) vs chained.
Metrics per arm: recovery (match against ground truth), false-positive rate
(committed but wrong), abstention rate, and calls per resolved pair.

Where to run, which matters as much as the design:
- Not a yes-heavy country. On France (85% yes) a recovery number cannot be told
  apart from majority-class guessing, the D35 / D37 lesson. The set must carry
  plenty of no-gold pairs so a false `yes` is visible.
- First run on a HIGH-resource-language, low-maturity country, so search and
  model capability are not the bottleneck and the result isolates the chaining
  effect rather than language difficulty. Malta is the leading candidate:
  English is an official language and the open-data ecosystem is largely in
  English, and it has many no-gold pairs (about 30). Defer the lower-resource
  no-heavy countries (BA, MK, ME, BG, IS) to a follow-on so a poor result there
  is not blamed on language.

Prerequisite: the honest validation set (no-gold plus band pairs) must exist
first, both to baseline the current D34 / D37 code and to measure chaining
against it.

Status: planned, not started. Parked as a future experiment.

Result: pending.
