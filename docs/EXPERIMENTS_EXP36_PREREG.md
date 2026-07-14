# EXP-36 preregistration: frozen headline run (the single reported held-out estimate)

Registered before dispatch (R1). This document fixes the design of the headline
run before any held-out pair is finalised, so the reported number cannot be
reverse-fitted. The git commit that adds this file is the pre-registration
record. It replaces and discards EXP-31 (see Provenance).

Decision context: D47 (held-out set), D57 (prior exposure voided), D59 (model
revert), and the July freeze-gate verdicts. Everything runs DIY-only (D43), on
`claude-sonnet-4-6`, with instructions folded into the user turn behind the
CLIProxyAPI cloak (D55/D62). The eight D47 held-out countries are touched by
this run alone.

---

## Provenance: what this discards and why

Two prior identities are void, and both stay in the DB as audit trail only:

- `exp21_frozen_headline` — a 2026-06-24 partial dispatch finalised 301 pairs on
  FI/HR/SE under a pre-freeze config, then died to a power event. Voided by D57.
- `exp31_frozen_headline_v2` — registered 2026-07-02 (D57) as the replacement,
  but its pre-registration pinned a model cut by D59 (2026-07-09), never ran,
  and its design predates the July verdicts. Discarded here.

EXP-36 is a fresh number (Q2, minted 2026-07-13) so the discard is unambiguous
in the registry and the board. `run_id = exp36_frozen_headline`.

The held-out eight have been read before: the exp21 partial (301 finals) and
`expC_held_neg_licence` (627 finals, all eight, 2026-06-27/28). D57 voids both
for reporting and the defensible claim is "no tuning decision consumed held-out
outcomes", not "never read". EXP-36 is the single reported read.

---

## Question

What does the frozen production architecture score, end to end, on eight
countries it was never tuned on? Reported, not tested: there is no arm and no
adoption rule.

---

## The frozen configuration (the decision map)

Every knob, its frozen value, and the decision or experiment that fixed it. This
table is the freeze: the ARCHITECTURE.md tag and the dispatch spec must match it
exactly.

| Knob | Frozen value | Fixed by | Note |
|---|---|---|---|
| Search provider | DIY only (Serper SERP + trafilatura) | D43 | No Tavily, no Brave, no fallback. |
| Researcher model | `claude-sonnet-4-6` | D59 | Model reverted 2026-07-09. |
| Verifier model | `claude-sonnet-4-6` | D59 | |
| Adjudicator model | `claude-sonnet-4-6` | D59 | |
| Snippet-picker model | `claude-sonnet-4-6` | D59 | Picker is the largest single LLM call in a pair; pinned, not left to fall back. |
| Query-generation model | `claude-sonnet-4-6` | D59 | |
| Instruction transport | full prompt folded into the user turn (`<instructions>`), proxy cloak on | D55, D62 | Undisguised Sonnet/Opus is 429'd; cloak stays on. |
| Results per query | 5 | EXP-18 | r10 never confirmed multi-country; keep r5. |
| Queries per attempt | 3 | production default | |
| Query language | bilingual (English + native) | EXP-22, production default | English-only is an ablation; bilingual ships. |
| Max retries | 3 | production default | Retry-divergence limitation disclosed below. |
| Verifier counter-search | always | EXP-19 | `never` inconclusive multi-country; keep `always`. |
| Evidence chaining | off (baseline) | EXP-20 | Chaining failed 2 of 4 promotion conditions. |
| **Search strategy** | **`wide_only`** | **EXP-34** | **The one production flip. Adoption rule met on NL (neg-gold FP 17 to 14 paired, commit-acc 0.62 to 0.67).** |
| Researcher prompt variant | `full` (neg_licence OFF) | D50 | neg_licence deferred, not adopted. |
| Verifier strategy | `disprove` (adversarial flip) | production | |
| Pipeline mode | `trio` (Researcher, Verifier, Adjudicator) | D54 | |
| Snippet picker | on (LLM selects chunks) | production | |
| Abstention floor | commit only at confidence >= 0.65 | D37 | Risk-coverage swept in reporting. |
| Cache | `no_cache: true` (read-disabled) | R9, contamination defence | Held-out cache leakage guard; see Data hygiene. |
| Deny-list | `data.europa.eu` + ODMI path fragments, pre-retrieval | D24, D60 | Applied to every pair. |

## Sample

All 143 questions x 8 held-out countries = 1,144 (question, country) pairs,
about 368 binary negative golds. D47 strata: stratum A (low/mid-resource
language, negative-rich) BA, MK, ME, BG; stratum B (higher-resource) FI, HR, SE,
BE.

## Design

Single production configuration, no arms. Dispatched as eight per-country
sub-batches (`condition_label` = country code) to stay under the 500-pair
runaway guard. Order: stratum B first (FI, SE, BE, HR), then stratum A (BA, MK,
ME, BG), so the more reliable countries finalise before the thin-web ones.

## Endpoints (no adoption rule)

- Balance-aware: per-class recall with Wilson 95% intervals, balanced accuracy,
  Youden's J against the majority-class baseline.
- Three-outcome: commit-accuracy / coverage / negative-gold false-positive rate,
  with a D37 floor risk-coverage sweep.
- Stratified by ODMI dimension, resource stratum, ODMI assessor decision
  (confirm / complement / change), and answer shape.
- Disagreements with ODMI gold pass the D22 staleness band and are reported as a
  bracket (lower bound treats every disagreement as a swarm error, upper bound
  excludes confirmed-stale gold).
- FM-14 content-leakage fingerprint audit over the committed evidence, post-run.

## Resume rule (pre-registered; the exp21 lesson done right)

Runs will be cut off mid-flight (power events, 429s, proxy restarts). The rule
is resume, not restart. What exp21 got wrong was not that it resumed; it was that
it finalised held-out pairs under a pre-freeze config that later changed. The
config here is frozen, so completing the read across interruptions is a single
read.

- Resume at pair granularity. On interruption, re-dispatch the identical EXP-36
  spec against the same dispatch DB. The coordinator resumes from clean,
  committed results only (`_find_resumable_researcher`, run_coordinator.py:705):
  finalised pairs are kept and skipped, and pairs that were failed, inconclusive,
  or in flight are re-run from their last clean stage. No finalised pair is
  re-run or overwritten. Verified by the 38 dispatch/resume tests (gate 8).
- One frozen config across every resume. The spec, the pinned models, and the DB
  `model_defaults` must be identical on every restart. A resume under any changed
  knob voids the run, which is then re-read from scratch under one config. This,
  not the resume, is the exp21 lesson.
- Immutable finals, one run_id. The reported set is every pair finalised under
  `run_id = exp36_frozen_headline`, across however many interruptions it took. It
  is one logical read; a resume reads only the not-yet-read pairs.
- Per-country sub-batches stay the dispatch unit (runaway guard, clean per-country
  attribution); resume operates per pair within and across them.
- A pair that never commits after the retry ceiling is an abstention, counted in
  coverage per D37, not a failure and not a reason to re-read the country.

## Gates (status at 2026-07-13)

1. EXP-18 / EXP-19 / EXP-20 verdicts — LANDED (2026-07-10), no config flip.
2. EXP-34 retrieval-strategy verdict — LANDED (2026-07-13), adopt `wide_only`.
3. D50 neg_licence decision — LANDED, defer, keep `full`.
4. EXP-28 / EXP-29 landed — model family (4.6, D59) and pipeline mode (trio, D54)
   are set; the EXP-29 4.6 battery ran but its rows were lost (D63), which does
   not change the config decisions.
5. ARCHITECTURE.md freeze commit, tagged — PENDING, applied as the last step
   once the fixes below land and the config table above is reflected in the
   ledger.
6. SE catalogue route — DONE (sparql on dataportal.se, D24-compliant).
7. Deny-list audit clean — DONE on the dev battery; re-run on the dispatch DB
   before and after EXP-36.
8. Resume-from-interruption verified — DONE (38 dispatch/resume tests).
9. NEW: coordinator data-integrity fixes B1-B4 land with tests (see Fixes).
10. NEW: paper-trail corrections land (D62 written up; FINAL_PROGRAMME gate 5 and
    the ARCHITECTURE.md stale rows corrected to 4.6 / EXP-18 / EXP-34).

## Fixes carried by this freeze (Q4: fix all four, disclose)

Four data-integrity defects, confirmed present, fixed before dispatch:

- B1 `invalid_answer_shape` did not retry: a shape-invalid Researcher answer was
  carried forward and could commit as junk `differ`. Fixed to retry, and to
  abstain rather than commit junk on exhaustion.
- B2 `schema_invalid` killed answered pairs: a Verifier schema failure on the
  final attempt dropped the pair as `agent_failure` without adjudicating the
  Researcher answer in hand. Fixed to mirror the Researcher-path recovery
  (adjudicate on the answer already produced). EXP-34 itself lost two pairs to
  this bug, so the fix is load-bearing for coverage.
- B3 `_pct(n, 0)` returned the bottom band on an empty denominator: an empty
  catalogue reported "<10%" rather than not-applicable. Fixed.
- B4 dashboard still offered a since-cut model for dispatch: removed from both
  the Run Console and the Models comparison dashboards (D59).

## Disclosures (carried into the write-up)

- Prior held-out exposure (exp21 partial, expC_held), voided per D57. EXP-36 is
  the reported read; the exposure is disclosed.
- `wide_only` is adopted on accuracy grounds: it lifts pooled commit-accuracy
  (0.679 to 0.733 across the NL+MT+AL dev battery) and never regresses any
  country. The negative-gold FP reduction that motivated it (NL, 17 to 14) does
  not generalise at full power (pooled McNemar p=0.727, MT no signal, AL a small
  reverse), so no general FP-reduction claim is made.
- Trusted-domain narrowing is untested on the reported set: the eight held-out
  countries have no trusted-domain lists, so `narrow_then_wide` would be inert on
  them anyway. `wide_only` makes the actual behaviour explicit rather than
  claiming a component the headline never exercises.
- Coordinator version: B1/B2 are fixed for EXP-36, whereas the EXP-18/19/20/34
  verdicts were measured pre-fix. The fixes touch malformed-output edge cases
  only, not the knobs those experiments tested, so the verdicts carry.
- ODMI gold can be one cycle old (D22); a swarm-vs-ODMI disagreement is not
  automatically a swarm error, hence the reported band.

## Data hygiene (cache contamination: primary fix already done)

The 2026-07-13 purge (commit b8a316c) cleared most held-out cache but was
incomplete: a pre-dispatch audit (2026-07-14) found the canonical DB still
carried **892 held-out fetch rows, 112 SERP rows and 202 snippet rows** (the
b8a316c join matched cache to surviving `phase2_*` rows and missed rows whose
originating `phase2_*` row had already been deleted; its "verified 0 fetch
remaining" claim did not hold on this DB). `scripts/purge_heldout_cache.py`
closes the gap: it deletes every cache row that names a held-out country, is
referenced by a held-out `phase2_*` row, or (fetch) sits on a held-out national
ccTLD, and re-scans to prove zero residual across all three layers. It must be
run on the dispatch DB and read `VERIFIED CLEAN` before dispatch. Over-deletion
is harmless: the cache is disposable and the run reads none of it.

- Dispatch from a fresh copy of the canonical DB that has been purged with
  `scripts/purge_heldout_cache.py --apply` and registered with
  `scripts/register_exp36.py`, `model_defaults` at `claude-sonnet-4-6`. This is
  the load-bearing step. Never dispatch from a worktree DB: the unpurged worktree
  copies still carry ~3,950 held-out fetch rows each. Full procedure in
  `docs/EXPERIMENTS_EXP36_DISPATCH_RUNBOOK.md`.
- `no_cache: true` in every sub-batch is defence in depth, not the primary fix.
  It disables cache reads (so no surviving row can be read) but not writes, so the
  run writes fresh held-out cache into its throwaway DB copy. That is why the copy
  is disposable and never committed; the reported finals are exported separately
  (see the runbook), so nothing depends on committing the DB.
- Proxy cloak on and 4.6 authenticated through CLIProxyAPI before dispatch.
- `check_data_leakage.py` (finalised URL rows) clean before and after, plus the
  held-out cache-row scan (the purge script re-scan) on the dispatch DB.

## Budget

`CALLS_PER_PAIR_WORST` was corrected 17 -> 45 on merge (a concurrent fix threaded
`subtrio_id` into the snippet picker, which is ~80% of real call volume and was
previously going uncounted). True worst case is 1,144 pairs x 45 = 51,480 calls;
ceiling raised to 55,000 (the original 25,000, sized against the wrong constant,
would have paused the run mid-flight). Per-country `--max-calls` is
`pairs x 45 + 50` = 6,485.

## Change log

- 2026-07-13: created. Discards EXP-31 (`exp31_frozen_headline_v2`) and mints
  EXP-36. Freezes `search_strategy = wide_only` on the EXP-34 verdict; pins all
  models to `claude-sonnet-4-6` (D59); records the sub-batch-atomic partial-run
  rule; carries the B1-B4 fixes; lists the operational data-hygiene
  preconditions.
