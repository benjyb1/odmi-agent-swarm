# Experiments

The status board for swarm experiments: what is planned, queued, running, and
done, with results once they land. Decisions and rationale live in `SPEC.md`;
the machine registry is the `experiments` SQLite table (D27). This file is the
human-readable view, updated whenever an experiment changes state.

**Status values:** `planned` (designed, not scheduled) · `queued` (next to
run) · `running` · `done`.

| ID | Experiment | Status | Scope | Result (short) |
|---|---|---|---|---|
| EXP-1 | DIY vs Tavily, adjudicated | done | FR, 36 pairs | DIY at parity on answerable pairs: not worse 78%, wins 3:1 |
| EXP-2a | Search-knob cost vs quality | queued | FR subset | pending |
| EXP-2b | Search-knob cost vs quality | planned | low-resource countries | pending |
| EXP-3 | DIY vs Tavily, multilingual | planned | RO / EE / HU and other thin-web countries | pending |
| EXP-4 | Brave head-to-head | planned | FR first | pending |
| EXP-5 | Five-provider search A/B | planned | TBD (the parked June plan) | pending |

---

## EXP-1: DIY vs Tavily, adjudicated (done)

SPEC: D29. Harness: `evaluation/diy_vs_tavily.py`. Results file:
`evaluation/results/diy_vs_tavily_20260601_220315.jsonl`.

A blind, position-swapped Opus judge compared DIY and Tavily evidence against
the ODMI gold answer on 36 dimension-stratified French pairs.

Result: DIY 12 wins, 2 ties, 4 losses, 18 both_fail. On the 18 decisive
(web-answerable) pairs DIY was not worse 78% of the time and out-won Tavily 3:1,
leading on every answerable dimension. Half the sample, and all nine Quality
questions, both-failed because the gold answer lives on the deny-listed
data.europa.eu (MQA metric) or is a self-report.

Caveats: n=18 decisive, France only, Tavily basic tier, judge position
consistency 67%. Read the 78% with those attached.

## EXP-2: Search-knob cost vs quality

SPEC: D30. DIY costs five to eight times the Claude calls of Tavily per pair,
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
