# EXP-6 runbook: build the dataset (6a), then run the four-arm judge (6b)

EXP-6 is split into two phases so the dataset is frozen before it is judged. This
is the page to hand an agent: "fill out the database for EXP-6a" means run phase A
below.

Pre-registration: `docs/EXPERIMENTS_VERIFIER.md`. Status board: `docs/EXPERIMENTS.md`.

---

## What EXP-6 measures

Each of the four D15 verifier strategies (`disprove`, `negation`, `steelman`,
`blind`) is treated as a binary classifier over a Researcher candidate answer:
`pass` = accept, `fail` = reject. The endpoint is how well each tells a wrong
answer from a correct one (Youden's J), per token. So the dataset needs both
classes with real mass: `should_fail` (Researcher answer differs from ODMI gold)
and `should_pass` (matches). `should_fail` is the binding constraint and the whole
reason for the design below.

## The dataset (target ~120 candidates)

Written to the `exp6_candidates` table, one row per candidate, each pinning the
`phase2_researcher_runs.id` it was frozen from:

| Stratum | Role | Source | Label | ~n |
|---|---|---|---|---|
| NAT-fail | primary | MT committed runs that differ from gold | should_fail | ~13 |
| NAT-pass | primary | MT committed runs that match gold | should_pass | ~28 |
| NAT-fail / NAT-pass | secondary | NL committed runs (after the NL dispatch) | both | ~40 |
| INJ-fail | robustness | FR/EE correct binary runs, label flipped yes↔no | should_fail | 35 |

Excluded by rule: abstentions (`inconclusive` / `not_applicable`), pairs with no
ODMI gold, pairs with no committed run. Latest `id` wins per pair, so a finished
v2 re-run is the one frozen.

The injected flips are **robustness only**, never folded into the primary J. They
need no new research run, they reuse existing FR/EE correct runs.

---

## Phase A (EXP-6a): fill the database

Goal: every pair in the two worklists has a committed Researcher run, then freeze.

1. **Build the NL worklist** (once; deterministic, seed 20260603):
   ```bash
   uv run python scripts/build_nl_eval_pairs.py
   ```
   Writes `data/questions/nl_eval_pairs.json` (52 pairs: all 26 NL `no`-gold binary
   + 26 matched `yes`, dimension-stratified). MT's worklist
   (`data/questions/malta_eval_pairs.json`) already exists.

2. **Dispatch the swarm over the NL worklist.** This is the long, quota-spending
   step; Benjy runs it himself in a dedicated branch (do not auto-launch a
   multi-hour background loop on the shared quota). MT is already dispatched.
   The dispatcher takes an explicit `--pairs QID:CC ...` list, so derive it from
   the worklist JSON:
   ```bash
   PAIRS=$(uv run python -c "import json; d=json.load(open('data/questions/nl_eval_pairs.json')); print(' '.join(f\"{p['question_id']}:{p['country_code']}\" for p in d['pairs']))")
   uv run python scripts/dispatch_subtrios.py --pairs $PAIRS \
       --condition-label exp6_nl --batch-id exp6_nl
   ```
   NL is already in `run_coordinator.COUNTRIES`. Resumable: re-run to pick up where
   a 429 stopped (the freeze in step 3 reads whatever has committed so far).

3. **Freeze the candidate set** (safe to repeat; idempotent per experiment_id):
   ```bash
   uv run python scripts/build_exp6_candidates.py            # --inj-target 35 default
   ```
   Creates `exp6_candidates`, registers the experiment, prints achieved counts.
   Re-run after the NL dispatch lands, and again if MT v2 adds committed answers.

**Phase A is done when** `build_exp6_candidates.py` reports a populated secondary
(NL) stratum and ~115-120 total, e.g.
`natural: ~23 should_fail + ~57 should_pass; injected: 35`.

Sanity check the frozen table:
```bash
sqlite3 data/odmi.db "select role, stratum, count(*) from exp6_candidates \
  where experiment_id='verifier_strategy_disc_v1' group by role, stratum"
```

## Phase B (EXP-6b): run the four-arm judge

Reads the frozen table by default (the snapshot, immune to later DB writes):
```bash
uv run python evaluation/verifier_strategies.py            # full four-arm run
uv run python evaluation/verifier_strategies.py --limit 6  # smoke first
```
`--live` forces the legacy live builder (only for debugging; not for the real run).
Frozen evidence per candidate (one query-gen + one search, shared across all four
arms), temperature 0, resumable, writes
`evaluation/results/verifier_strategies_verifier_strategy_disc_v1.jsonl` and a
summary block. Cost ≈ 4 × candidates main calls + one evidence-prep each, so ~120
candidates ≈ 480 verifier calls + 120 preps.

Report the primary J on the MT+NL natural set, the injected-only J separately as
robustness, per-class rates with Wilson intervals, and the honest caveat that
`should_fail` ≈ 23 gives wide intervals and a directional ranking.
