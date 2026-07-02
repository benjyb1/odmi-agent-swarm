# EXP-28 / EXP-29 pre-registration: architecture ablation ladder, Sonnet 5

Registered 2026-07-01, before dispatch (R1). Runs overnight 2026-07-01/02.

## Motivation

The dissertation's central engineering claim is that an adversarial
verification layer buys precision that a lone research agent cannot supply.
The evidence so far is indirect: EXP-13a measured the whole
verify-and-adjudicate layer by deterministic replay (removing it cost 27
correct answers and saved 16 wrong ones, net -11), and EXP-15 (Adjudicator
standalone) was designed but never run. No live experiment has ablated the
Verifier alone, and no experiment separates the Verifier's contribution from
the Adjudicator's. EXP-28 runs the ladder live. EXP-29 rides the same pair
set to give the first Sonnet 5 whole-stack data point against a same-night
Sonnet 4.6 control.

## Design

**EXP-28 `exp28_arch_ablation`** — one knob, `pipeline_mode`, three arms:

| Arm (condition_label) | pipeline_mode | What runs |
|---|---|---|
| `trio_s5` (control) | `trio` | Production pipeline: Researcher -> Verifier loop -> Adjudicator on exhaustion |
| `no_adjudicator_s5` | `no_adjudicator` | Researcher -> Verifier loop; retry exhaustion abstains (`abstained_no_adjudicator`). Delivers the EXP-15 design. |
| `researcher_only_s5` | `researcher_only` | Researcher alone; commit iff a real label at or above the D37 floor (`accepted_researcher_only`); exhaustion abstains. |

The honesty layer (D35 abstention retries, D37 0.65 commit floor) is held in
every arm: it is a distinct mechanism from the adversarial verification layer
under ablation, and removing both at once would confound the comparison.

**EXP-29 `exp29_sonnet5_model`** — single arm `trio_s46`: the identical trio
pipeline and pair set with every model knob pinned to `claude-sonnet-4-6`.
Its pre-registered control is EXP-28/`trio_s5` (identical knobs except the
model family, compared on the same pairs). Encoding the model contrast as a
separate experiment keeps the orchestrator's one-variable preflight honest:
within each experiment, arms differ in exactly one knob.

Ladder comparisons (paired, same pairs):
- `trio_s5` vs `no_adjudicator_s5` isolates the Adjudicator.
- `no_adjudicator_s5` vs `researcher_only_s5` isolates the Verifier loop.
- `trio_s5` vs `researcher_only_s5` is the whole verification layer (the
  live counterpart of EXP-13a's replay estimate).
- `trio_s46` vs `trio_s5` isolates the model family (whole stack: agents and
  picker move together, pre-registered as a whole-stack contrast).

## Sample

The three committed canonical dev pair sets, 156 pairs per arm:
- `data/questions/malta_eval_pairs.json` — MT, 60 (30 no / 30 yes golds)
- `data/questions/nl_eval_pairs.json` — NL, 52 (26 / 26)
- `data/questions/al_eval_pairs.json` — AL, 44 (22 / 22)

78 negative golds per arm; base-rate-balanced by construction (R3). All dev
countries (R8); the D47 held-out eight are untouched (R7).

## Models and knobs

All EXP-28 arms: `researcher_model` = `verifier_model` = `adjudicator_model`
= `picker_model` = `claude-sonnet-5`. Every other knob at the production
default: provider diy, 3 queries, 5 results/query, snippet picker on,
600-char snippets, 16k page cap, bilingual queries, narrow_then_wide,
verifier counter-search always, retry cap 3, no chaining, standard
adjudicator selection.

## Endpoints

Primary (per arm, on the 156 golds):
- Balanced accuracy and per-class rates: TPR (yes-gold recall), TNR (no-gold
  recall), FPR on committed answers (R4).
- Commit precision: exact-match rate over committed (non-abstained) pairs.
- Coverage: committed / 156, and abstention rate.

Secondary (descriptive): cost per pair and per correct answer (R9, GBP),
wall-clock per pair, retry depth distribution, Youden's J, per-country and
per-dimension splits, decision-stratified (confirm/complement/change) splits.

Statistics: Wilson intervals on all rates; paired McNemar on the overlapping
committed set for each ladder comparison, Holm-corrected within the
three-comparison EXP-28 family (R10). n=156 with 78 negative golds is
powered for the primary FP-rate contrasts at roughly the effect sizes
EXP-13a suggests; smaller effects will be reported descriptively (R11).

## Adoption rule (R2)

This is a characterisation experiment, not an optimisation: the production
trio stays regardless. The pre-registered claims at stake:
- The verification layer's live value: confirmed if `trio_s5` beats
  `researcher_only_s5` on committed-answer precision by >= 5 points AND cuts
  the no-gold FP rate, at McNemar p < 0.05 on the paired committed set.
- The Adjudicator's marginal value: quantified by the `trio_s5` vs
  `no_adjudicator_s5` gap in coverage and in correct-recoveries (pairs the
  Adjudicator committed that match gold) vs wrong-recoveries.
- Sonnet 5 adoption (EXP-29): switch the production default to
  `claude-sonnet-5` only if `trio_s5` is non-inferior on balanced accuracy
  (delta >= -0.02) AND does not raise the no-gold FP rate by more than 2
  points; otherwise stay on 4.6.

## Cache policy (pre-registered R6 deviation)

`type` is `accuracy`, so the shared DIY cache stays warm and is SHARED
across arms deliberately: arms differ only downstream of retrieval, so a
shared cache gives every arm the same evidence for the same query, turning
retrieval sampling noise into a matched-pairs constant. This is a deviation
from the strict cold-cache reading of R6, justified because no endpoint here
measures retrieval or cost-of-retrieval. Arms run sequentially
(trio_s5 first), so the first arm populates most of the cache.

## Transport note (recorded per R12)

CLIProxyAPI 7.2.45 (restarted 2026-07-01 to expose `claude-sonnet-5`)
replaces the API `system` parameter with the Claude Code system prompt.
From this run onward, agent instructions travel in the user turn inside an
`<instructions>` block (`agents/tools/llm.py`, commit d2b61de). This affects
every arm equally, including the EXP-29 Sonnet 4.6 control, so within-night
comparisons are clean; comparisons against pre-2026-07-01 runs (e.g. the
June Malta baseline) cross a transport change and are flagged as such.
Claude 5 calls also omit `temperature` (the model rejects it); pre-5 arms
keep temperature 0.0. This is a model-family property and is absorbed into
the model contrast.

## Failure handling

Idempotent resume via the orchestrator (re-running the spec skips finalised
pairs per arm). Rate limits surface as clean interrupted-and-resumable
shutdowns; the overnight harness re-runs the spec on wake.

## Run-time deviations (R12, recorded as they happened)

- 2026-07-02 00:03: trio_s5 arm done, 132/156 finalised, healthy (blocker
  rate 0.071). Calls per pair ran ~57 against the 17-per-pair planning
  worst case: the Sonnet 5 Verifier rejects at a high rate, so most pairs
  ride the full retry ladder into adjudication (each round costs
  researcher query-gen + picker + main plus verifier query-gen + main).
  `budget_calls` raised 14,000 -> 32,000 in the spec on that evidence; the
  ceiling was a planning artefact, and the elevated call rate is itself an
  arm-level finding (verification is expensive on this model), not a fault.
- 2026-07-01 ~23:00: the owed D51 migration (`escalate_human` -> `abstain`)
  had never been applied to the committed DB, so every Sonnet 5 Adjudicator
  `abstain` verdict crashed the pair on the phase2_adjudications CHECK
  (stuck `adjudicating` orphans, no final row). Migration applied mid-arm
  (1,197 rows preserved); crashed pairs re-run via the idempotent resume
  sweep at the end of the run. agent_failure finals from the pre-fix
  Verifier schema collapse were deleted (3 + 8 rows) so the sweep retries
  them on fixed code.
