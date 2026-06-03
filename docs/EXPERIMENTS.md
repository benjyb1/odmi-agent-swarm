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
| EXP-6 | Verifier strategy discrimination (4-arm signal detection) | running | primary Malta natural errors (48 candidates, 24 should_fail / 24 should_pass), NL secondary, FR + injected robustness | Malta baseline landed (60/60); `verifier_strategies.py` running on frozen evidence, results streaming to `evaluation/results/verifier_strategies_verifier_strategy_disc_v1.jsonl` |
| EXP-7 | Retry chaining: accumulate evidence across the loop | registered, run queued | Malta primary (no-gold-rich), NL secondary | both arms (`baseline`, `chained`) to dispatch cold under `retry_chaining_mt_v1`, ~40 dim-stratified pairs; queued behind EXP-6 (shared quota, protocol section 10) |
| EXP-8 | Cost-side optimisations (Family 1) | registered, run queued | baseline + prompt-compressed / retrieval-tight / cache-hot / model-fallback; MT primary, NL secondary | queued behind EXP-7; ~160 fresh swarm runs |
| EXP-9 | Model variants (Family 3) | registered, run queued | Haiku / Sonnet / Opus / tiered; MT primary, NL secondary | queued behind EXP-8; Opus arm is the costliest single run in the programme |
| EXP-10 | Malta failure-mode audit + confidence-floor recovery | done | MT 60 finalised pairs vs ground truth; Phase A taxonomy, Phase B floor sweep | match 32/60; losses 17 fixable + 11 wrong + 0 structural; floor stays 0.65 (lower floors fail the precision>=0.80 bound). `evaluation/results/malta_failure_audit_MT.jsonl` |

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

Harness: `evaluation/malta_failure_audit.py`. Phase A runs incrementally
on whatever Malta pairs exist; the floor sweep needs no quota. Tavily-independent.

Result (done 2026-06-03, full canonical 60-pair Malta set). Match 32/60; losses
split 15 abstain, 11 differ, 2 no-swarm-answer. Phase A taxonomy over the 28
non-match pairs: 17 fixable (9 fetch 4xx/5xx, 5 below-floor abstention, 2
substring-gate, 1 abstain-other), 11 genuine wrong answers, 0 structural/stale-gold
(the conservative `--llm` residual judge coded every `differ` as a real error).
This confirms the pre-registered framing: Malta's losses are recall-dominated and
fixable, not silent wrong commits. Phase B floor sweep: 0.65 (baseline) commits 43,
32 correct, negative-gold FPR 0.10; 0.55 recovers +4 at 0.50 precision; 0.50
recovers +10 at 0.70 precision, FPR 0.13. The pre-set decision rule (precision
>= 0.80, FPR rise <= 0.05) keeps the floor at **0.65**; both lower floors fail the
precision bound. The D37 floor is vindicated. Receipts:
`evaluation/results/malta_failure_audit_MT.jsonl`.

Data-integrity fix found during the QA pass: the dispatch had written 72
`phase2_final` rows for the 60 distinct MT questions (stale `agent_failure` rows
superseded by real finalisations, plus a few concurrent double-finalisations,
two of which conflicted: Q6, PT29). `load_pairs` counted all 72, double-counting
questions and reading the negative-gold denominator as 40 not 30, which would have
corrupted the Phase-B false-positive rate. Fixed by selecting the canonical row
per (question, country) = highest id, `experiment_id IS NULL` for main runs,
mirroring the dashboard's match-matrix rule (`dashboard/lib/db.py`). The same
canonical dedup, partitioned per arm, was added to `chaining_analysis.py` for
EXP-7. Both pinned by regression tests.

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

Prerequisite: the Malta dispatch (search-quota gated, shared with EXP-6/8/9; the
`no`-gold candidates do not exist in the DB yet) and Claude headroom. The run is
gated only on those two; the code and pre-registration are done.

Status: code built and committed (flag-gated, default off), pre-registered. Run
not started, pending the Malta dispatch and quota.

Result: pending.
