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
(`migrate_corroborate_strategy_label.py`). 139 of the 156 pairs have a clean
attempt-1 seed row; the other 17 (8 agent_failure + a few inconclusive
attempt-1s) fall back to a live attempt 1, disclosed.

## Open item flagged to Benjy

The corroborate Verifier runs a supporting-search. The EXP-36 audit found the
Verifier counter-search bypasses the deny-list (`counter_source_url` can hit ODMI
mirrors). That gap must be closed before arm 4 runs, or the corroborate arm can
pull ODMI's own answer as "corroboration" — the worst possible leak for a
confirmation-seeking verifier. This is the chipped fix; it is now a hard
precondition for EXP-40, not an optional cleanup.
