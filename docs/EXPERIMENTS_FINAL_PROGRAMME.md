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
4. EXP-28/29 land. **Status 2026-07-12: neither has landed as pre-registered.**
   EXP-28 has data for only 1 of 3 arms (`trio_s5`, 99 pairs, now a
   superseded-model artefact per D59); EXP-29 never dispatched (0 rows).
   Per D59 the model choice (4.6) is already decided on the `trio_s5`
   coverage-collapse evidence, so this gate is satisfied for the *model*
   question without EXP-28/29 completing; the *pipeline_mode* (architecture
   ablation) question they were meant to answer is still open and does not
   block EXP-31 (production stays `trio` regardless per D45) but does block
   the dissertation's architecture-ablation chapter. Re-run on 4.6 post-freeze.
5. ARCHITECTURE.md freeze commit, tagged; models per D59 (`claude-sonnet-4-6`,
   reverted from D56's `claude-sonnet-5` after the EXP-28 `trio_s5` coverage
   collapse). Transport per D62 (cloak-safe user-turn fold; D61's cloak-off
   path is dead).
6. SE catalogue route: restore `SE.json` or document web-only routing.
7. Deny-list audit (`check_data_leakage.py`) clean before and after.
8. Resume-from-interruption behaviour verified (the 2026-06-24 attempt died to
   a power event mid-run).

**Endpoints (no adoption rule; this is the reported headline).**
Balance-aware per-class recall with Wilson intervals, balanced accuracy,
Youden's J vs the majority-class baseline; three-outcome
commit-accuracy / coverage / false-positive rate with a D37 floor
risk-coverage sweep; stratified by ODMI dimension, resource stratum,
ODMI assessor decision (confirm / complement / change), and answer shape.
Disagreements pass through the D22 staleness-adjudication band and are
reported as a bracket. FM-14 content-leakage fingerprint audit runs over the
committed evidence post-run.

**Mid-run bug and partial-run rule (added 2026-07-12, pre-EXP-31 audit —
this gap had no written rule; D57 was precedent, not a pre-registered
procedure).** The freeze locks a commit SHA (D47); the run is eight
independent per-country sub-batches, so the SHA-lock is enforced per
sub-batch, not only per whole-run.

- **A crash** (rate limit, `auth_unavailable`, infra failure, power event)
  does not void anything. Resume from the same frozen SHA via the existing
  idempotent resume path (skips already-finalised pairs, D58, verified per
  gate 8). No new commit, no new experiment_id.
- **A correctness bug found after some countries have finished but before
  all eight have dispatched:** countries already finalised under the frozen
  SHA are not touched *unless* the bug plausibly affected their correctness
  (not just a crash on later pairs) — if it did, those pairs are voided and
  re-run under the D57 precedent (void for reporting, keep as audit trail,
  fresh id, disclosure paragraph). If the bug only affects not-yet-dispatched
  countries, the fix lands as a new commit, a new SHA is tagged, remaining
  countries dispatch under a new experiment_id suffix (e.g. `_v3`), and the
  report discloses both configurations explicitly (dates, SHAs, what changed
  between them) rather than presenting the merged set as one uniform run —
  the same disclosure discipline D57 already applies to the two pre-freeze
  exposures.
- **A bug found after all eight countries have finalised, before write-up:**
  full D57 treatment — void the affected rows for reporting, keep them as
  audit trail, re-register a fresh experiment_id, fix, re-run, disclose.
- **Partial, permanent stop** (e.g. a hard budget or time cutoff before all
  eight countries finish): the headline is reported on whatever countries
  did complete, explicitly labelled as a partial n with the missing
  countries named and the reason stated — never silently presented as the
  full ~1,144-pair design. This follows the project's existing disclosure
  ethos (D57, the D22 staleness-adjudication stance) rather than inventing a
  new one for this case.

---

## EXP-32 `exp32_model_haiku` — all-Haiku whole-stack cost point

**Question.** What does the cheapest current Anthropic model do to the
cost-quality frontier when the whole stack moves to it?

**Design.** Single arm `haiku_h45`: researcher = verifier = adjudicator =
picker = query-gen = `claude-haiku-4-5-20251001`. Pre-registered control:
originally EXP-28 `trio_s5` (identical knobs, identical pairs, only the model
family differs). **Stale per D59 (2026-07-12 flag):** `trio_s5` is a
collapsed-coverage artefact on a now-cut model, not a valid production
baseline. The control needs a `trio_s46` re-run of EXP-28 (currently 0 rows)
before this comparison means anything; do not compare `haiku_h45` against
`trio_s5` in the report. Same encoding pattern as EXP-29: the model contrast
is its own experiment so the one-variable preflight stays honest.

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

**Design.** Single arm `tiered_h45_s46`: researcher, researcher query-gen and
snippet picker on `claude-haiku-4-5-20251001` (the picker is the largest
single spend line, and it is researcher-side); verifier and adjudicator on
`claude-sonnet-4-6` (re-pinned per D59; the `claude-sonnet-5` original is
void, model cut 2026-07-09). Control: EXP-28 `trio_s46` (needs a 4.6 re-run
first — the existing `trio_s5` has 0 rows on 4.6), same pairs, same knobs.

**Sample.** The 156-pair dev battery, as EXP-32.

**Endpoints and adoption rule.** Adopt tiered as production default only if
cost per committed-correct answer <= 0.6x `trio_s5` AND balanced accuracy
delta >= -0.02 AND negative-gold FP rise <= 2 points. Otherwise it is a
frontier point for RQ5.

**Order.** Runs after EXP-32; if all-Haiku collapses entirely on retrieval
quality, the tiered arm is still informative (the verifier layer sees the
same degraded evidence), but interpret with EXP-32 in hand.

---

## EXP-34 `exp34_retrieval_strategy_s46` — trusted-domain narrow-then-widen verdict, Sonnet 4.6

**Question.** Is trusted-domain narrowing (SRCH-5/6/7) helping, hurting, or
inert? Re-run of the EXP-23 design on the production model family.

**Why a re-run, twice over.** EXP-23 (dispatched 2026-06-24 per the original
plan) has DB rows that don't match that description — 167 `phase2_researcher_runs`
rows under `exp23_narrow_then_widen_nl`, all `claude-sonnet-5`, NL only, dated
2026-07-02 — so whichever record is right, it does not inform the production
config. The first re-run attempt (`exp34_retrieval_strategy_s5`, pinned
Sonnet 5) is itself void: Sonnet 5 was cut 2026-07-09 (D59). **Re-pinned
2026-07-12** to `exp34_retrieval_strategy_s46`
(`evaluation/specs/exp34_pilot_nl_s46.json`, all roles + picker on
`claude-sonnet-4-6`, registered in the `experiments` table). Per the D62 commit
message its diagnostic pilot finalised 20/20 across both arms — the first
working 4.6 data point under the post-D55 transport — though that result is
not yet queryable in every worktree's copy of the DB; verify against canonical
before citing it. The narrowing strategy remains the largest production
component with no measured verdict. This is config-changing and therefore
blocks the freeze (EXP-31 gate 2).

**Design.** Slimmed from EXP-23's three arms to two (`narrow_only` dropped,
never adopted in any prior run): one knob (`--search-strategy`),
`baseline_narrow_then_wide` (production) vs `wide_only` (treatment). All roles
and the picker pinned `claude-sonnet-4-6`. Step 1 runs `nl_pilot10` (10%
behaviour check); if healthy, expands to `nl_pilot24` (25%) via idempotent
resume.

**Sample.** NL only. `nl_pilot10` then `nl_pilot24` (up to 25% of the original
156-pair-per-arm design), not the full multi-country battery.

**Adoption rule (unchanged from EXP-23).** Promote `wide_only` only if it cuts
NL negative-gold FP by >= 5 points AND commit accuracy is non-inferior
(delta >= -0.02). Diagnostic: share of each arm's FPs whose cited URL hits a
trusted domain. **Not testable in the slimmed NL-only pilot:** the original
side-finding rule (a >= 5-point AL candidate-recall lift on `wide_only`
confirms narrowing suppresses thin-web recall) needs the AL arm this re-pin
dropped; defer to a follow-up if the NL result is directional but the
AL-suppression mechanism needs confirming.

---

## EXP-35 `exp35_self_critique` — single-agent self-verification arm

**Question.** Is the verification layer's value adversarial separation, or
just more reasoning? The examiner probe "why three agents rather than one
self-critiquing agent" is currently only half answered: EXP-28's
`researcher_only` arm removes verification entirely; no arm gives the same
model a self-critique pass.

**Design.** New `pipeline_mode` value `researcher_self_verify` (engineering
precondition: coordinator branch + versioned prompt, already built). One agent
answers, then critiques its own answer under the disprove framing before
commit; the D35 abstention retries and D37 0.65 floor are held as in every
EXP-28 arm. Single arm `self_verify_s46` (re-pinned per D59; the built spec
`evaluation/specs/exp35_self_critique.json` still pins `claude-sonnet-5` in
every role field and needs the same 4.6 re-pin as EXP-34 before dispatch).
Controls: EXP-28 `trio_s46` and `researcher_only_s46`, paired on the same
pairs — both currently 0 rows on 4.6, so this experiment is blocked on the
EXP-28 re-run, not just its own re-pin.

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
