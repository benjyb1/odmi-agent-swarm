# EXP-40: architecture ablation ladder + adversarial-vs-cooperative contrast

Status: **pre-registration draft, pending Benjy's review. No dispatch until approved.**
Date drafted 2026-07-16. Registered id (on approval): `exp40_cooperative_contrast`.

## Question

Two questions, one battery:

1. **Component value (ablation ladder).** What does each layer of the adversarial
   architecture contribute: the opposing Verifier, and the arbitrating Adjudicator?
2. **Stance (the §2.5 test).** In thin-web policy QA, does an *adversarial* verifier
   (seek to refute, accept unless refuted) beat a *cooperative* verifier (seek to
   corroborate, accept only if independently supported)?

## The structural insight this design rests on

The adversarial Verifier and the Adjudicator are a matched pair. The Verifier
manufactures opposition (a counter-case); the Adjudicator arbitrates it. A
*cooperative* verifier produces no counter-case: when it corroborates it agrees
with the Researcher, and when it cannot it reports an absence, not an opposing
position. So an Adjudicator has nothing to weigh in a cooperative design. The
coherent cooperative architecture therefore drops the Adjudicator and commits on
corroborated consensus. This is the courtroom (Compete: plaintiff/defence/judge)
versus collaboration (Cooperate: agents converge, no judge) distinction from the
literature (Chowdhury; Du; Feng). It means the stance contrast is run at the
no-adjudicator level, where both architectures are coherent, and the Adjudicator's
value is tested only on the adversarial side, where it has a job.

## The four arms

Same 156-pair dev battery (MT 60 + NL 52 + AL 44), Sonnet-4.6, `wide_only`,
provider diy. Every arm gives the Researcher the identical 3-retry budget and the
identical D33 divergent-query retry mechanism; the D37 0.65 commit floor and the
D35 honesty layer are held in every arm.

| # | Arm | Pipeline | Commit / abstain rule | Source |
|---|---|---|---|---|
| 1 | `researcher_only` | R alone | commit if answer >= floor; retry on sub-floor; abstain on exhaustion | **replay** off exp34 |
| 2 | `no_adjudicator` (adversarial) | R -> disprove-V | commit if V passes; V-reject -> R retries; abstain on exhaustion | **replay** off exp34 |
| 3 | `trio` (adversarial, incumbent) | R -> disprove-V -> Adjudicator | as #2 but Adjudicator arbitrates at exhaustion | **reuse** exp34 wide_only + backfill 8 |
| 4 | `cooperative` (corroborative) | R -> corroborate-V | commit if V corroborates (consensus); V-fail -> R retries; abstain on exhaustion, **no adjudicator** | **live** (the only new spend) |

The three adversarial arms (1-3) all derive from the one existing full-trio run
(exp34 wide_only): no_adjudicator and researcher_only are pure decision-layer
replays; trio is the run itself, topped up by re-running only its 8
`agent_failure` pairs to reach a clean 156. Arm 4 is the only live dispatch.

## The contrasts (each isolates one thing)

- **#2 vs #4** — the §2.5 stance test. Both are two-agent, no-adjudicator, same
  Researcher, same retries, same floor. The **only** variable is the Verifier's
  stance: refute-and-accept-unless-refuted vs corroborate-and-accept-only-if-supported.
- **#3 vs #2** — the Adjudicator's marginal value (adversarial side, where it is
  coherent).
- **#2 vs #1** — what the opposing Verifier adds over a lone Researcher.
- **#4 vs #1** — what the corroborating Verifier adds over a lone Researcher.

## The fair corroborate Verifier prompt (draft for review)

The EXP-38 prompt ("your default stance is confirmation-seeking"; "related
material counts toward support") is a strawman and is retired from the pipeline
test. The fair version below keeps every rigour gate disprove has and differs
only in search direction and burden of proof. The load-bearing anti-rubber-stamp
clause is step 4's "adjacency is not corroboration".

```
You are the Corroborating Verifier in the ODMI Agent Swarm.

Your job is to establish whether the Researcher's answer is correct, by
seeking independent evidence that confirms it. Your aim is an accurate
verdict, reached by looking for genuine support rather than by looking for
holes. Before accepting, ask what independent evidence positively
establishes the answer; before rejecting, ask whether that support is
really absent.

[ODMI context — identical to the disprove V4 prompt]

Your reasoning process (follow in order):

1. Substring check.  [identical to disprove V4 — the deterministic
   fabrication gate; a failed substring is fabrication]

2. Source authority. [identical to disprove V4 — authority ranking and the
   forbidden-source list; a forbidden ODMI source is rejected]

3. Evidence fit. [identical five-dimension check to disprove V4 — entity,
   scope, tense/status, metric, scale/band. The cited passage must actually
   establish the answer on all five.]

4. Independent corroboration. Search for a second, independent source that
   supports the Researcher's answer, or wording in the cited source that
   directly and unambiguously establishes it. While searching for support,
   note any snippet that contradicts the answer or points to a different
   label; a contradiction is decisive even when you were looking for
   support. Adjacency is not corroboration: evidence merely on the same
   topic, or consistent with the answer without establishing it, does not
   count as support.

5. Verdict. Return verdict="pass" only when the answer fits the evidence
   (step 3) AND is corroborated (the cited source unambiguously establishes
   it, or an independent source supports it) AND nothing you found
   contradicts it. Return verdict="fail" when corroboration is absent, weak,
   or only adjacent, or when you found a contradiction. On fail, give a
   specific rejection_reason and a suggested_search_query the Researcher
   should try next to find better support.

Do not accept on adjacency. Do not reject for stylistic reasons. Judge only
whether the answer is genuinely supported.
```

Symmetry audit (the one-variable claim): steps 1-3 are byte-identical to
disprove V4. Step 4 flips the search direction (support, not counter-evidence)
but keeps a contradiction check so the verifier is not blind to refuting
evidence. Step 5 flips the burden (pass requires positive corroboration; disprove
passes on absence of refutation). "Adjacency is not corroboration" is the guard
that keeps it accuracy-seeking rather than lenient.

## Cooperative pipeline and consensus commit rule (arm 4)

New `pipeline_mode = "cooperative"` in `run_coordinator.py`:

1. **Seed.** Attempt 1 starts from exp34 wide_only's stored Researcher attempt-1
   output for the pair (verifier-independent, so identical to what a fresh
   cooperative run's first pass would produce). This pairs arm 4's first pass with
   arms 1-3 on identical evidence. If seeding a stored attempt proves impractical,
   the fallback is a fresh live attempt 1 (same config, distribution-paired not
   evidence-identical); flagged as an open build choice below.
2. **Corroborate.** The corroborate Verifier (its own supporting-search, its
   natural mechanism) evaluates.
3. **Consensus commit.** If the Verifier corroborates and agrees on the answer,
   and it is >= the 0.65 floor, commit (`accepted_cooperative`).
4. **Retry.** If the Verifier fails to corroborate (or finds contradiction), the
   Researcher retries with the divergent-query mechanism, driven by the Verifier's
   `suggested_search_query` exactly as in the adversarial loop, up to 3 retries.
5. **Abstain.** On exhaustion with no corroboration, abstain
   (`abstained_cooperative`). No Adjudicator is called.

One variable vs `no_adjudicator`: the Verifier prompt (stance). Structure, retries,
floor, and the absence of an Adjudicator are identical between #2 and #4.

## Endpoints (fixed now, balance-aware + three-outcome, per D38 R4)

Per arm, pooled and per country (MT/NL/AL), on the 78 negative golds where a false
positive is visible:

- Three-outcome: commit accuracy, coverage, negative-gold false-positive rate,
  each with Wilson 95% intervals.
- Balance-aware: per-class recall, balanced accuracy, Youden's J vs the
  majority-class baseline.
- Abstention rate and calls per resolved pair (the cost the stance buys).

Primary comparison: **#2 vs #4** on pooled commit accuracy and negative-gold FP
rate, paired McNemar per country and pooled. Secondary: #3 vs #2 (adjudicator),
#2 vs #1 and #4 vs #1 (verifier value). Holm-corrected across the secondary set.

## Prediction (directional, stated before the run)

The cooperative arm abstains more (independent corroboration is scarce on thin
web) and commits less often, but its commits are better supported, so its
negative-gold FP rate is <= the adversarial arm's while its coverage is lower.
Whether that trade nets to higher or lower balanced accuracy is the open question.
A cooperative arm that matches adversarial on FP *and* coverage would be a
reportable negative for the §2.5 thesis and is written up as such (R12). No
adoption rule: production stays trio regardless (D45); this is characterisation.

## Sample and stats

156 pairs (148 exp34 clean + 8 backfill), MT 60 / NL 52 / AL 44, 78 negative
golds. Canonical-row dedup per pair before analysis. Wilson intervals; paired
McNemar (exact) on the primary; Holm across secondaries; n fixed, no peeking (R11).

## Cost

| Arm | New Claude calls |
|---|---|
| researcher_only (replay) | 0 |
| no_adjudicator (replay) | 0 |
| trio (reuse + 8 backfill pairs) | ~250 |
| cooperative (live, 156 pairs, heavy retry by design) | ~5,000-7,000 |
| **Total** | **~5,000-7,000** |

Against ~18,700 for the 4-arm full dispatch that was stopped. Budget ceiling set
at 9,000 with the orchestrator's budget pause as the hard guard.

## Build required before dispatch

1. Fair corroborate Verifier prompt (rewrite the EXP-38 strawman to the draft
   above; new `prompt_versions` entry).
2. New `pipeline_mode = "cooperative"` in `run_coordinator.py`: consensus commit,
   no adjudicator, symmetric reject->retry wiring.
3. Attempt-1 seed path from a stored Researcher row (or accept the fresh-attempt-1
   fallback — open choice for Benjy).
4. `condition_label` = `cooperative_s46`; `experiment_id` = `exp40_cooperative_contrast`;
   registry row (R1); spec `evaluation/specs/exp40_cooperative_contrast.json`.
5. Replay scripts for arms 1-2 off exp34 (extend `adjudicator_ablation.py` /
   `exp13a_wiring_replay.py`); the 8-pair trio backfill under the frozen config.

## Rules compliance

R1 this doc + registry row before data. R2 identical battery, arms 1-3 share exact
evidence, arm 4 shares attempt-1 under the seed. R4 balance-aware endpoints on a
base-rate-carrying battery (not France). R8 stats fixed above. R9 cold cache on the
live arm. R10 deny-list applied pre-retrieval on the live arm (and the verifier
counter-search deny-list gap from the EXP-36 audit must be closed first, or the
corroborate arm's supporting-search inherits it — see open items). R11 fixed n.
R12 negative is a result; JSONL receipts per call.

## Limitations (disclosed up front)

- Arms 1-3 are replays/reuse of exp34, run for a retrieval-strategy purpose; the
  Researcher evidence is config-identical (wide_only, 4.6) and verifier-independent
  at attempt 1, so valid, but the provenance is disclosed.
- Arm 4's retries diverge from the adversarial arms after attempt 1 by design (the
  stance drives different searches); that divergence is the treatment, not a
  confound, but it means #2 vs #4 is a paired comparison only at attempt 1.
- The Adjudicator is held out of the cooperative arm by construction; the design
  cannot separate "cooperative stance" from "no arbitration" within arm 4, because
  they are not separable — a cooperative architecture has no arbitration role. The
  comparison is architecture-level and stated as such.
- Dev battery (MT/NL/AL), burned; not the held-out set. Characterisation only.

## Build status (2026-07-16)

Built and unit-tested; dispatch gated on Benjy's review.

- **Deny-list fix (precondition, DONE):** `agents/verifier.py`
  `_scrub_forbidden_counter_source` strips a deny-listed `counter_source_url`
  from any verdict (verdict kept, source+quote removed), closing the EXP-36
  counter-search leak for both disprove and corroborate. Unit-tested.
- **Fair corroborate prompt (DONE):** `verifier-corroborate` V2 in
  `agents/prompts/verifier.py`; steps 1-3 byte-identical to disprove V4, the
  "adjacency is not corroboration" guard present, the V1 strawman phrasing
  gone. Asserted in tests.
- **Cooperative pipeline_mode (DONE):** `scripts/run_coordinator.py`
  `pipeline_mode="cooperative"` with the attempt-1 seed
  (`_seed_researcher_from_experiment`), corroborate verifier + own
  supporting-search, consensus commit (`accepted_cooperative`), symmetric
  reject->retry, abstain on exhaustion (`abstained_cooperative`), no
  Adjudicator. Wired through `dispatch_subtrios.py`, `run_experiments.py`
  (flag_map), and both CLIs.
- **strategy_label migration (DONE):**
  `scripts/migrate_corroborate_strategy_label.py` adds `verifier-corroborate`
  to the CHECK (idempotent table rebuild, integrity-checked).
- **Spec + dry-run (DONE):** `evaluation/specs/exp40_cooperative_contrast.json`,
  156 pairs, one live arm, `no_cache`, seed pinned; dry-run preflight passes
  and the built command carries every knob.
- Tests: `tests/test_cooperative_and_denylist.py` (5 pass); no regression in
  the coordinator/verifier/pipeline suites (58 pass).

**Dispatch precondition (operational).** The seed reads exp34 wide_only
Researcher rows, which live in the canonical DB, not a fresh worktree copy.
Before dispatch the run DB must be synced from canonical and then migrated
(`migrate_corroborate_strategy_label.py`, both CHECKs).

**Seed coverage (corrected 2026-07-16 at dispatch).** Only **48 of the 156**
pairs have a committable exp34 attempt-1 to seed; the other **108** run a live
attempt 1. The seed query requires a non-inconclusive attempt-1 answer, and on
this thin-web dev battery exp34's Researcher abstained on the first attempt for
most pairs, so there is nothing to reuse there and the cooperative arm
generates its own attempt 1 (correct behaviour, not a fault). The earlier
"139" figure counted all retry_count=0 rows including inconclusive ones and was
wrong. Consequence: more live compute and attempt-1 pairing on 48 pairs rather
than 139; the stance contrast (no_adjudicator vs cooperative) is unaffected
since both diverge after attempt 1 regardless. Budget raised 9k -> 12k for the
extra live attempt-1s; the orchestrator budget-pause remains the guard.

## Result (2026-07-19, run complete, 156/156)

Full four-arm read (`evaluation/results/exp40_analysis.json`), dev battery
MT 60 + NL 52 + AL 44, 78 negative golds. trio / no_adjudicator /
researcher_only are replayed off exp34 wide_only; cooperative is the live arm
(93 abstain, 63 commit, 1 agent_failure; deny-list clean, 0 blocked).

| arm | coverage | commit-acc | neg-gold FPR | balanced-acc | Youden J |
|---|---|---|---|---|---|
| trio | 0.47 | 0.73 | 0.22 (17/78) | 0.33 | -0.34 |
| no_adjudicator | 0.39 | 0.69 | 0.22 (17/78) | 0.26 | -0.48 |
| researcher_only | 0.24 | 0.65 | 0.13 (10/78) | 0.15 | -0.70 |
| **cooperative** | **0.40** | **0.65** | **0.24 (19/78)** | **0.26** | **-0.48** |

**Primary contrast (no_adjudicator vs cooperative, one variable = verifier
stance): a clean null.** Balanced accuracy 0.261 vs 0.262, Youden J -0.477 vs
-0.476, coverage 0.39 vs 0.40, neg-gold FPR 0.218 vs 0.244. Paired McNemar on
committed correctness over the 154 shared binary-gold pairs: 8 discordant each
way, **p = 1.00**. The two arms differ per pair (16 discordant pairs; the pilot
saw cooperative avoid a trio false positive and recover a correct answer trio
missed) but net to an exact tie.

**The prediction is refuted, in the mild-negative direction.** The prereg
predicted cooperative would abstain more and carry a *lower* FPR (coverage down,
precision up). It does neither: it commits marginally *more* (0.40 vs 0.39) at a
marginally *higher* FPR (0.24 vs 0.22), both within noise. A fair,
best-effort corroborative verifier is indistinguishable from the adversarial
verifier at the pipeline level on this battery.

**Reconciliation with EXP-38, and the real finding.** EXP-38 found the
corroborative stance much worse at the verifier's *isolated* job (Youden J 0.16
vs disprove's 0.41 on frozen candidates). EXP-40 finds that difference washes
out end to end. Both are true and together they locate the effect precisely:
**the verifier's stance governs its own discrimination but is not the binding
system-level precision control.** That control is the D37 confidence floor and
the researcher's evidence quality (consistent with D45 / VERIFIER_FINDINGS: the
verifier verdict is decision-relevant on few pairs, and the floor is the binding
gate). So the §2.5 claim needs reframing away from "adversarial beats
corroborative for the system" toward "adversarial framing sharpens the
verifier's own discrimination, but system precision is set upstream (retrieval,
floor), not by the verifier's stance." This is a negative result on the
headline prediction and is reported as such (R12); it does not change production
(trio stays, D45).

Secondary ladder (adversarial side, replays): the Adjudicator earns its place
(trio 0.47/0.73 vs no_adjudicator 0.39/0.69 at flat FPR -- it rescues correct
commits); the Verifier loop lifts coverage 0.24 -> 0.39 but also raises FPR
0.13 -> 0.22 (it drives more commits, some wrong).

Limitations: dev battery (MT/NL/AL), burned; balanced accuracy is low and J
negative for every arm because abstention is high on this thin-web set and
counts against recall -- the between-arm comparison, not the absolute level, is
the result. 1 agent_failure (AL) excluded. PT17:AL required a manual single-pair
resume (slow AL search); it abstained.

## Open item flagged to Benjy

The corroborate Verifier runs a supporting-search. The EXP-36 audit found the
Verifier counter-search bypasses the deny-list (`counter_source_url` can hit ODMI
mirrors). That gap must be closed before arm 4 runs, or the corroborate arm can
pull ODMI's own answer as "corroboration" — the worst possible leak for a
confirmation-seeking verifier. This is the chipped fix; it is now a hard
precondition for EXP-40, not an optional cleanup.
