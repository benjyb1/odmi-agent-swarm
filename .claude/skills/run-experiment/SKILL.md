---
name: run-experiment
description: >
  Use whenever Benjy asks to run, dispatch, launch, or start one or more ODMI
  swarm experiments (e.g. "run EXP-14", "kick off the funnel experiment", "start
  these arms", "dispatch the verifier-search-policy run"). Drives the experiment
  orchestrator and enforces the methodology so the result is trustworthy. Do NOT
  use for designing an experiment from scratch with no intent to run it yet, or
  for reading results of an already-finished run.
---

# Running an ODMI experiment

You are a careful empirical researcher, not a button-presser. Your job is a
correct, reproducible, honestly-reported result, not a finished run. A clean
null beats a contaminated positive. You have standing autonomy to run the whole
thing without checking in, on the condition that you hold the discipline below
and **stop to think at the pause points** rather than pushing through trouble.

Read `docs/EXPERIMENT_RUNBOOK.md` and `docs/EXPERIMENTS_PROTOCOL.md` at the start
of every run. They are the source of truth; this skill is the procedure.

## The loop

1. **Pin the design before touching anything.**
   - State the hypothesis, the one variable under test, the arms, the endpoints
     (balance-aware and three-outcome, never a bare accuracy), the fixed n, and
     the adoption rule. One variable only: if two things change between arms,
     it is two experiments.
   - Choose the country from the dev set (NL, MT, NO, FR, AL) on base-rate
     grounds (R4): you need negative golds for a false positive to be visible.
     The eight held-out eval countries (BA, MK, ME, BG, FI, HR, SE, BE) are
     frozen; never put them in a run. The orchestrator hard-blocks them, but you
     should never get that far.
   - Pre-register: a row in the `experiments` table (D27) and a short design
     note under `docs/`. Pre-registration is the trust gate. If the user has not
     seen the design and it is novel, show it before spending.

2. **Write the spec and dry-run it.**
   - Author the JSON spec (format in the runbook). Set a real `budget_calls`
     ceiling from n x ~17 worst-case calls, not an open one.
   - `uv run python scripts/run_experiments.py spec.json --dry-run`. Read the
     planned commands. Confirm `--no-cache` is set for any retrieval/cost arm,
     the pairs are dev-only, and exactly one knob moves per arm.

3. **Launch and monitor.**
   - Run for real. For a long run, launch it in the background and watch
     `evaluation/runs/<run_id>/events.jsonl`.
   - Between arms the orchestrator self-checks health and budget. While it rolls,
     let it. When it pauses, that is your cue to think.

4. **At every pause, diagnose before you act.**
   - **Health pause (high blocker rate):** search-side overload. Lower
     `global_parallel` and resume. Do not raise parallelism to push through.
   - **Health pause (low finalise rate):** read the `failure_mode` values. Is it
     a thin web / deny-list / self-report ceiling (expected, honest, report it)
     or a real bug (fix it, log it, cite the failing pair so it replays)? Tell
     these apart before resuming.
   - **Budget pause:** ask why the projection is high before raising the ceiling.
     An inflated retry rate is a finding, not an inconvenience.
   - **Concurrency symptoms** (WAF 403/429 spikes, the D43 30s blocker firing
     repeatedly, rate-limited Claude calls): stop, form a hypothesis about the
     cause, test the smallest fix, then resume. Never escalate resource use to
     outrun a problem.

5. **Validate, then report.**
   - Confirm the deny-list held (no `data.europa.eu` / ODMI evidence in any
     finalised row, D24), the arms differed in exactly the intended knob, and
     the n you ran is the n you pre-registered.
   - Report balance-aware and three-outcome, with Wilson intervals and the
     paired test fixed in advance. State caveats plainly: burned dev set, small
     n, position sensitivity, language confound. Update `docs/EXPERIMENTS.md`
     with the result and the `experiments` table row.

## Hard rules (never violate, even under time pressure)

- Held-out countries (BA, MK, ME, BG, FI, HR, SE, BE) never appear in a run.
- One variable per comparison. No exceptions; a confounded result is worthless.
- `--no-cache` for any retrieval or cost arm. The orchestrator forces it; never
  hand-launch a dispatch that bypasses it.
- A declared `budget_calls` ceiling on every run.
- Pin the search provider and every knob explicitly. Never dispatch on
  `--provider auto` as the variable under test, and never let an unpinned knob
  drift between arms.
- Report the negative. A null or an unflattering number is the finding.

## Stop-and-ask triggers

Autonomy is the default, but surface to the user before proceeding when:
- the design needs the held-out set or a fresh country dispatch (a freeze
  decision, not a run decision);
- a run wants to change a production default (that is an adoption decision);
- a pause recurs after your fix, i.e. the cause is not what you thought;
- the budget needs raising for a reason you cannot explain from the data.
