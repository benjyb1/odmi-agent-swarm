# Agent task: run the search-knob cost/quality experiment on a French subset (EXP-2a)

You are working in the ODMI Agent Swarm repo. Run one experiment end to end,
record the results, and commit. Work from logs and the DB; do not guess.

## Read first
- `docs/EXPERIMENTS.md` -> EXP-2 (the experiment definition and the conditions).
- `docs/SPEC.md` -> D29 (DIY pipeline + adjudicated evaluation) and D31 (the
  search knobs and how they thread through the dispatcher).
- Background: the DIY search pipeline costs roughly five to eight times the
  Claude calls of Tavily per pair, because it runs extraction on our own model
  (up to five snippet-picks per search). This experiment tests whether cutting
  the search knobs keeps answer quality while saving that cost.

## What you are testing
Three conditions, identical except the search knobs, all on provider=diy:

| condition_label | --num-queries | --max-results-per-query |
|---|---|---|
| diy_full | (omit; default, up to 3) | 5 |
| diy_lean | 2 | 3 |
| diy_q3r3 | (omit) | 3 |

Run the SAME pairs through all three. Quality = accuracy against ODMI ground
truth. Cost = Claude calls / tokens / cost / mean retry count per pair.

## Step 1 — choose the pair set (web-answerable French subset)
- Read the most recent `evaluation/results/diy_vs_tavily_*.jsonl`. Take the FR
  pairs whose `verdict` is NOT `both_fail`; those are the web-answerable ones,
  where a quality difference can actually show. Exclude any Quality-dimension
  question (they all both-fail on the deny-list and carry no signal).
- Keep only pairs that have an ODMI `ground_truth` row (needed for accuracy).
- Cap to about 8 to 12 pairs to bound cost (see Guardrails).
- Write the exact list down. You must use the identical list for all three
  conditions, or the comparison is invalid.

## Step 2 — run the three conditions
Use a shared `--experiment-id knob_cost_quality_fr` and a distinct
`--condition-label` per condition. Run them sequentially (let one finish before
starting the next) so the rate limit and cost stay legible. `<PAIRS>` is the
space-separated list from Step 1, e.g. `P23:FR I7:FR PT8:FR ...`.

```
uv run python scripts/dispatch_subtrios.py --pairs <PAIRS> \
  --provider diy --max-results-per-query 5 \
  --experiment-id knob_cost_quality_fr --condition-label diy_full --parallel 2

uv run python scripts/dispatch_subtrios.py --pairs <PAIRS> \
  --provider diy --max-results-per-query 3 --num-queries 2 \
  --experiment-id knob_cost_quality_fr --condition-label diy_lean --parallel 2

uv run python scripts/dispatch_subtrios.py --pairs <PAIRS> \
  --provider diy --max-results-per-query 3 \
  --experiment-id knob_cost_quality_fr --condition-label diy_q3r3 --parallel 2
```

After the first condition, sanity-check that the swarm actually used DIY:
the `phase2_researcher_runs` rows for this experiment_id should show DIY in
`search_provider_calls`. If they show tavily or brave, the provider flag did
not take; stop and investigate before spending more.

## Step 3 — wait for completion
The dispatcher is fire-and-forget per pair. Wait until every subtrio for the
experiment_id has a `phase2_final` row or a terminal failure. Poll
`subtrio_status` and `phase2_final`; do not start the analysis early.

## Step 4 — analyse, grouped by condition_label (within the experiment_id)
- Quality: classify each finalised pair against ODMI with `_MATCH_STATUS_SQL`
  (`dashboard/lib/db.py`); report match / near_match / differ counts and the
  match rate per condition. Join `phase2_final` to `ground_truth` on
  (question_id, country_code), filter `experiment_id = 'knob_cost_quality_fr'`,
  group by `condition_label`. The Analytics page already groups by
  condition_label; reuse db helpers if they fit.
- Cost: per condition, total and per-pair Claude calls, tokens, and cost, plus
  mean `phase2_final.retry_count`. Cost rows live in `claude_usage_log` keyed by
  `subtrio_id`; map subtrio to condition via the experiment_id /
  condition_label on the phase2 rows (check `scripts/setup_sqlite.py` for the
  exact columns). Convert cost to GBP via `dashboard/lib/currency.py`.
- Headline: accuracy delta (diy_lean minus diy_full, diy_q3r3 minus diy_full)
  set against the calls-per-pair delta. State whether dropping the knobs held
  quality and how much it actually saved end to end. If a leaner condition
  retried more and erased the saving, say so plainly; that is the most
  interesting result this experiment can produce.

## Step 5 — record and commit
- Update `docs/EXPERIMENTS.md`: move EXP-2a to `done` and fill in the result
  row and the EXP-2 result with the numbers and a one-line verdict.
- Save the per-pair analysis to `evaluation/results/` (a small CSV or JSONL)
  for the audit trail.
- Writing rules: UK English, no em dashes, plain register, no AI tells.
- Commit small and push to origin/main (the repo's convention). No dashboard
  verifier needed unless you changed dashboard code.

## Guardrails
- This spends real Claude rate-limit budget, and DIY is five to eight times
  Tavily per pair. Keep the subset small and `--parallel` low (2). Respect the
  budget soft limit; never `--force` past a budget refusal.
- Same pair list across all three conditions. No exceptions.
- Temperature is already 0 in the LLM wrapper; leave it.
- If quotas are exhausted mid-run, record the partial result honestly and stop.
  Partial is fine. Fabricated or extrapolated numbers are not.
