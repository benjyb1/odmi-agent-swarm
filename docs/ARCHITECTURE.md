# Current best architecture

The single living record of what the swarm is configured to do and why. Every
row is one design knob, its current adopted value, and the experiment or numbered
decision that set it. When an experiment lands a verdict, update the row here as
well as in `EXPERIMENTS.md`, so the best-known configuration is always one glance
away rather than reconstructed from the spec, the experiment board, and the
findings docs.

Read this with `SPEC.md` (the full numbered-decision record and rationale) and
`EXPERIMENTS.md` (the per-experiment evidence). This file is the summary view, not
a substitute for either.

**Status vocabulary.** *adopted* = decided and live in production. *kept* = an
experiment tested a change and the incumbent stood. *favoured* = an experiment
points to a better value but production has not been switched yet. *baseline* =
built and validated as a comparison point, not the default. *pending* = under test
or owed.

Last updated 2026-06-23 (after EXP-14, EXP-16, EXP-17 picker/breadth).

## Search and retrieval

| Knob | Current value | Set by | Status |
|---|---|---|---|
| Provider | DIY only (Serper SERP + trafilatura). No Tavily, no Brave, no fallback. | D43 | adopted, closed |
| Snippet picker | on (LLM selects chunks) | EXP-17 picker (off is no cheaper, no better, does not bin the answer) | kept |
| Results per query | 3 (production) | default | adopted |
| ... breadth finding | widen to ~10 | EXP-17 breadth (r10 > r5 on NL) | favoured, not switched |
| Queries per attempt | 3 | default | adopted |
| Page-text cap | 16,000 chars | D29 (extraction-ordering fix) | adopted |
| Max chars per snippet | 600 | default; EXP-17 truncation arm owed | pending |
| Evidence deny-list | ODMI publications + data.europa.eu banned at every layer | D24 | adopted |

## Researcher

| Knob | Current value | Set by | Status |
|---|---|---|---|
| Catalogue routing | computed Quality questions route to the deterministic catalogue tool before web search | D30, D46 | adopted |
| Portal registry | auto-discovered from a committed seed list, not hand-authored | D46 | adopted |
| Prompt | v3, per-shape answer space | D28 | adopted |

## Verifier

| Knob | Current value | Set by | Status |
|---|---|---|---|
| Strategy | disprove (adversarial flip) | D15 | adopted |
| Own counter-search | always (clean DIY each round) | EXP-14 (never holds accuracy but raises false positives) | kept |
| Quote-grounding gate | matcher v2 (per-snippet, ellipsis-aware) | EXP-11 stage 0 / D45 | adopted |
| Tristate verdict / relaxed wiring / richer evidence | not adopted | EXP-11 / EXP-12 / EXP-13 (all null) | kept incumbent |

## Adjudicator

| Knob | Current value | Set by | Status |
|---|---|---|---|
| Candidate selection | standard (researcher_correct / verifier_correct / neither / escalate_human) | EXP-16 (free choice of any attempt gained nothing) | kept |
| Finalisation answer | the Adjudicator's own answer, not the last Researcher output | D32 | adopted |
| Commit-confidence floor | 0.65; abstain (`inconclusive`) below it | D37; confirmed by EXP-10 pooled over 7 countries (n=360, recovered-precision 0.76 at 0.50, under the 0.80 bar) | adopted |

## Retry loop

| Knob | Current value | Set by | Status |
|---|---|---|---|
| Max retries | 3 (proxy-resilience cushion to 8) | default | adopted |
| Retry query divergence | forced to differ from prior queries | D33 | adopted |
| `inconclusive` handling | abstention that retries then adjudicates, not a terminal label | D35 | adopted |
| Evidence chaining across rounds | off | EXP-7 (promising, not proven) | baseline, not default |

## Models

| Knob | Current value | Set by | Status |
|---|---|---|---|
| Researcher / Verifier / Adjudicator | Sonnet (`claude-sonnet-4-6`) | default | adopted |
| Routing | CLIProxyAPI on localhost:8317 (Claude Max), no direct API billing | D1 | adopted |
| Model-variant comparison (Haiku / Opus / tiered / Mistral) | undecided | EXP-9 (status stale, needs re-check / re-run) | pending |

## Coordinator and evaluation

| Knob | Current value | Set by | Status |
|---|---|---|---|
| Orchestration | plain Python state machine, not LangGraph | D3 (amended) | adopted |
| Resume on partial | reuse a committed Researcher row from a dead subtrio | 2026-05-14 | adopted |
| Ground truth | ODMI published answers (`ground_truth` table) | D22 | adopted |
| Reporting | balance-aware + three-outcome (commit-accuracy / coverage / false-positive rate) | D38 (R4), D47 | adopted |
| Dev set | NL, MT, NO, FR, AL | D47 | adopted |
| Held-out eval set (frozen) | BA, MK, ME, BG, FI, HR, SE, BE | D47 | adopted |
| Cost guard | no soft limit; runaway breakers only | D40, D41 | adopted |

## Open levers (what the remaining experiments are still chasing)

- **Search cost/quality** (EXP-2, EXP-8): can the funnel be made cheaper without
  losing recall? Confounded by retries, so judged on calls per pair.
- **Multilingual / thin-web retrieval**: does the DIY pipeline's recall hold up
  off France, on thin-web and low-resource-language countries (AL especially)?
  This is a DIY-internal recall question, not a provider comparison (provider is
  closed: DIY only, D43).
- **Model variants** (EXP-9): how much of the accuracy is the pipeline vs Claude
  specifically (Mistral cross-family arm).
- **Adjudicator ablation** (EXP-15): does the Adjudicator earn its keep under the
  current verifier evidence channel?
- **Selection ceiling** (follow-on to EXP-16): the headroom is real but free
  choice cannot bank it; it needs a better per-attempt signal, not a wider choice
  set.
- **Owed slices:** EXP-14 elective verifier arm, EXP-17 truncation arm, the FR
  candidate-recall read.

A recurring pattern across the verifier and adjudicator programmes (EXP-11/12/13,
EXP-14, EXP-16): the incumbent design keeps winning, and the binding precision
control is the D37 commit floor, not the verifier verdict or the adjudicator's
choice set. The open accuracy gains now look retrieval-side and signal-side, not
reasoning-wiring-side.
