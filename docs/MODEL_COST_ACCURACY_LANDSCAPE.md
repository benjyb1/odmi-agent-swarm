# Model cost/accuracy landscape (RQ5)

Whole-stack model comparison on the frozen 156-pair dev battery
(MT 60 + NL 52 + AL 44), scored against ODMI ground truth. Each arm runs one
model in every role (researcher, verifier, adjudicator, snippet picker,
query-gen); the model is the only variable. Production config throughout: DIY
search, verifier-disprove, `narrow_then_wide`, snippet picker on, 3 retries,
5 results per query.

## Result

| Model (all roles) | Accuracy (correct / 156) | Commit rate | Cost | Cost / correct answer |
|---|---|---|---|---|
| **Sonnet 4.6** | **34.0%** (53) | 50.0% | £10.39 | £0.20 |
| **Haiku 4.5** | 28.8% (45) | 42.9% | **£6.14** | **£0.14** |
| **Opus 4.8** | 21.8% (34) | 30.1% | £22.12 | £0.65 |

"Accuracy" is correct answers *delivered* against ground truth over all 156
pairs: an abstention counts as a miss, because a swarm that abstains has not
answered the question. "Commit rate" is the share of pairs on which the swarm
committed a label rather than abstaining. Cost is the arithmetic-equivalent
figure (Anthropic list pricing; marginal cost is zero under the Max plan, D1).

## Significance

Paired exact McNemar on the same 156 pairs (concordant pairs dropped):

| Comparison | Right-where-other-wrong | p |
|---|---|---|
| Sonnet 4.6 vs Opus 4.8 | 21 vs 2 | < 0.001 |
| Haiku 4.5 vs Opus 4.8 | 17 vs 6 | 0.035 |
| Sonnet 4.6 vs Haiku 4.5 | 20 vs 12 | 0.215 |

## What it says

1. **Opus 4.8 is dominated.** It is the *least* accurate model on this battery,
   significantly worse than both Sonnet 4.6 (p < 0.001) and Haiku 4.5 (p = 0.035),
   at the highest cost of the three. Its heavy abstention (30% commit rate) means
   it delivers the fewest correct answers despite the highest per-commit precision
   (72%). The "larger model is better" prior is false here.
2. **Sonnet 4.6 and Haiku 4.5 are a statistical tie on accuracy** (p = 0.215).
   Sonnet is nominally ahead (34.0% vs 28.8%) but the gap sits inside noise.
3. **The tie breaks on cost.** Haiku delivers the same accuracy as Sonnet for
   ~60% of the cost, and the best cost-per-correct-answer of the three (£0.14).
   Practical read: run **Haiku** for cost-efficiency, **Sonnet 4.6** for the
   (non-significant) accuracy edge, **never Opus** for this task.

Behavioural driver: model tier trades coverage for caution. The higher-tier
model abstains more; the extra per-commit precision does not pay for the lost
coverage on the delivered-accuracy metric.

## Provenance and caveats

- **Haiku 4.5**: `exp32_model_haiku / haiku_h45`, run 2026-07-12.
- **Opus 4.8**: `exp36_model_opus / opus_o48`, run 2026-07-12/13. 9 pairs finalised
  as `agent_failure` for infrastructure reasons (a Serper credit-exhaustion
  outage, since fixed; see below), which depresses its effective commit rate by
  ~6% — Opus's true numbers would be marginally better, not enough to change the
  ranking.
- **Sonnet 4.6**: `exp34_retrieval_strategy_s46 / baseline_narrow_then_wide`, an
  all-4.6 whole-stack run over the exact 156 battery at production config (the
  `_s46` redispatch pins every role to `claude-sonnet-4-6`). Its
  verifier/adjudicator model strings live in that experiment's own worktree DB
  rather than canonical; the researcher is confirmed 4.6 and the redispatch was
  4.6 by design. Confirm those two role strings before this is a load-bearing
  dissertation claim.
- **No Sonnet 5.** Sonnet 5 is cut (production is 4.6 only). The historical
  `exp28/trio_s5` data is Sonnet 5 and is deliberately excluded from this
  comparison.
- **Single run per model, n = 156.** The McNemar handles the pairing; the
  Sonnet/Haiku accuracy tie specifically could resolve either way with more pairs.
- **Config note.** A query-gen `max_tokens` bump (200 to 400) landed partway
  through the Opus run to fix truncation failures; Haiku ran entirely at 200.
  Second-order, affects only rare query-gen truncation.

## Adjunct: adjudicator-model escalation on frozen evidence

Two paired single-variable replays (evidence held identical, only the
adjudicator model swapped) test whether a stronger last-look checker helps:

- **Haiku evidence, Sonnet 4.6 adjudicator** (`h_h_s`, 104 adjudicated pairs):
  Sonnet flipped 12/104 (11.5%) of the Haiku adjudicator's calls, toward more
  abstention; accuracy on the re-judged subset rose 52.9% to 66.7%. £1.10.
- **Sonnet evidence, Opus 4.8 adjudicator** (`s_s_o`, 110 pairs): Opus flipped
  only 4/110 (3.6%); subset accuracy fell 60.0% to 44.4% (tiny committed n,
  5 vs 9). £2.63. Note the *source* evidence here is Sonnet 5, so this arm is
  reported for the pattern only, not as a 4.6 result.

Consistent with the headline: a stronger adjudicator is more conservative, and
that caution is not reliably an accuracy win.

## Code fixes landed alongside

- `SearchProviderExhausted` (`agents/errors.py`, `agents/tools/search_serper.py`):
  a Serper `400 "Not enough credits"` now degrades to a clean resumable shutdown
  instead of crashing the coordinator uncaught (same contract as the D58
  `AuthUnavailableShutdown`).
- Query-gen `max_tokens` 200 to 400 (`agents/researcher.py`, `agents/verifier.py`):
  stops adversarial-query truncation failures observed on the Opus arm.
- `evaluation/replay_adjudicator_escalation.py`: the frozen-evidence
  adjudicator-only escalation harness used for the two adjunct replays.

## Reproducibility

The raw experiment rows for the two new arms (`exp32_model_haiku`,
`exp36_model_opus`) are exported as text in
`evaluation/results/model_landscape_rows.sql` for migration into the canonical
DB (the binary worktree DB is a diverged fork and is deliberately kept out of
the merge). The two replay outputs are in
`evaluation/results/{h_h_s,s_s_o}_adjonly_replay.jsonl`.
