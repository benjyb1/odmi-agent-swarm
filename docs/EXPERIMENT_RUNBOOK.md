# Experiment runbook

The operational layer for running swarm experiments. `EXPERIMENTS_PROTOCOL.md`
holds the statistical rules (R1-R12: pre-registration, base-rate country
selection, blinded judges, fixed n, Wilson intervals, cost per item). This
runbook is the *how I execute* layer: the spec format, the preflight gate, the
concurrency model, the reflection points, and the bug log. The `run-experiment`
skill drives it. Together they exist for one reason: so an experiment is
trustworthy every time, not when I happen to remember the rules.

The orchestrator is `scripts/run_experiments.py`. It is the only sanctioned way
to launch a multi-arm run, because it enforces the rules below by construction
rather than by memory.

## The two catches, and how the orchestrator solves them

1. **Shared-cache contamination.** The DIY search cache is keyed on query/url,
   not on `experiment_id`, so two arms that vary retrieval read each other's
   snippets. Any experiment typed `retrieval` or `cost` is forced to
   `--no-cache`; the preflight will not start it warm. Accuracy experiments with
   identical retrieval may share the warm cache as a benign speed-up.

2. **Search-side concurrency ceiling.** The binding limit on throughput is the
   number of concurrent DIY pipelines (Serper quota and target-site WAFs), not
   the Claude budget, which is linear (D42). So arms run **sequentially**, each
   internally parallel up to one global cap (`global_parallel`, default 8).
   Sequential-at-cap has the same throughput as concurrent-at-global-cap, with
   clean per-arm cost, no cross-arm cache race, and a natural reflection point
   between arms. Never launch N independent dispatches with their own
   `--parallel`; that multiplies the in-flight count and trips the WAFs.

## Spec format

A run is one JSON file. The orchestrator flattens it to an ordered arm queue.

```json
{
  "run_id": "exp17_funnel_20260622",
  "global_parallel": 8,
  "budget_calls": 6000,
  "experiments": [
    {
      "experiment_id": "exp17_funnel",
      "type": "retrieval",
      "questions_from": "data/questions/nl_eval_pairs.json",
      "countries": ["NL"],
      "baseline_knobs": {
        "provider": "diy", "strategy": "verifier-disprove",
        "max_results_per_query": 5, "num_queries": 3, "max_retries": 3
      },
      "arms": [
        { "condition_label": "baseline", "knobs": {} },
        { "condition_label": "breadth_8", "knobs": { "max_results_per_query": 8 } }
      ]
    }
  ]
}
```

- `type` is one of `accuracy` | `retrieval` | `cost` | `replay`. It sets the
  cache discipline and the one-variable check.
- Pairs come from `pairs` (explicit `QID:CC`), or `questions` + `countries`, or
  `questions_from` (a pair-set file) + `countries`.
- `baseline_knobs` apply to every arm; an arm's `knobs` override them. The
  knob keys map to the `dispatch_subtrios.py` flags (provider, strategy,
  max_results_per_query, num_queries, max_retries, prompt_variant, the three
  model knobs, the two escalation-model knobs, chained, no_cache).
- `budget_calls` is mandatory: the hard ceiling on Claude calls for the whole
  run. Nothing runs without one.

Dry-run any spec first: `uv run python scripts/run_experiments.py spec.json
--dry-run` prints the planned command per arm and whether the cache is off.

## Preflight gate (enforced by the orchestrator, hard-fail)

1. **D47 hold-out.** No pair may use a held-out eval country (BA, MK, ME, BG,
   FI, HR, SE, BE). They are frozen until the frozen headline run. Any country
   that is neither dev (NL, MT, NO, FR, AL) nor held-out is flagged for a manual
   confirm.
2. **Budget present.** `budget_calls` must be set.
3. **Deny-list importable.** `agents.tools.blocked_domains` must load (D24).
4. **One variable.** Within an experiment, every arm differs from the baseline
   in at most one knob. More than one is a confounded comparison and aborts.
   (This is the `feedback_experiments_one_variable` rule made mechanical.)
5. **Unique labels.** Every arm has a distinct `condition_label`, so the resume
   path and cost attribution stay clean (the lookup is scoped by
   `experiment_id` + `condition_label`).

## Reflection points (when to stop and think)

The run is autonomous while healthy and **pauses itself** otherwise. A pause is
not a failure; it is the design. On a pause, read `evaluation/runs/<run_id>/
events.jsonl`, diagnose, then re-run the same spec (completed arms are skipped).

- **Budget pause.** If the next arm's worst-case calls would breach
  `budget_calls`, the run stops before spending. Do not just raise the budget
  reflexively: ask why the projection is high (is the retry rate inflated? is an
  arm larger than intended?).
- **Health pause.** After each arm the orchestrator checks the blocker rate
  (pairs stuck on `interrupted_blocker` / `interrupted_rate_limit` / `failed` /
  `orphaned`) and the finalise rate. A high blocker rate means search-side
  overload: lower `global_parallel` and resume, do not push harder. A low
  finalise rate means a thin web, the deny-list / self-report ceiling, or a real
  bug: read the `failure_mode` values before deciding which.
- **Dispatch error.** A non-zero return from a child dispatch stops the run for
  inspection rather than rolling on.

Never respond to a concurrency or error spike by increasing parallelism or the
budget to push through it. Stop, find the cause, fix or back off, then resume.
Runs do not escalate their own resource use.

## Bug and issue log

Every run writes `evaluation/runs/<run_id>/events.jsonl` (arm start/end, health
snapshots, pauses) and `manifest.json` (the planned arms and budget). When a run
surfaces a real bug (not a thin-web ceiling, an actual defect), record it:

- a one-line entry in the run's events log is automatic;
- a durable bug gets a note in `docs/KNOWN_GAPS.md` or a fix on its own commit,
  with the `run_id` and the failing `(question, country)` cited so it replays.

## Pre-registration and reporting

Before any run, the experiment is pre-registered: a row in the `experiments`
table (D27) and a design note (endpoints, fixed n, the analysis, the adoption
rule) under `docs/`, per `EXPERIMENTS_PROTOCOL.md`. Results are read
balance-aware and three-outcome (commit-accuracy / coverage / false-positive
rate), never as a single accuracy number, because the gold is base-rate skewed
(D38 R4, D47). A null is a result; log it, do not bury it (R12).
