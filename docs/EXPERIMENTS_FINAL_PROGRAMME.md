# EXP-31..35 pre-registration: the final-report programme

Registered 2026-07-02, before dispatch (R1). These five experiments are the
remaining evidence the final dissertation needs. Numbers EXP-31 to EXP-35 are
claimed here; any collision with a concurrently minted number follows the D49
reconciliation rule (the programme with run data keeps the number).

Decision context is D57 (held-out exposure voided; fresh headline run). All
five follow the universal rules in `EXPERIMENTS_PROTOCOL.md` (D38 R1-R12).
Everything runs DIY-only (D43) with models pinned per arm. The D47 held-out
eight are touched by EXP-31 alone.

---

## EXP-31 `exp31_frozen_headline_v2` — frozen headline run, all eight held-out countries

**Question.** What does the frozen production architecture score, end to end,
on eight countries it has never been tuned on?

**Why v2.** The original `exp21_frozen_headline` ID is contaminated: a partial
dispatch on 2026-06-24 finalised 301 pairs (FI 143, HR 59, SE 99) on a
pre-freeze config, and `expC_held_neg_licence` (2026-06-27/28) finalised 627
pairs across all eight countries as an A/B arm. D50 excluded the latter from
the neg_licence adoption basis, so no config choice has consumed held-out
outcomes, but "read exactly once" is no longer true. D57 voids all prior
held-out rows for reporting and the report discloses both exposures. EXP-31 is
the single reported headline.

**Design.** Single production configuration, no arms. Dispatched as eight
per-country sub-batches (condition_label = country code) to stay under the
500-pair runaway guard, reliable stratum B first (FI, SE, BE, HR), then
stratum A (BA, MK, ME, BG).

**Sample.** All 143 questions x 8 countries, ~1,144 pairs, ~368 negative golds
(D47 strata: BA/MK/ME/BG low/mid-resource negative-rich; FI/HR/SE/BE
higher-resource).

**Gates (all must land or be formally deferred before dispatch).**
1. EXP-18 (breadth), EXP-19 (verifier search), EXP-20 (chaining) verdicts.
2. EXP-34 retrieval-strategy verdict (EXP-23 produced no Sonnet-usable data).
3. D50 neg_licence adopt-or-defer decision.
4. EXP-28/29 land (model family and pipeline mode are config).
5. ARCHITECTURE.md freeze commit, tagged; models per D56 (`claude-sonnet-5`).
6. SE catalogue route: restore `SE.json` or document web-only routing.
7. Deny-list audit (`check_data_leakage.py`) clean before and after.
8. Resume-from-interruption behaviour verified (the 2026-06-24 attempt died to
   a power event mid-run).
9. **Held-out cache purge.** `search_cache_{serp,fetch,snippet}` for the eight
   held-out countries must read cold before dispatch, or the run silently
   reuses evidence from the voided `exp21_frozen_headline` /
   `expC_held_neg_licence` exposures (same rows this pre-registration already
   discloses as voided for reporting, at C.1 above). Executed 2026-07-13 on
   the canonical DB (backup `data/odmi.db.bak-preheldoutpurge-20260713-153926`):
   3,962 fetch rows, 11,014 SERP rows, 29,104 snippet rows deleted (URL/query
   match against the actual held-out fetched_urls / search_queries_used in
   `phase2_researcher_runs` and `phase2_verifier_runs`), verified zero
   remaining, VACUUM 646MB -> 539MB. **Any other checkout or worktree used to
   dispatch EXP-31 needs its own purge** (or a fresh copy of the purged
   canonical DB) - this is not fixed globally by one DB's purge. `--no-cache`
   (`_READ_DISABLED`, EXP-2) remains the belt-and-braces backstop regardless of
   purge state. See `SNIPPET_PICKER_CACHE_ANALYSIS.md` section 2d/2e for the
   full audit trail and SQL.

**Endpoints (no adoption rule; this is the reported headline).**
Balance-aware per-class recall with Wilson intervals, balanced accuracy,
Youden's J vs the majority-class baseline; three-outcome
commit-accuracy / coverage / false-positive rate with a D37 floor
risk-coverage sweep; stratified by ODMI dimension, resource stratum,
ODMI assessor decision (confirm / complement / change), and answer shape.
Disagreements pass through the D22 staleness-adjudication band and are
reported as a bracket. FM-14 content-leakage fingerprint audit runs over the
committed evidence post-run.

---

## EXP-32 `exp32_model_haiku` — all-Haiku whole-stack cost point

**Question.** What does the cheapest current Anthropic model do to the
cost-quality frontier when the whole stack moves to it?

**Design.** Single arm `haiku_h45`: researcher = verifier = adjudicator =
picker = query-gen = `claude-haiku-4-5-20251001`. Pre-registered control:
EXP-28 `trio_s5` (identical knobs, identical pairs, only the model family
differs). Same encoding pattern as EXP-29: the model contrast is its own
experiment so the one-variable preflight stays honest.

**Sample.** The committed 156-pair dev battery (MT 60 + NL 52 + AL 44,
78 negative golds), warm shared cache as in EXP-28.

**Endpoints.** Balanced accuracy, negative-gold FPR, abstention rate, cost per
pair and cost per committed-correct answer (GBP), wall-clock per pair.
Characterisation for the RQ5 frontier. Adoption rule (declared for
completeness, expected to fail): Haiku takes any role only if balanced
accuracy delta >= -0.02 and negative-gold FP rise <= 2 points.

**Supersedes.** EXP-9 (`model_variants_mt`) is closed as stalled: 21 of ~300
finals, Sonnet 4.6 era, old Malta pair list, pre-D55 transport. Its rows stay
in the DB as audit trail and are excluded from all reporting.

---

## EXP-33 `exp33_model_tiered` — tiered assignment (the D18 hypothesis)

**Question.** Does "cheap generator, expensive checker" hold: can Haiku do the
retrieval-side grunt work while Sonnet 5 keeps the verification quality?

**Design.** Single arm `tiered_h45_s5`: researcher, researcher query-gen and
snippet picker on `claude-haiku-4-5-20251001` (the picker is the largest
single spend line, and it is researcher-side); verifier and adjudicator on
`claude-sonnet-5`. Control: EXP-28 `trio_s5`, same pairs, same knobs.

**Sample.** The 156-pair dev battery, as EXP-32.

**Endpoints and adoption rule.** Adopt tiered as production default only if
cost per committed-correct answer <= 0.6x `trio_s5` AND balanced accuracy
delta >= -0.02 AND negative-gold FP rise <= 2 points. Otherwise it is a
frontier point for RQ5.

**Order.** Runs after EXP-32; if all-Haiku collapses entirely on retrieval
quality, the tiered arm is still informative (the verifier layer sees the
same degraded evidence), but interpret with EXP-32 in hand.

---

## EXP-34 `exp34_retrieval_strategy_s5` — trusted-domain narrow-then-widen verdict, Sonnet 5

**Question.** Is trusted-domain narrowing (SRCH-5/6/7) helping, hurting, or
inert? Re-run of the EXP-23 design on the production model family.

**Why a re-run.** EXP-23 dispatched 2026-06-24 under Sonnet exhaustion with
every role and the picker pinned to Opus 4.6, so it cannot inform the
Sonnet-5 production config (SPEC change log 2026-06-29: "no canonical data").
The narrowing strategy remains the largest production component with no
measured verdict. This is config-changing and therefore blocks the freeze
(EXP-31 gate 2).

**Design.** Identical to EXP-23: three arms, one knob (`--search-strategy`):
`baseline_narrow_then_wide` (production) vs `wide_only` (treatment) vs
`narrow_only` (attribution control, never adopted). All roles and the picker
pinned `claude-sonnet-5`.

**Sample.** The 156-pair dev battery per arm (468 runs).

**Adoption rule (unchanged from EXP-23).** Promote `wide_only` only if it cuts
NL negative-gold FP by >= 5 points AND commit accuracy is non-inferior
(delta >= -0.02). Side-finding rule: a >= 5-point AL candidate-recall lift on
`wide_only` confirms narrowing suppresses thin-web recall. Diagnostic: share
of each arm's FPs whose cited URL hits a trusted domain.

---

## EXP-35 `exp35_self_critique` — single-agent self-verification arm

**Question.** Is the verification layer's value adversarial separation, or
just more reasoning? The examiner probe "why three agents rather than one
self-critiquing agent" is currently only half answered: EXP-28's
`researcher_only` arm removes verification entirely; no arm gives the same
model a self-critique pass.

**Design.** New `pipeline_mode` value `researcher_self_verify` (engineering
precondition: coordinator branch + versioned prompt). One agent answers, then
critiques its own answer under the disprove framing before commit; the D35
abstention retries and D37 0.65 floor are held as in every EXP-28 arm. Single
arm `self_verify_s5`, all knobs and models as EXP-28 `trio_s5`. Controls:
EXP-28 `trio_s5` and `researcher_only_s5`, paired on the same pairs.

**Sample.** The 156-pair dev battery.

**Endpoints.** Balanced accuracy, negative-gold FPR, abstention, cost per
committed-correct answer, all read against the EXP-28 ladder.
Characterisation only; the production trio stays regardless (D45 framing).

**Contingency.** If EXP-28 finds `researcher_only` within noise of `trio`,
EXP-35 is promoted to the report's central exhibit (the verification layer
would need to beat self-critique, not just no-critique, to justify its cost).
If trio dominates clearly, EXP-35 quantifies how much of the gap separation
buys. Either way it is load-bearing for the report's central claim.

---

## What is deliberately not registered

- **EXP-8 (prompt compression / cache / retrieval tightening).** Parked. The
  report's cost story is the EXP-28 ladder + EXP-29/32/33 model frontier +
  the rebuilt cost-surface analysis over live data. One month out, prompt
  compression is an optimisation programme without a report section to feed.
- **Retry-budget and adjudicator-threshold ablations.** Q13 stays open;
  attribution B already characterises the retry loop. Not worth held-out
  budget.
- **Per-layer deny-list catch rates, per-role cost attribution, staleness
  adjudication.** Analyses over existing data, not experiments; tracked in
  the cost/analysis workstream, not here.
