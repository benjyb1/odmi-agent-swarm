# EXP-11: Verifier redesign evaluation (pre-registration and runbook)

Drafted 2026-06-10. Numbered EXP-11 because EXP-10 is the Malta failure-mode
audit (`docs/EXPERIMENTS.md`). This file is both the pre-registration and the
runbook: an agent pointed at this file should be able to build, run, analyse,
and report the whole programme without further briefing.

The pre-registration becomes binding at the commit that fills section 5
(FROZEN KNOBS). Until that commit, this is a design draft. After it, any
change is a new dated commit with a line in the change log at the foot of
this file, made before the affected run (universal rule R1,
`docs/EXPERIMENTS_PROTOCOL.md` section 0).

---

## 0. Orientation for the agent running this

Work top to bottom. Each stage has build tasks, run steps, a definition of
done, and a gate. Do not start a stage before the previous stage's gate is
recorded in the change log.

**Read first, in order:**

1. `docs/SPEC.md` status block and decisions D15, D22, D24, D28, D34, D35,
   D37 (D44 is in code at `scripts/run_coordinator.py:366` with no SPEC entry
   yet).
2. `docs/VERIFIER_REDESIGN.md`: the six proposals (P1 to P6) under test here,
   with the full diagnosis and its SQL appendix.
3. `docs/EXPERIMENTS_PROTOCOL.md` section 0: the universal rules R1 to R12.
4. `evaluation/verifier_strategies.py`: the EXP-6 apparatus this experiment
   borrows from. Read it; do not edit it (it is a pre-registered artefact).

**Hard rules. Breaking any of these invalidates the run.**

1. Worktree isolation: if not already in a worktree, call `EnterWorktree`
   before editing anything (CLAUDE.md, branch isolation).
2. Pin every knob. Search provider is `diy` explicitly on every dispatch and
   every freeze; never `auto` (the D36 fallback is a confound; this is a
   standing project rule). Model is the wrapper default (Sonnet) unless a
   knob block below says otherwise. Temperature stays at the wrapper default
   of 0. Cold cache (`--no-cache`) on every dispatch.
3. Stage 1 writes no `phase2_*` rows. Results go to JSONL under
   `evaluation/results/`. Writing `prompt_versions` rows is required (every
   prompt is versioned; receipts standard).
4. Do not edit `evaluation/verifier_strategies.py`, the four existing
   strategy prompts in `agents/prompts/verifier.py`, or `VerifierOutput` in
   `agents/models.py`. Stage 1 is additive code only.
5. Partial runs are reported as partial with the achieved n (R11). No
   selective re-runs to move a number (R12).
6. Coordinate before dispatching: EXP-9 (model variants) is running on Malta
   with pinned knobs. Do not run EXP-11 dispatches concurrently with EXP-9
   arms; latency endpoints contaminate under contention (see the EXP-9 row
   in `docs/EXPERIMENTS.md`). Ask Benjy if unsure what is in flight.
7. Selection happens on the development strata only (Malta, Norway). The
   Netherlands confirmatory set is analysed once, for one pre-registered
   comparison. If the confirmatory test fails, the answer is no; do not
   iterate against NL.
8. `data/odmi.db` is tracked with Git LFS. Do not commit DB changes in
   experiment commits unless explicitly instructed.
9. UK English, no em dashes, plain register, the full CLAUDE.md
   writing-style block, in every artefact this work produces.
10. Commit small and often. The freeze commit (section 5) must predate the
    first stage 1 LLM call (R1).

**First action: verify the state.** Run the SQL in Appendix A. Expected
values as of 2026-06-10: MT 60 questions / 152 disprove rows; NO 143
questions / 211 disprove rows; NL 3 questions (the pinned re-dispatch has not
landed); FR 130 questions; `experiments` registry contains
`verifier_strategy_disc_v1` only. If the numbers have moved, note the deltas
in the change log; the design holds unless a pool this experiment depends on
has shrunk.

---

## 1. What is being tested

The Verifier's `disprove` default does not discriminate correctness. On the
joined Malta set (n = 114): P(pass | correct) = 0.571 vs P(pass | wrong) =
0.432, Fisher p = 0.23; but P(pass | yes-claim) = 0.368 vs P(pass | no-claim)
= 0.605, p = 0.028. The verdict sorts by claim direction, not truth. False
fails are mostly evidence-fit complaints on correct answers; the Verifier's
own counter-quote is never checked against anything; the substring gate
passes junction-stitched quotes and fails legitimate elisions; and the D37
floor, not the Verifier, controls commits (only 18 of 94 golded Malta pairs
commit in-loop; 12 of the 16 correct in-loop commits sit in [0.65, 0.75)).
Full diagnosis with SQL: `docs/VERIFIER_REDESIGN.md` section 1.

The redesign proposals, and the evaluation channel each belongs to:

| # | Proposal | What it changes | Evaluated by |
|---|---|---|---|
| P1 | Tristate verdict (`refute` / `inconclusive` / `confirm`) with deterministically gated extremes | Prompt vocabulary (live); gates are post-processing | Stage 1 arms + analysis toggles |
| P2 | Symmetric burden: confirmation probes for absence claims, machine-set `absence_corroborated` | The evidence the model sees | Stage 1 arm D |
| P3 | Absence commit policy: receipts check, confidence ceiling, corroborated route | Pure arithmetic over stored fields, plus one Researcher-side validator | Stage 0 replay (ceiling); stage 2 (receipts) |
| P4 | Quote integrity v2: per-snippet, ellipsis-fragment matcher with provenance | Deterministic matcher | Stage 0 replay; ships as a bug fix |
| P5 | Ordered shapes: verified figure mapped to band in code | Deterministic overlay | Stage 1 analysis column, band stratum only |
| P6 | `verifier_confidence` demoted to telemetry | Nothing (it already gates nothing) | Code audit only |

---

## 2. Design overview

**Why not a factorial.** Six proposals naively give 64 cells. But only
changes to what the model sees need LLM calls; everything deterministic
(gates, matcher, policy arithmetic, band mapping) is a function of stored
outputs and can be toggled in analysis at zero cost. The dependency
structure also makes most cells incoherent: P2's flag needs P1's vocabulary;
P3's corroborated route needs P2's probes. The meaningful space is a ladder,
plus one off-ladder cell (the refute gate applied to the incumbent's binary
fails), all of which is covered by three live arms and analysis columns.

**The combination space actually searched:**
{A, A-gated, B-ungated, B-gated, D-ungated, D-gated} x the frozen commit
policy. Selection on the development strata; one confirmatory comparison on
NL; robustness direction checks on the FR injected set.

**Stages and gates:**

- Stage 0 (free, offline replays): ship P4 on its own receipt; freeze the
  policy knobs; measure the receipts-check burden. Gate: knobs committed.
- Stage 1 (EXP-11a, classifier ladder, frozen evidence): attribute the
  effect of vocabulary, gates, and probes; select the package; confirm once
  on NL. Gate: the adoption rule in 6.7.
- Stage 2 (EXP-11b, end-to-end paired dispatch on an untouched country):
  loop dynamics, the receipts validator, the D45 decision.

---

## 3. Stage 0: offline replays, no LLM calls

### S0.1 Matcher v2 and its replay (P4)

**Build.**

- `agents/tools/substring.py`: add `contains_v2(snippets: list[str], needle:
  str) -> MatchResult` alongside the untouched `contains`. Semantics: split
  the needle on ellipsis markers (`...`, `[...]`, `…`); every fragment must
  be at least 15 normalised characters; all fragments must match within the
  SAME snippet, in order. Return which snippet index matched (provenance) or
  why not (`no_match` / `fragment_too_short` / `cross_snippet_only`, where
  the last means v1 would have matched the joined corpus but no single
  snippet contains all fragments). Unit tests in `tests/test_substring_v2.py`
  covering: junction-stitch rejected, within-snippet elision accepted, short
  fragment rejected, order violation rejected, NFKC cases from the existing
  v1 tests.
- `evaluation/replay_substring_v2.py`: replay v1 and v2 over (a) every
  `phase2_researcher_runs.evidence_quote` against its own `search_snippets`,
  and (b) every `phase2_verifier_runs.counter_evidence_quote` against the
  verifier's `independent_evidence` plus the researcher's snippets. Join to
  `ground_truth` for correctness. Output:
  `evaluation/results/substring_v2_replay.jsonl` plus a printed flip matrix
  (v1 pass / v2 fail and vice versa) split by researcher-answer correctness.

**Run.** `uv run python evaluation/replay_substring_v2.py`

**Definition of done.** Flip matrix printed; 10 flips in each direction
hand-audited (read the quote and the snippets; classify the flip as
junction-stitch caught, elision released, short-fragment caught, or
unexplained).

**Decision rule.** P4 ships to production (wire `contains_v2` into
`_run_substring_check`, `agents/verifier.py:139`, snippet path only) iff
every audited flip is explainable and no v1-fail/v2-pass flip admits a quote
that is absent from every individual snippet. Ship as its own commit with a
SPEC change-log line, in the D34 pattern. If unexplained flips appear, stop
and report; do not proceed to stage 1 with a matcher you cannot explain.

### S0.2 Commit-policy grid (P3 arithmetic)

**Build.** `evaluation/replay_commit_policy.py`: over the stored MT and NO
trails, for each finalised pair recompute the in-loop commit decision per
attempt under policy variants, holding the stored verdicts, answers, and
confidences fixed. Policy parameters:

- `FLOOR` = 0.65, fixed (D37; not on the grid).
- `ABSENCE_CEILING` in {0.70, 0.75, 0.80}: minimum confidence to commit an
  absence-class answer (binary `no`, `none`, bottom band) absent
  corroboration.
- The corroborated route cannot be replayed (no `absence_corroborated` in
  stored data); it is fixed structurally at `FLOOR` and measured in stage 1.

Endpoints per cell, per country: simulated committed-wrong rate, committed-
correct rate, abstain-or-retry rate, against the incumbent policy's replay
on the same rows. Honest limitation, printed in the output: this replay sees
single attempts, not retry recovery or the Adjudicator.

**Run.** `uv run python evaluation/replay_commit_policy.py`

**Decision rule (freezes the ceiling).** Choose the ABSENCE_CEILING with the
lowest committed-wrong on both MT and NO subject to the abstain-or-retry
rate rising no more than 5 points over the incumbent on either. Ties break
to 0.75. Write the choice into section 5.

**Interaction with EXP-10.** EXP-10 Phase B
(`docs/EXPERIMENTS_MALTA_FAILURES.md`) sweeps the D37 floor itself (0.65 /
0.55 / 0.50) on the same stored confidences. If EXP-10 has adopted a new
floor by the time S0.2 runs, use that floor as the fixed FLOOR here and grid
the ceiling above it; if S0.2 runs first, EXP-10 inherits the frozen
ceiling. The two knob decisions must not be made independently; check the
EXP-10 row in `docs/EXPERIMENTS.md` before freezing.

### S0.3 Absence receipts shadow replay (P3 lock 1)

**Build.** `evaluation/replay_absence_receipts.py`: over every stored
researcher row with an absence-class answer, run the deterministic receipts
check: at least `RECEIPTS_N` distinct entries in `search_queries_used`
naming the country, the portal domain, or the question's subject term.
Report the flag rate split by correctness (join to gold), at N in {2, 3, 4}.

**Decision rule.** Pick the largest N whose flag rate on CORRECT absence
answers is at most 10%. Write into section 5. This check gates nothing until
stage 2; the replay measures the retry burden it would add.

### S0.4 P6 audit

Grep audit that `verifier_confidence` reaches no decision path
(`scripts/run_coordinator.py:878` reads the Researcher's confidence; confirm
nothing else branches on the Verifier's). Record one paragraph in the run
log. No run.

## 4. Stage 0 gate

P4 shipped or stopped-with-report; section 5 fields filled; all three
replay JSONLs in `evaluation/results/`; change-log line added. Commit. That
commit is the binding pre-registration for stages 1 and 2.

---

## 5. FROZEN KNOBS (frozen at the stage 0 gate)

```
FROZEN 2026-06-10 (this commit). Stage 0 replays run; values fixed before
any stage 1 LLM call.

ABSENCE_CEILING        = 0.65  # == FLOOR, i.e. NO special ceiling. S0.2
                               # showed a higher ceiling is net-negative on
                               # dev (see below). P3 lock 3 is DROPPED.
RECEIPTS_N             = 2     # per the S0.3 rule, but lock 1 is PARKED, not
                               # shipped: at N=2 it flags ~nothing (queries
                               # already name the country); only the deferred
                               # subject-term matcher would have teeth.
UPLIFT_U               = 0.00  # fixed for stage 1; 0.10 is the stage 2
                               # candidate, armed only if confirm-precision
                               # >= 0.85 on DEV in stage 1 (n_confirm >= 20,
                               # else the uplift decision defers to stage 2)
MATCHER                = v2 (SHIPPED to production this commit); v1 recorded
                         per candidate in stage 1
PROVIDER               = diy (Serper), --no-cache, never auto
MODEL                  = wrapper default (Sonnet), identical across arms
SEED                   = 20260610 (any stratified draw in this experiment)
CANDIDATE_FILE         = evaluation/results/exp11_candidates.json (frozen
                         IDs written before the first arm call; R3)
```

Selection and confirmatory rules are already fixed in 6.7 and are part of
the freeze.

### Stage 0 results (2026-06-10)

Three offline replays, all read-only, JSONL in `evaluation/results/`.

**S0.1 matcher v2 -> SHIP (done, wired into `agents/verifier.py:139`).**
`evaluation/replay_substring_v2.py` over 639 researcher quotes and 306
verifier counter-quotes. On the researcher path (the gate that ships) v2
rejects nothing v1 passed, and newly admits 8 quotes v1 was wrongly failing,
all within-snippet ellipsis elisions (4 on correct answers, rescued from a
false hard fail; 4 faithful-but-wrong, which the verdict logic handles), zero
cross-snippet splices. On the verifier path v2 catches 1 junction-stitch
splice (`cross_snippet_only`) that v1 waved through, on a correct answer.
Two cases hand-audited against raw snippets (PT4 MT: fragments at offsets 0
and 413 of one snippet, a real elision; PT41 NO: a quote in no single snippet
but present across the join, a true splice). Ship rule met: every flip
explainable, no v2 pass admits a quote absent from every individual snippet
(true by construction). 13 new unit tests in `tests/test_substring_v2.py`,
the 4 pinned gate tests still pass.

**S0.2 absence ceiling -> DROP (freeze at floor).**
`evaluation/replay_commit_policy.py`, (pair, attempt) grain, MT+NO. Raising
the absence ceiling is net-negative: on Malta a 0.70 ceiling defers 7 of 8
absence commits and all 7 are CORRECT (zero wrong caught), because Malta's
correct `no` answers commit in the 0.65-0.70 band; the 2 Malta committed-wrong
are not even absence-class. Norway has only 5 absence commits, so the lever
barely moves (committed-wrong 9 -> 7 at a cost of 1-2 correct). No ceiling
clears the 5-point deferral bar on both countries. Conclusion: the blanket
confidence ceiling destroys correct absence answers to catch almost no wrong
ones. Absence precision must come from the corroboration route (P2,
`absence_corroborated`), measured live in stage 1, not from a confidence
ceiling.

**S0.3 absence receipts -> PARK lock 1 as specified.**
`evaluation/replay_absence_receipts.py`, 122 absence answers (MT 78, NO 44).
Every Malta absence answer carries exactly 3 country/portal-targeted queries
(the country is in the search template), so the country-naming check is
near-inert: N=2 flags 1.6% of correct and 0% of wrong (catches nothing); N=3
discriminates (wrong 23% vs correct 11%) but breaches the 10%-correct bar.
RECEIPTS_N is frozen at 2 per the rule, but lock 1 is not wired into stage 2:
"did you search the country" is always yes, so the under-search signal needs
the deferred subject-term matcher to be worth anything.

**P6 audit -> confirmed.** `verifier_confidence` is written to the DB,
printed in one log line, and shown to the Adjudicator as prose. No
`if`/`>=`/threshold branches on it anywhere in `scripts/run_coordinator.py`
or the adjudicator. It gates nothing today; under the redesign it stays as
stored telemetry. No experiment needed.

**Net effect on the stage 1 design.** P4 is now production. P3 collapses to
the corroboration route alone (the ceiling and the receipts lock are both
parked on dev evidence), which sharpens the stage 1 question: does the P2
confirmation channel earn its place, given that neither static absence lock
survived contact with the data? Arms and endpoints in section 6 are
unchanged; the absence-policy simulation in 6.7 now compares the corroborated
route against the floor alone, not against a ceiling.

---

## 6. Stage 1 (EXP-11a): the classifier ladder

### 6.1 Prerequisites

1. Stage 0 gate passed; P4 in production.
2. **Tristate built (additive only, no DB migration).**
   - `agents/models.py`: new `VerifierOutputTristate` model. Fields as
     `VerifierOutput` except: `verdict: Literal["refute", "inconclusive",
     "confirm"]`; `counter_*` and `rejection_reason` required iff
     `refute`; new `corroborating_quote: str | None` and
     `corroborating_url: AnyHttpUrl | None` required iff `confirm`; new
     `probe_findings: list[ProbeFinding] | None` (per probe: `query`,
     `found: bool`, `quote: str | None`). `VerifierOutput` untouched.
   - `agents/prompts/verifier.py` (additive): two new strategy specs
     registered in `prompt_versions` via the existing pattern.
     `verifier-tristate` v1: the tristate vocabulary and verdict rules
     (refute needs counter-evidence you can quote from the search results;
     confirm needs corroboration you can quote from a source other than the
     Researcher's; otherwise inconclusive, which is the honest default and
     carries no penalty; evidence-fit complaints are inconclusive, not
     refute). `verifier-tristate-probes` v1: the same plus the absence
     protocol (for an absence claim, work through the supplied probe
     results for the presence proposition; report per-probe findings;
     refute only on a quotable verified presence; confirm only on a
     quotable explicit negative). Extend the `VerifierStrategy` Literal
     with the two labels (type-level only; the DB CHECK at
     `scripts/setup_sqlite.py:187` is untouched because stage 1 writes no
     verifier rows).
   - Query-gen v3 (additive function beside
     `generate_adversarial_queries`, `agents/verifier.py:111`): for
     absence claims emit 4 probes (portal feature page; API or developer
     documentation; official policy register or legal gazette; a
     national-language probe of the presence proposition). For presence
     claims emit the standard adversarial set.
   - Unit tests for the new model validators and the probe query-gen
     message builder.
3. **NL dispatch (EXP-11 owns it; EXP-6 is parked).** Check Appendix A; if
   NL still holds ~3 questions, dispatch the committed 71-question set
   (`data/questions/exp6_question_set.json`) for NL via
   `scripts/dispatch_exp6_clean.py` with `--provider diy --no-cache`,
   NL-only if the script supports country selection (read it first; it was
   built for the NL+FR clean dispatch). Confirm EXP-9 is not mid-run first
   (hard rule 6). The FR side of that script is NOT needed:
   the robustness arm uses the committed
   `data/questions/fr_augmented_eval_pairs.json` over existing FR rows.
4. **Registry (D27).** Insert `experiment_id = 'verifier_tristate_v1'` into
   the `experiments` table with the conditions JSON naming the arms, before
   the first call.

### 6.2 Arms and analysis columns

Live arms (one main call per candidate per arm, paired, frozen evidence):

| Arm | Strategy prompt | Evidence seen | Status |
|---|---|---|---|
| A | `verifier-disprove` v3 (incumbent, untouched) | adversarial block | required |
| B | `verifier-tristate` v1 | adversarial block (same as A) | required |
| D | `verifier-tristate-probes` v1 | adversarial + probe results | required |
| E | `verifier-blind` v3 | adversarial block | run unless quota is tight; gates nothing; informs the D15 narrative |

Analysis columns derived at zero cost from the stored arm outputs:

- `A-gated`: A's `fail` downgraded to `pass` unless the counter-quote
  passes `contains_v2` against the frozen snippets (verifier's plus
  researcher's), or the substring gate failed (which stays a hard fail).
- `B-gated`, `D-gated`: `refute` downgraded to `inconclusive` unless the
  counter-quote verifies as above; `confirm` downgraded to `inconclusive`
  unless the corroborating quote verifies against the verifier-side frozen
  snippets AND its matched snippet's URL differs from the Researcher's
  `source_url`.
- `absence_corroborated` (D only): true iff every probe ran, all
  `probe_findings.found` are false, and no nominated presence quote
  verifies. Computed in Python from stored fields.
- P5 overlay (D, band questions only): parse a numeric figure from the
  verified quote, map to band deterministically, recompute the verdict.
  Exploratory; reported on the band stratum only.
- Policy simulation under section 5 knobs, per column: would this candidate
  commit, and is the committed answer right?

### 6.3 Evidence freeze (extension of the EXP-6 pattern)

Per candidate, exactly once, before any arm call:

1. Substring check of the Researcher's quote against its own snippets,
   computed under BOTH matchers; v2 is what arms consume, v1 is recorded.
2. Adversarial query-gen (the production generator), then search, pinned
   `diy`, no cache.
3. Probe query-gen v3, then search, same pinning. Empty results recorded as
   empty (that is itself data for `absence_corroborated`).
4. Freeze `(substring_v1, substring_v2, adversarial_queries,
   adversarial_snippets, probe_queries, probe_snippets)` into the results
   JSONL. Arms A, B, E see the adversarial block only; D sees adversarial
   plus probes. Snippets carry their URLs (needed for the confirm gate;
   note the production formatter drops URLs, `agents/verifier.py:467`, so
   the harness must keep its own URL-bearing structure).

### 6.4 Candidates

A candidate is the latest researcher run per (question_id, country_code)
with a definite answer (not `inconclusive` / `not_applicable`), non-empty
gold, and stored `search_snippets`; it carries the quote, URL, confidences,
and snippets. Mirror the EXP-6 builder (`evaluation/verifier_strategies.py`
`build_candidates`, `_label`, `_researcher_output`); import the pure pieces
or copy with a provenance comment; do not edit the original.

Strata (roles recorded per candidate):

- `DEV-MT`: all natural Malta candidates. Burned by the diagnosis; dev only.
- `DEV-NO`: all natural Norway candidates. Lightly burned by the D44 replay;
  dev only; covers the yes-heavy regime.
- `PRIMARY-NL`: all natural NL candidates from the 6.1 dispatch. Touched by
  no prior analysis; the confirmatory set.
- `ROB-FR`: the committed FR augmented 50%-flip set
  (`data/questions/fr_augmented_eval_pairs.json`), labels by construction.

Labelling: `should_pass` iff the candidate answer matches gold under the
`_MATCH_STATUS_SQL` logic (exact / yes-prefix on binary / no=no);
adjacent-band misses are `should_fail` (consistent with EXP-6 section 2).
Write all candidate IDs and roles to `CANDIDATE_FILE` before the first arm
call (R3).

### 6.5 Build: the harness

`evaluation/verifier_redesign.py`, mirroring `verifier_strategies.py`
conventions: `--limit N` smoke mode, `--analyse-only PATH`, resumable JSONL
streaming keyed by (candidate_id, arm), one freeze per candidate shared
across arms. Each JSONL record: candidate id, role, question, country,
researcher answer and confidences, gold, label, frozen evidence block, arm,
raw model output, parsed verdict, gated verdict per column, verification
details (which snippet matched, which URL), `absence_corroborated`, policy
simulation result, tokens, wall clock.

### 6.6 Run

```bash
uv run python evaluation/verifier_redesign.py --limit 6     # smoke
uv run python evaluation/verifier_redesign.py               # full
uv run python evaluation/verifier_redesign.py --analyse-only \
    evaluation/results/verifier_redesign_verifier_tristate_v1.jsonl
```

Cost estimate: ~290 candidates (MT ~50, NO ~116, NL ~65, FR-aug 60) x 3 to 4
main calls, plus 2 query-gen calls and 3 to 7 Serper queries per candidate.
Roughly 900 to 1,200 main calls and 1,200 to 1,500 Serper queries. Check
Serper credits before starting; the run streams and resumes, so an
interruption loses nothing.

### 6.7 Analysis, selection, confirmation (all fixed here)

Per column (A, A-gated, B-ungated, B-gated, D-ungated, D-gated), per
stratum: binarise tristate verdicts as `refute` = fail, {`confirm`,
`inconclusive`} = pass. Report:

- Youden's J (primary), MCC, balanced accuracy; catch rate and
  false-rejection rate with Wilson 95% intervals.
- Verdict distribution (degeneracy check: each tristate category at least
  5% on DEV, or the column is flagged degenerate and excluded from
  selection).
- Pass rate by claim direction and the yes/no gap with CI (the asymmetry
  endpoint; the incumbent's gap is 0.368 vs 0.605).
- Confirm-precision: P(candidate correct | gated confirm) with CI. This
  arms or disarms UPLIFT_U for stage 2 (section 5).
- Policy simulation: simulated committed-wrong, committed-correct,
  abstain-or-retry, under the frozen knobs.

**Attribution ladder (DEV strata, MT+NO natural combined).** Four planned
comparisons, exact McNemar on the paired verdict-correctness indicator,
Holm-corrected as a family of four:

1. A vs A-gated (do gates alone rescue disprove?)
2. A vs B-ungated (does vocabulary alone fix the asymmetry?)
3. B-ungated vs B-gated (what do gates add under tristate?)
4. B-gated vs D-gated (what do probes add? also reported on the no-claim
   stratum alone, where the contrast is concentrated)

**Selection rule.** The package = argmax J on DEV natural candidates over
the six non-degenerate columns, subject to: simulated committed-wrong <= A's
on DEV, and verdict non-degeneracy. Record the chosen package in the change
log before touching NL data.

**Confirmatory test (NL, analysed once).** One comparison: package vs A on
PRIMARY-NL. Adopt the package as the production default iff ALL of:

- (i) J_package > J_A with exact McNemar p < 0.05 on verdict-correctness
  (single planned comparison; no correction);
- (ii) false-rejection rate (package) <= false-rejection rate (A), point
  estimates, both reported with Wilson CIs;
- (iii) simulated committed-wrong (package) <= (A) on NL;
- (iv) J_package >= J_A as a point estimate on ROB-FR.

**Recall escape clause.** If (i) fails but J_package >= J_A - 0.05 and (ii)
to (iv) hold, adopt iff the simulated abstain-or-retry rate on NL is at
least 5 points lower than A's.

**If nothing passes.** The incumbent stays, the null is the reported
finding (R12), and stage 2 does not run. Any redesign-v2 needs a fresh
confirmatory pool (NL is then burned).

### 6.8 Outputs and gate

Results JSONL plus a summary block printed by `--analyse-only`; a row update
in `docs/EXPERIMENTS.md`; the stage gate (package chosen, confirmatory
verdict, uplift armed or not) recorded in this file's change log. Gate to
stage 2: the adoption rule or the escape clause passed.

---

## 7. Stage 2 (EXP-11b): end-to-end paired dispatch

The classifier cannot see retry dynamics, feedback quality, what reaches
the Adjudicator, or the Researcher-side receipts check. Stage 2 is the
final gate before D45.

### 7.1 Build (production wiring, flag-gated)

- DB migration: widen the `verdict` CHECK (`scripts/setup_sqlite.py:196`)
  to admit `refute` / `confirm` / `inconclusive` (old rows keep
  `pass`/`fail`); add the two strategy labels to the `strategy_label`
  CHECK (`:187`); add `corroborating_quote`, `corroborating_url`,
  `absence_corroborated`, and a JSON `independent_evidence_urls` column so
  the Verifier row keeps per-snippet URLs.
- Coordinator `--tristate` flag, default off, in the EXP-7 `--chained`
  pattern: with the flag off, the loop is byte-identical to production.
  With it on: tristate strategy, gates, the section 5 commit policy via a
  pure `_commit_decision(verdict, answer, confidence, flags)` replacing
  `_should_accept_verifier_pass` on that path
  (`scripts/run_coordinator.py:878`), refute feedback carrying the verified
  counter-evidence, and `inconclusive` not forcing a retry (sub-floor
  answers still retry on the existing floor-feedback rule).
- Researcher receipts validator (P3 lock 1) behind the same flag, with
  `RECEIPTS_N` from section 5.
- Unit tests for `_commit_decision` and the migration.

### 7.2 Country and sample (rule fixed now)

Selection rule: the untouched country (zero `phase2_*` rows) with the
highest binary no-share whose official language is high-resource. As of
2026-06-10 that is **Sweden** (no-share 0.22, 27 no-gold binary). Bulgaria
(0.41, mid-resource) is the optional harder secondary if quota allows,
reported separately. Re-run the Appendix A pool query at execution time; if
Sweden has been touched since, apply the rule to what remains and log it.

Sample: all SE no-gold binary questions (27) + 27 yes-gold binary drawn
dimension-stratified with SEED + every band/ordinal/count question with a
definite gold (<= 17). Roughly 65 to 70 pairs. Build
`scripts/build_se_eval_pairs.py` in the pattern of
`scripts/build_nl_eval_pairs.py`; commit the pair list JSON before
dispatch.

### 7.3 Dispatch

Both arms run the identical pair list, sequentially (not interleaved with
other experiments), pinned `diy`, `--no-cache`, same models:

- Arm BASE: production defaults at a named commit, `--tristate` off.
- Arm TRI: identical plus `--tristate`.

If chaining (EXP-7) has become the production default by then, both arms
inherit it; only the flag varies. `experiment_id = 'verifier_tristate_e2e_v1'`,
one batch id per arm. These runs DO write `phase2_*` rows, tagged, so the
headline dashboards (untagged baseline queries) stay clean; verify the
dashboard filters before dispatch.

### 7.4 Endpoints and the D45 decision

Per pair, the final outcome category via `_MATCH_STATUS_SQL` (match /
near_match / abstained / differ / failure), where `differ` on a committed
answer is the committed-wrong event. Endpoints: paired McNemar on
match-vs-not and on committed-wrong-vs-not; abstention rate; retry count;
adjudicator-involvement rate; cost per pair with retries counted (R9).

**Adopt as D45 iff:** committed-wrong (TRI) <= committed-wrong (BASE), AND
at least one of match rate up or abstention rate down with exact McNemar
p < 0.05 on the paired per-pair outcome. Otherwise the incumbent stays and
the null is reported. Either way: SPEC change-log entry, a D45 entry on
adoption, `docs/EXPERIMENTS.md` row updated, and the dissertation numbers
filed as bullet-point facts (report-facts convention), not prose.

---

## 8. Interpretation guide

| Pattern in the results | Conclusion | Action |
|---|---|---|
| A-gated ~ A, B-ungated > A | The vocabulary does the work | Package is B-or-D family; keep gates anyway (deterministic, cheap, auditable) |
| A-gated > A, B-gated ~ A-gated | The gates do the work | The minimal package (gate the incumbent) is a legitimate selection; the ladder allows it |
| D-gated > B-gated on no-claims | The probe channel earns its cost | Package includes P2; absence policy uses the corroborated route |
| D-gated ~ B-gated everywhere | Probes add nothing | Drop P2; absence policy rests on the ceiling alone |
| Any tristate column with inconclusive > 90% on DEV | Vocabulary collapse (the D28 lesson) | Column is degenerate; excluded by rule; fall back to best non-degenerate |
| Confirm-precision < 0.85 or n_confirm < 20 | The confirm channel is not trustworthy yet | UPLIFT_U stays 0; recall claims rest on fewer false fails only |
| Strong DEV, failed NL confirmatory | Overfit to burned sets | Report the null; do not iterate on NL (hard rule 7) |
| Stage 1 passed, stage 2 committed-wrong rises | The classifier missed loop dynamics | Do not adopt; report; the discrepancy is itself a dissertation finding |
| Yes/no pass-rate gap shrinks but J flat | Symmetry fixed without discrimination gained | Honest partial win; report both; adoption rides the J rule, not the gap |

---

## 9. Threats and controls

| Threat | Control |
|---|---|
| Adaptive selection contaminates the headline | Dev/confirmatory split; NL analysed once for one comparison; selection recorded before NL is touched |
| MT and NO are burned (diagnosis; D44 replay) | Used as dev only, stated in every report |
| Arm D sees more evidence than B | That is the treatment (protocol + evidence as one component), stated; B vs D is attribution, not a purity claim |
| Matcher change confounds arm A vs history | P4 ships first; all arms consume v2; v1 recorded per candidate so the gate effect is separable |
| Search luck varies between arms | One freeze per candidate shared across arms (R2); pinned provider, cold cache |
| Quota dies mid-run | JSONL streams and resumes; partial reported as partial (R11) |
| Concurrent experiments collide (the EXP-6 / Malta-v2 lesson) | Candidate IDs frozen to file before the run; no concurrent dispatch with EXP-9; coordinate via the tracker |
| ODMI gold staleness (D22) | A natural should_fail may be a stale gold; ROB-FR injected flips are wrong by construction; both natural-only and injected J reported |
| Class base rates flatter always-pass | J / MCC / balanced accuracy headline; pass rate per column shown; NL is R4-viable (21% no-share) |
| Prompt-authoring bias (tristate written by the proposer) | The gates are deterministic; the ungated columns expose the prompt's unaided behaviour; null is reportable |

---

## 10. Compliance with the universal rules

R1 freeze commit before data; R2 paired arms on identical candidates with
shared frozen evidence; R3 seeded draws, IDs written to file; R4 NL primary
(21% no-share), MT/NO dev cover both regimes; R5 not applicable (no LLM
judge; gold is ODMI); R6 not applicable for stage 1 (no judge), noted as
future work for cross-family verification; R7 the B-vs-D confound is broken
by design into ladder rungs and the residual stated; R8 statistics fixed in
6.7; R9 cost per item with retries in stage 2; R10 deny-list untouched and
identical across arms; R11 fixed sample, no peek-and-extend; R12 nulls
reported, drops logged, receipts kept (raw outputs in the JSONL).

---

## 11. Reporting and archival

- Stage results: `evaluation/results/substring_v2_replay.jsonl`,
  `commit_policy_grid.jsonl`, `absence_receipts_replay.jsonl`,
  `verifier_redesign_verifier_tristate_v1.jsonl`, stage 2 rows in
  `phase2_*` tagged `verifier_tristate_e2e_v1`.
- `docs/EXPERIMENTS.md`: EXP-11 row kept current at every gate.
- `docs/SPEC.md`: change-log lines at P4 ship and at each stage gate; a D45
  entry only on stage 2 adoption.
- This file's change log: every gate decision, every deviation, dated.
- Dissertation material: numbers as bullets, never paste-ready prose.

---

## Appendix A: state-check SQL

```sql
-- Pools (expected 2026-06-10: NO 143, FR 130, MT 60, EE 16, NL 3, DE 3, RO 2)
SELECT country_code, COUNT(DISTINCT question_id)
FROM phase2_researcher_runs GROUP BY 1 ORDER BY 2 DESC;

-- NL dispatch landed? (needs ~65+ to proceed; 3 means not yet)
SELECT COUNT(DISTINCT question_id) FROM phase2_researcher_runs
WHERE country_code='NL';

-- Registry
SELECT experiment_id, status FROM experiments;

-- Natural-error counts per dev country (definite answer, gold present)
SELECT r.country_code,
       SUM(CASE WHEN REPLACE(LOWER(TRIM(r.answer)),'_',' ')
                   = REPLACE(LOWER(TRIM(gt.response)),'_',' ')
                 OR (LOWER(TRIM(r.answer))='yes'
                     AND LOWER(TRIM(gt.response)) LIKE 'yes%') THEN 0
            ELSE 1 END) AS n_wrong,
       COUNT(*) AS n
FROM (SELECT country_code, question_id, MAX(id) AS id
      FROM phase2_researcher_runs
      WHERE answer IS NOT NULL
        AND LOWER(TRIM(answer)) NOT IN ('inconclusive','not_applicable',
                                        'not applicable')
      GROUP BY 1,2) latest
JOIN phase2_researcher_runs r ON r.id = latest.id
JOIN ground_truth gt ON gt.question_id = r.question_id
                    AND gt.country_code = r.country_code
WHERE gt.response IS NOT NULL AND TRIM(gt.response) <> ''
  AND r.country_code IN ('MT','NO','NL')
GROUP BY 1;

-- Untouched-country no-share (stage 2 rule; SE expected on top among
-- high-resource languages)
SELECT gt.country_code,
       ROUND(1.0*SUM(LOWER(TRIM(gt.response))='no')/COUNT(*),2) AS no_share,
       SUM(LOWER(TRIM(gt.response))='no') AS n_no
FROM ground_truth gt
JOIN questions q ON q.question_id=gt.question_id
                AND q.answer_shape='binary'
WHERE gt.response IS NOT NULL AND TRIM(gt.response)<>''
  AND gt.country_code NOT IN
      (SELECT DISTINCT country_code FROM phase2_researcher_runs)
GROUP BY 1 ORDER BY no_share DESC;
```

## Appendix B: file map

Exists already:

- `agents/verifier.py` (entry point `run_verifier`; substring check at
  `:139`; query-gen at `:111`; snippet formatter dropping URLs at `:467`)
- `agents/prompts/verifier.py` (four D15 strategies; the recipe for adding
  one at `:33`)
- `agents/models.py` (`VerifierOutput` at `:218`; do not edit)
- `agents/tools/substring.py` (v1 matcher; v2 goes beside it)
- `scripts/run_coordinator.py` (floor `:857`; accept rule `:878`; verdict
  branching `:1291`; adjudication finalisation `:300`)
- `evaluation/verifier_strategies.py` (EXP-6 apparatus; read-only)
- `data/questions/exp6_question_set.json` (71 binary questions, seeded)
- `data/questions/fr_augmented_eval_pairs.json` (ROB-FR labels)
- `scripts/dispatch_exp6_clean.py`, `scripts/build_nl_eval_pairs.py`
- `docs/VERIFIER_REDESIGN.md` (rationale and diagnosis SQL)

Built by this experiment:

- `agents/tools/substring.py::contains_v2` + `tests/test_substring_v2.py`
- `evaluation/replay_substring_v2.py`
- `evaluation/replay_commit_policy.py`
- `evaluation/replay_absence_receipts.py`
- `agents/models.py::VerifierOutputTristate` (additive)
- two tristate strategy specs + query-gen v3 (additive)
- `evaluation/verifier_redesign.py` (the EXP-11a harness)
- stage 2 only: the migration, `--tristate` coordinator flag,
  `_commit_decision`, receipts validator,
  `scripts/build_se_eval_pairs.py`

## Change log

- 2026-06-10: created. Design draft; becomes binding at the section 5
  freeze commit. No stage has run.
- 2026-06-10: **stage 0 run and gate passed; this commit is the binding
  pre-registration for stages 1 and 2.** Built `substring.contains_v2` +
  `tests/test_substring_v2.py` (13 tests), `evaluation/_replay_common.py`,
  and the three replay scripts. Results in section 5: P4 matcher v2 shipped
  to production (`agents/verifier.py:139`); ABSENCE_CEILING dropped (frozen at
  the 0.65 floor, S0.2 showed it net-negative on dev); RECEIPTS_N frozen at 2
  but lock 1 parked (S0.3, near-inert as specified); P6 confirmed inert. The
  knobs are frozen. Next: stage 1 prerequisites (tristate build + the NL
  pinned dispatch), which need quota and are not started.
