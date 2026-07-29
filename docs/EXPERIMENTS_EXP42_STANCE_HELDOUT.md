# EXP-42: verifier stance on the held-out eight (corroborative vs adversarial)

Status: **pre-registration, written before any EXP-42 data exists (R1).**
Drafted 2026-07-27. Registered id: `exp42_stance_heldout`.
Supersedes EXP-40's stance contrast as the powered read; EXP-40 remains the
dev-battery characterisation.

## Why this runs at all

EXP-40 compared an adversarial verifier against a corroborative one end to end
and returned a null: balanced accuracy 0.261 vs 0.262, paired McNemar p = 1.00 on
8-vs-8 discordant pairs. Section 4.2 of the dissertation currently reads that as
"the Verifier's stance does not matter", and section 5.2 builds on it.

That reading is not supported by the design. A McNemar test on 16 discordant
pairs fails to reject the null; it does not establish equivalence. At that n only
a very large effect is detectable, so the honest statement is "no large effect
detected on a 156-pair dev battery". EXP-40's own limitations section says the
same thing. No equivalence test was pre-registered, so nothing licences the
stronger claim.

EXP-42 fixes the two defects that make the claim unsafe:

1. **Power.** 1,144 pairs against 156, and 370 negative golds against 78.
2. **Scope.** The held-out eight the results chapter is framed around, rather
   than the burned dev battery.

The experiment is registered as characterisation. There is no adoption rule.
Production stays trio regardless of outcome (D45).

## Question

Holding the architecture fixed, does swapping the Verifier's stance from
adversarial (seek to refute, accept unless refuted) to corroborative (seek to
support, accept only if supported) change system-level commit accuracy or the
negative-gold false-positive rate, on the held-out eight?

"Stance" here means the pair of things that make a stance coherent: the direction
the Verifier searches, and the burden its verdict rule applies. Both move together
in arm B. EXP-38 already isolated the verdict rule on its own, search-free, so the
decomposition exists across the two experiments rather than inside this one.

## Battery

The eight D47 held-out countries at the full 143 questions: BA, MK, ME, BG, FI,
HR, SE, BE. 1,144 pairs. Ground truth from the `ground_truth` table:

| CC | binary golds | negative golds | total |
|---|---|---|---|
| BA | 93 | 79 | 143 |
| BE | 115 | 24 | 143 |
| BG | 117 | 51 | 143 |
| FI | 120 | 29 | 143 |
| HR | 113 | 27 | 143 |
| ME | 113 | 59 | 143 |
| MK | 116 | 73 | 143 |
| SE | 122 | 28 | 143 |
| **total** | **909** | **370** | **1,144** |

235 pairs carry a non-binary gold (bands, counts, `not_applicable`). Those are
scored in coverage and commit accuracy but excluded from the paired binary tests,
exactly as EXP-36 handled them.

**Held-out freeze (D47).** This is a second touch of the frozen set. EXP-36 was
the sanctioned single evaluation pass. EXP-42 is admissible on the same grounds
EXP-40 used, that it is characterisation with no adoption rule and cannot tune
production, but the second touch is disclosed here and in the dissertation
limitations, and it is Benjy's call with his supervisor, not an autonomous one.
The set is burned for any subsequent tuning either way.

## The architecture, stated explicitly

This section exists so the fairness of the contrast can be checked line by line.

### Arm A: adversarial, `no_adjudicator`. Replay. Zero new calls.

Reconstructed from the stored `exp36_frozen_headline` rows by the decision-layer
replay in `evaluation/exp40_analysis.py:168-211`. The rule, verbatim from that
file:

- commit iff `terminal_status == "accepted_by_verifier"` and the answer is not
  `inconclusive`;
- `accepted_by_adjudicator` and `abstained_adjudicator` both become abstentions,
  because without an Adjudicator neither would have committed;
- `agent_failure` stays a failure and is excluded from both arms.

Replay yield on the canonical-latest exp36 set, verified:

| exp36 terminal_status | n | arm A outcome |
|---|---|---|
| `accepted_by_verifier` | 526 | commit |
| `accepted_by_adjudicator` | 205 | abstain |
| `abstained_adjudicator` | 413 | abstain |
| `agent_failure` | 0 | — |

Arm A commit rate 526/1,144 = 0.460. No pairs are lost.

### Arm B: corroborative, `cooperative`. Live. The only required new spend.

`pipeline_mode="cooperative"` in `scripts/run_coordinator.py:1571`. Control flow,
traced:

1. **Seed.** Where a committable EXP-36 attempt-1 exists, attempt 1 is seeded
   from it (`_seed_researcher_from_experiment`, `run_coordinator.py:891`) so both
   arms start from identical evidence. Coverage is 392/1,144 (see below).
2. **Corroborate.** The corroborate Verifier runs its own supporting search and
   returns a verdict.
3. **Commit.** `accepted_cooperative` iff verdict is `pass`, the answer is not an
   abstention, and answer confidence >= 0.65. The predicate at
   `run_coordinator.py:1066-1077` is shared with every other pipeline mode, so
   the floor is applied identically.
4. **Retry.** On fail, the Researcher retries with the D33 divergent-query
   mechanism driven by the Verifier's `suggested_search_query`, up to 3 retries.
   The retry wiring at `1756-1757` is mode-agnostic.
5. **Abstain.** On exhaustion, `abstained_cooperative`. The answer is forced to
   `inconclusive` at `1782`.

The Adjudicator is never called. Verified structurally: `run_adjudicator` has one
call site, `run_coordinator.py:1862`, which sits after the unconditional cooperative
return at `1811`.

### There is no third arm. Drift is checked for free instead.

An earlier draft of this pre-registration carried a third arm: a live adversarial
control on a 200-pair subsample, to measure how much of any A-vs-B difference was
the web having moved between exp36's window and this one. It was cut, and the
reasoning is recorded here because the temptation to add it will recur.

Two reasons. First, drift and run-to-run stochasticity add discordance
**symmetrically**, to both off-diagonal cells. McNemar tests the *asymmetry* of
discordance, so a symmetric nuisance costs power, not validity. It cannot
manufacture a directional stance effect. The only version of drift that could
bias the result is the web systematically improving or degrading over ten days by
enough to move commit accuracy several points, which is not plausible for national
open-data portals on that timescale. Second, the arm would have spent about 10,000
calls and, more expensively, 200 further pairs of exposure on a frozen set where
exposure is the scarce resource, to re-measure a configuration EXP-36 has already
characterised.

**The free substitute.** Arm B's 392 seeded pairs start from exp36's stored
attempt-1 evidence, so retrieval is identical to arm A's on those pairs. The 752
unseeded pairs search live. If drift were doing real work, the stance effect would
differ between the seeded and unseeded subsets. That contrast is computed from
data arm B already produces, costs nothing, and spends no extra held-out exposure.
It is registered as a diagnostic below.

It is a weaker instrument than a dedicated control arm: the two subsets differ in
difficulty as well as in retrieval freshness, so a difference between them is not
cleanly attributable to drift. That is stated as a limitation rather than
papered over.

## This is a steel-man, and that framing is load-bearing

The corroborative arm is built to do as well as it possibly can. Its prompt is
repaired (V3), its retrieval is aligned to its verdict rule (corroborative query
generation), its parse path is verified. The adversarial comparator is frozen production,
replayed off EXP-36 and not re-tuned.

That asymmetry is deliberate, and the direction it runs matters:

- **If the steel-manned corroborative arm still fails to beat adversarial**, the
  section 2.5 claim is supported far more strongly than EXP-40 supported it,
  because the alternative was given every advantage and still did not win. This is
  the conservative direction and it is the reason the asymmetry is acceptable.
- **If the corroborative arm wins**, the result is confounded with the tuning: we
  cannot say whether corroboration is better or whether an optimised arm beat an
  un-optimised one. That outcome is reportable as "a well-built corroborative
  verifier is at least competitive with frozen production", and no more. It cannot
  be written up as "corroboration beats adversarialism".

Both readings are fixed here, before the data exists, so neither can be chosen
after seeing the result. Anyone tempted to optimise the corroborative arm further
mid-run should note that doing so only strengthens the first reading and further
weakens the second.

## What is held constant, and what varies

The one intended variable is the Verifier's verdict prompt. Everything below is
pinned identically across both arms.

| Held constant | Value | Enforced by |
|---|---|---|
| Reasoning model | `claude-sonnet-4-6` | spec `researcher_model` / `verifier_model` |
| Snippet picker model | `claude-sonnet-4-6` | spec `picker_model` |
| Search provider | `diy` | spec `provider` (D43; never `auto`) |
| Retrieval strategy | `wide_only` | spec `search_strategy` (EXP-34 adoption) |
| Max retries | 3 | spec `max_retries` |
| Queries per search | 3 | spec `num_queries` |
| Results per query | 5 | spec `max_results_per_query` |
| Verifier search | `always` | spec `verifier_search` |
| Commit confidence floor | 0.65 | `COMMIT_CONFIDENCE_FLOOR`, hardcoded at `run_coordinator.py:1045`; there is no CLI override, so the floor is held by construction, not by a knob |
| Honesty layer | D35, on | code |
| Deny-list | D24, on | pre-retrieval, three layers (below) |
| Cache regime | cold (`no_cache: true`) | matches EXP-36's own setting |
| Adjudicator | absent in both arms | arm A by replay rule, arm B by construction |

| Varies (jointly, as one construct: verifier stance) | Arm A | Arm B |
|---|---|---|
| Verifier verdict prompt | `verifier-disprove` V4 (`prompt_versions.id=23`) | `verifier-corroborate` V3 (new, see below) |
| Burden of proof | pass unless refuted | pass only if corroborated |
| Verifier search direction | counter-evidence (`generate_adversarial_queries`) | supporting evidence (`generate_corroborative_queries`) |

## Known asymmetries, and what is done about each

These are the places the contrast could be unfair. Each is either fixed before
dispatch or disclosed as a limitation.

### 1. Prompt rigour asymmetry. FIXED before dispatch.

EXP-40's documentation claims the two prompts differ only in stance, on the
strength of steps 1 to 3 being byte-identical. That check was verified and holds:
step 1 (461 B), step 2 (714 B) and step 3 (253 B) are identical in both prompts.

The preamble is not. Disprove V4 carries a rejection criterion at
`agents/prompts/verifier.py:269-270` that corroborate V2 drops entirely:

> "Vague, paraphrased, or out-of-date evidence is grounds for rejection."

Corroborate V2 has no equivalent. The corroborative verifier is therefore missing
a rigour gate its adversarial counterpart has, which biases it toward passing.
That bias runs in the direction of the section 2.5 hypothesis, so EXP-40's null
is conservative and stands, but it makes EXP-42 an unfair test as it stands.

**Resolution.** Register `verifier-corroborate` **V3**, which is V2 plus the
corroborative mirror of the dropped criterion. Copying the disprove sentence
verbatim would import adversarial framing into a corroborative prompt, so the
mirror is stated in the prompt's own terms:

> "Vague, paraphrased, or out-of-date evidence does not constitute corroboration."

This equalises rigour while preserving the stance flip. The cost is that EXP-42
is not a pure scale-up of EXP-40: their corroborate prompts differ by this one
sentence, and any EXP-40-to-EXP-42 comparison must say so. That cost is worth
paying, because the alternative is a headline held-out result running a
verifier that is missing a gate the comparator has.

### 2. The corroborative arm currently searches adversarially. FIXED before dispatch.

This is the most serious defect found, and an earlier draft of this document got
it wrong by calling the shared generator "the tighter design". It is not. It is a
handicap on the corroborative arm, and it contradicts what EXP-40's own
pre-registration said the arm was doing.

`generate_adversarial_queries` (`agents/verifier.py:628-630`, prompt at
`103-125`) produces the Verifier's independent search queries in **both** stances.
`scripts/run_coordinator.py:1585-1593` swaps only `v_strategy`, leaving `v_search`
untouched. That generator's prompt instructs:

> "produce 2-3 short web search queries that are specifically designed to find
> evidence AGAINST the Researcher's answer... binary: search for the opposite
> label (yes -> no, no -> yes)."

Meanwhile corroborate V2's step 4 instructs the verifier to "Search for a second,
independent source that **supports** the Researcher's answer". So the corroborating
verifier is told to seek support and then handed snippets selected to contradict.
Its verdict rule requires positive corroboration; its evidence supply is optimised
to contain none. EXP-40's prereg claimed "step 4 flips the search direction
(support, not counter-evidence)", which the implementation never did.

**Resolution.** Give the corroborative stance its own query generator, so each
stance retrieves in the direction its verdict rule requires. Adversarial keeps
counter-search with a refutation burden; corroborative gets support-search with a
corroboration burden. Both are then internally coherent.

**Corrected 2026-07-29.** This section originally specified wiring
`generate_confirmation_probes` (`agents/verifier.py`, reachable only from the
offline harness at `evaluation/verifier_redesign.py`) into the cooperative path.
That was wrong on inspection. The probe generator is absence-specific: its system
prompt opens "The Researcher has answered that some feature, API, dataset, or
policy instrument does NOT exist for this country", and it asks for queries that
would find that thing if it existed. On a positive answer the prompt does not
apply. On a negative answer it hunts for the positive thing, which is refutation,
the opposite of what arm B needs. Wiring it in would have left arm B searching
adversarially on every positive claim and refutationally on every negative one,
which is the same chimera under a different name.

Built instead as `generate_corroborative_queries`, a direction mirror of
`generate_adversarial_queries` carrying the same shape-awareness: for binary, the
claimed label rather than the opposite one, and for a claimed absence an
authoritative statement of exclusion rather than the thing itself; for ordered
bands, a figure inside the claimed band rather than one step off; for
categoricals, the claimed category. Same 2-3 query budget, same national-language
requirement, same official-source targeting, same `_build_query_gen_message`
input. The arms therefore still differ by stance alone, and the mirror is a
smaller change than adapting an absence-only generator would have been.

**This widens the treatment, and the pre-registration owns that.** EXP-42 now
varies two coupled things: the verdict rule and the search direction. That is the
correct definition of a verifier *stance*: a verifier that searches one way and
judges the other is not a stance, it is a chimera, and measuring it answers no
question anyone asked. The cost is that EXP-42 alone cannot separate verdict rule
from search direction. It does not need to: **EXP-38 already isolated the verdict
rule** on frozen candidates with no search at all (disprove J 0.41 vs corroborate
J 0.16). EXP-38 gives the verdict rule in isolation, EXP-42 gives the whole stance
in the pipeline, and together they decompose the effect. That is a better
decomposition than either alone.

Built and tested 2026-07-29 (`83d193a`). `tests/test_exp42_stance.py` pins that
`verifier-corroborate` calls the corroborative generator and never the
adversarial one, that `verifier-disprove` is untouched, and that the EXP-14
`never` policy still skips both.

### 3. Seed coverage is 34%, and it is not random. DISCLOSED with a pre-specified subgroup.

The seed predicate (`run_coordinator.py:911-935`) requires `retry_count = 0`, a
non-null answer, no failure mode, and an answer that is not `inconclusive`.
Against exp36 that yields **392 of 1,144 pairs (0.343)**:

| CC | BA | BE | BG | FI | HR | ME | MK | SE | total |
|---|---|---|---|---|---|---|---|---|---|
| seedable | 20 | 54 | 27 | 82 | 48 | 51 | 40 | 70 | **392** |

The cause is that 761 of 1,158 exp36 attempt-1 rows answered `inconclusive` and
are excluded. So the 752 unseeded pairs are systematically the harder ones, and
they run a live attempt 1 against a web that has moved since July.

**Resolution.** The 392 seeded pairs are pre-registered as a named secondary
analysis. On those pairs attempt 1 is evidence-identical across arms, so they are
the strictly paired subset. The primary stays the full 1,144 because restricting
to seeded pairs would bias the battery toward easy questions. Both are reported.

For calibration: EXP-40's seeding was no better in proportion (49 of 149
attempt-1 rows carried a seed, 32.9%), so the doc's implication that its arms
started from identical evidence was already true of only a third of pairs.

### 4. `condition_label` in exp36 is the country code. HANDLED in the spec.

exp36 stored `condition_label` as `BA, BE, BG, FI, HR, ME, MK, SE`, not an arm
name, and the seed predicate pins a single scalar label. A single-arm spec copied
from the EXP-40 template would match zero seed rows and silently run everything
live, because the seed miss path only prints (`run_coordinator.py:1298-1303`).

EXP-42 is therefore dispatched as **eight per-country sub-batches**, each with
`--seed-condition-label <CC>` matching its own `--countries <CC>`. Seed hit counts
per country are logged and checked against the table above before analysis. A run
whose seed count deviates from 392 is a failed dispatch, not a result.

### 5. Retries diverge after attempt 1. This is the treatment, not a confound.

A corroborative verifier fails different claims and suggests different follow-up
queries, so arm B's trajectory separates from arm A's after attempt 1 by design.
That divergence is what a stance change does. It does mean the A-vs-B pairing is
strictly evidence-identical only at attempt 1, and only on the 392 seeded pairs.

### 6. Cost per pair is not comparable between arms. DISCLOSED.

Arm A is free and reuses EXP-36's already-paid adversarial searches. Arm B pays
for a fresh corroborative search on every attempt. Any per-pair cost or
calls-per-resolved-pair comparison between A and B is not like for like. Where
cost is compared, it is B against C, both live.

### 7. Catalogue asymmetry pre-dates this experiment. DISCLOSED.

Only 4 of the 8 held-out countries are catalogue-computable (FI, ME, HR, SE);
BG, MK, BE and BA are blocked by geo-blocking, absent machine APIs or
single-agency non-DCAT publication. Catalogue coverage is therefore already
uneven across the battery before EXP-42 starts. It is even across arms, so it
does not bias the contrast, but it bounds what the per-country reads mean.

Related build defect, carried from the known orchestrator gap:
`--no-warm-catalogue`, `--refresh-catalogue` and `--allow-large` are absent from
`scripts/run_experiments.py::build_command` flag_map, so a spec setting them is
silently ignored. EXP-42 does not set them. If catalogue behaviour needs pinning,
flag_map must be fixed first.

### 8. 33 seedable rows have empty stored snippets. DISCLOSED.

33 of the 392 seedable rows carry an empty `search_snippets`. Those seed with an
empty snippet list, which routes the substring gate down the live-fetch fallback
(`agents/verifier.py:237-259`) rather than the stored-snippet path, adding a live
network dependency on possibly-dead URLs. Counted and reported; too small to
restratify around.

## Data-leakage control

The corroborative stance is the worst case for leakage, because a
confirmation-seeking verifier that reaches ODMI's own published answers would
find perfect "corroboration". The controls were verified in code, not assumed:

- **Pre-fetch SERP filter.** `agents/tools/search_diy.py:157` drops deny-listed
  URLs after the SERP cache read and before any fetch or snippet pick, so a
  blocked URL never reaches the picker.
- **Fetch-layer refusal.** `agents/tools/fetch.py` refuses blocked URLs before any
  network call, at five entry points.
- **Post-filter backstop.** `agents/tools/search.py:153-169`.
- **Parametric-emission scrub.** `_scrub_forbidden_counter_source`
  (`agents/verifier.py:388-420`, called at `827`) strips a deny-listed source URL
  and quote from a returned verdict while deliberately leaving the verdict itself
  intact, so a `fail` still retries rather than flipping to a commit. Its
  docstring confirms it covers the corroborate strategy's contradiction source.

The pre-retrieval filters are the primary control. The scrub is the backstop for
the one channel retrieval filtering cannot reach, a URL emitted from model
memory. EXP-36's audit found 7 such rows on this channel, which is what prompted
the scrub.

**Gate.** A committed-evidence audit runs post-hoc on arm B, as EXP-36's did. Any
committed pair citing a deny-listed source is a failed run, not a finding.

## One hypothesis tested and refuted before dispatch

A corroborative verifier looks like it should be structurally unable to pass a
correct *negative* answer: you cannot usually find a source positively
establishing that a thing does not exist. With 370 negative golds in the battery,
that would have crippled arm B on merit rather than on stance, and it would have
been an implementation defect rather than the treatment.

It was checked against the EXP-40 data and it is **false**:

| conditional | corroborate | disprove |
|---|---|---|
| P(verifier pass \| researcher answered `no`) | 0.648 (59/91) | 0.693 (70/101) |
| P(verifier pass \| researcher answered `yes`) | 0.647 (66/102) | 0.606 (63/104) |
| P(pass) on *correct* negatives | 0.710 (44/62) | 0.766 (49/64) |
| commit rate on negative golds | 27/78 | 28/78 |

The corroborative verifier's pass rate on negative answers is identical to its
rate on positive ones (0.648 vs 0.647, Fisher p = 1.00), and its commit rate on
negative golds matches the adversarial arm's (Fisher p = 1.00). It passes correct
negatives by citing real independent evidence, not by defaulting. Neither stance
has any negative-specific commit route in code: `absence_corroborated` and the
tristate commit rule from `docs/VERIFIER_REDESIGN.md` were **never implemented**
(zero code hits, zero DB columns; that document's own header says so), and D44,
the only negative-specific logic in the pipeline, is a restriction that lives in
the Adjudicator path and therefore never fires in cooperative mode. The stances
are symmetric here.

**The real stance mechanism, pre-registered as the expected one.** The only
significant verdict difference in the EXP-40 data is on `inconclusive` researcher
answers: corroborate passes 0.147 of them against disprove's 0.514, Fisher
p = 0.0013. That is the stance working as intended, since an abstention has
nothing to corroborate, and it is the treatment rather than a defect. Its
practical consequence is limited, because `_should_accept_verifier_pass` blocks a
commit on an abstention regardless of verdict, so the effect runs through retry
behaviour rather than through commits.

Caveat: all of the above is the 156-pair dev battery, 62 correct-negative verifier
rows. It is enough to refute a claimed *structural* block. It is not powered to
exclude a 5 to 10 point effect, and the observed 5.6-point gap on correct negatives
sits inside that unresolvable band. EXP-42 will resolve it at 370 negative golds.

## Endpoints

Pre-specified now, balance-aware and three-outcome throughout (D38 R4, D47).
Reported pooled and per country, with Wilson 95% intervals.

**Primary.** Arm B vs arm A, on two endpoints, both pre-registered as co-primary
with Holm correction across the pair:

1. Commit accuracy, paired McNemar (exact) on committed correctness over the
   shared binary-gold pairs.
2. Negative-gold false-positive rate over the 370 negative golds, paired.

**Secondary**, Holm-corrected as a family:

- Coverage, and the abstention rate.
- Per-class recall, balanced accuracy, Youden's J against the majority-class
  baseline.
- Expected calibration error.
- The 392-pair seeded subgroup, primary endpoints repeated.
- Per-dimension strata (Policy / Portal / Quality / Impact).
- RQ3 resource-stratum contrast, mirroring EXP-36's A-vs-B split.
- **Architecture-level contrast: production trio (3 agents) vs cooperative (2).**
  Not matched, and reported as such: the trio gets an arbitration stage the
  cooperative design has no role for. It is the practically interesting comparison
  because it asks what a cheaper two-agent architecture gives up against shipped
  production, so it is reported with a cost normalisation rather than suppressed.
  Verified cost, matched dev battery: cooperative 4.26 agent calls per pair against
  trio's 6.30, **32% fewer**. Attempts per pair are near-identical (2.78 vs 2.81),
  so the saving is the Adjudicator, not fewer retries. On the held-out set the
  Adjudicator fires on 0.55 of pairs against 1.92 on dev, so the expected saving
  there is smaller, nearer 15%; the run will measure it. Any claim that the
  cooperative architecture is cheaper cites these numbers, not an estimate.

**Nuisance quantification**, reported before the primary is interpreted:

- Stance effect computed separately on the 392 seeded pairs (retrieval identical
  to arm A) and the 752 unseeded pairs (live retrieval). A materially different
  effect across the two is the signal that drift is doing work. Confounded with
  difficulty, so read as a diagnostic, not a clean drift estimate.
- Discordance rate compared against EXP-41's measured run-to-run floor
  (outcome unanimity 0.703, label agreement 0.922).

**Equivalence.** If the primary returns a null, a TOST equivalence test is run
against a pre-registered margin of **±0.05 commit accuracy**, chosen as the
smallest difference that would change an architectural recommendation. Only a
TOST that clears that margin licences the word "equivalent". A failed TOST plus a
failed McNemar is reported as inconclusive, which is the honest reading EXP-40
should have carried.

## Power

Stated before the run, with assumptions named.

Discordance on the paired binary test is driven mostly by run-to-run
stochasticity, which EXP-41 measured directly: three replicates of one config on
the dev battery agreed on outcome for only 0.703 of pairs, and on the label for
0.922 of pairs once all three committed. EXP-40 observed 16 discordant pairs on
154 shared binary golds, a 10.4% discordance rate consistent with that.

Applying the same 10.4% rate to 909 binary golds gives roughly **95 discordant
pairs**. For 80% power at α = 0.05 two-sided, McNemar needs

    (2p − 1)·√n ≥ 1.96 + 0.84 = 2.80

At n = 95 that requires p ≥ 0.644, a net imbalance of about 27 pairs, or
**3.0 percentage points** of commit accuracy.

The same calculation on EXP-40's n = 16 required p ≥ 0.85, a net imbalance of
about 11 pairs, or 7.3 percentage points. EXP-42 improves the minimum detectable
effect by roughly 2.4 times.

On the negative-gold endpoint, 370 negative golds against 78 narrows the
confidence interval on the FPR difference by a factor of about √(370/78) = 2.2.
EXP-40's FPR difference interval spanned roughly ±0.13; EXP-42's should span
roughly ±0.06.

**Stated plainly:** EXP-42 is powered for moderate effects, not small ones. A
null at this n means no effect of about 3 points or larger, which is a much
stronger statement than EXP-40 could make, and it is still not proof of
equivalence unless the TOST clears ±0.05. The dissertation must say exactly that.

## Prediction, stated before the run

Registered directionally, per R12.

The corroborative arm commits at a similar or slightly higher rate than the
adversarial arm, with a similar or slightly higher negative-gold false-positive
rate, and the difference on both primary endpoints does not reach significance.
The two repairs (V3 and confirmation probes) are expected to raise arm B's
coverage relative to EXP-40's cooperative arm, since that arm was searching in the
wrong direction for its own verdict rule; whether they move commit accuracy is
the open question.
This is EXP-40's observed direction carried forward, not its original prediction,
which EXP-40 refuted.

The reasoning is EXP-40's own: the binding precision control is the D37 floor and
retrieval quality, not the verifier's accept-or-reject framing, and the verifier
verdict is decision-relevant on relatively few pairs (D45). Against that, EXP-36
shows the verifier is far more active on the held-out set than on the dev battery
(all 1,144 pairs reach the verifier, 741 of 1,973 verdicts are `fail`, and 499
pairs carry at least one fail), so there is materially more room for stance to
matter here than there was in EXP-40. That tension is the reason to run it.

A result in either direction is reportable. A powered null earns the section 2.5
reframing honestly. A detected difference means the dev-battery null was an
underpowered miss, which is a more defensible finding than the current
unqualified claim.

## Cost

Derived from EXP-36 and EXP-40 actuals, not from an estimate.

EXP-36 ran 3,451 researcher attempts over 1,144 pairs, 3.02 attempts per pair.
EXP-40's cooperative arm ran 486 attempts over 157 pairs, 3.10 per pair. Assume
3.05 for EXP-42, so about **3,490 attempts**.

Cooperative costs 4 reasoning calls per attempt (researcher query-gen,
researcher, verifier query-gen, verifier; no adjudicator). Across the corpus the
snippet picker runs at 105,274 calls against 33,728 reasoning calls, so total
calls are about 4.12 times reasoning calls.

| Arm | Pairs | Attempts | Reasoning calls | Total calls |
|---|---|---|---|---|
| A (replay) | 1,144 | 0 | 0 | **0** |
| B (live cooperative) | 1,144 | ~3,490 | ~13,960 | **~57,500** |
| **total** | | | | **~57,500** |

Budget ceiling 60,000 calls, with the orchestrator budget pause as the hard guard.

There is no API billing (CLIProxyAPI on the Claude Max subscription). The real
constraint is DIY concurrency: Serper and WAF limits, the roughly 20-process RAM
ceiling, and collision with other dispatch windows. EXP-36 needed a resume-safe
supervisor and several days. EXP-42's arm B is retry-heavier than trio, so plan
for at least that. Check `ps aux` before adding arms. Put SE last and keep a stall
watchdog on it: `dataportal.se`'s SPARQL endpoint has hung dispatch in rdflib for
about 90 minutes with no progress, and there is no per-arm timeout.

## The dispatch guard blocks this run, by design

Both specs were written and dry-run. They are structurally clean: the preflight
reports no knob, arm or pair-expansion errors. It fails on exactly two things,
and both are worth recording.

**1. The D47 freeze is enforced in code, not just in the methodology.**
`scripts/run_experiments.py:170-174` rejects any spec naming a held-out country.
The single sanctioned exception, at `168`, is `spec.headline is true` **and**
every country in the experiment being held-out:

```python
headline_ok = spec.get("headline") is True and countries_in_exp <= HELD_OUT
```

So EXP-42 cannot dispatch as written. The guard is doing its job.

Setting `headline: true` would clear it, and that is the wrong fix. EXP-42 is not
the headline run, EXP-36 is; marking it headline would put a false claim in the
receipts and would risk downstream analysis treating it as the reported headline.
**The guard has not been lifted, and must not be lifted quietly.**

The correct fix, if Benjy and his supervisor approve the second touch, is an
explicit and auditable escape hatch rather than a removed check: a spec key such
as `heldout_second_touch: true` paired with a required free-text `justification`,
which the preflight logs and which fails unless a matching registry row already
exists. That way the override appears in the receipts and an examiner can see
exactly when and why the frozen set was touched a second time. Building that
escape hatch is a separate, reviewable change and is **not** included here.

**2. The dispatch DB must be synced from canonical.** The preflight also reports
`not pre-registered`, because the worktree's `data/odmi.db` is a 134-byte git-LFS
pointer, not a database. The registry rows exist in the canonical DB. As with
EXP-40, dispatch must run from a fresh copy of the canonical DB, never a worktree
copy, and the seed path depends on it: the exp36 researcher rows the seed reads
live in canonical.

## Build required before dispatch

Status 2026-07-29: items 0 to 4 are **done** (`83d193a`). Items 5 to 7 are
**outstanding** and are analysis and operations work, not gates on correctness of
the arms. Item 0's *decision* is still owed; the mechanism it needs now exists.

0. **DONE (mechanism), OWED (decision).** The auditable override is built:
   `heldout_second_touch` plus a non-empty
   `heldout_second_touch_justification`, with every country held-out and no
   `headline` claim, is the only way past the D47 guard, and the justification is
   written to the run manifest and the event log. **The spec deliberately does
   not carry the flag**, so dispatch stays blocked until Benjy and his supervisor
   make the call and the sign-off is recorded in the justification text.
1. **DONE. Corroborative search direction.** Built as
   `generate_corroborative_queries` rather than by wiring
   `generate_confirmation_probes`, for the reason given in defect 2 above: the
   probe generator is absence-specific and would have searched refutationally on
   negative claims. Deny-list coverage is unchanged, since both generators feed
   the same `search_many` path and the scrub is applied there rather than per
   generator. A dev-pair smoke test before the held-out dispatch is still worth
   running and is folded into item 7.
2. **DONE. `verifier-corroborate` V3.** Mirror sentence added to the preamble,
   `_CORROBORATE_VERSION` bumped to 3, registry description updated. Tests assert
   the new sentence is present, that disprove's rejection wording was not
   imported, and that steps 1 to 3 remain byte-identical to disprove V4.
3. **DONE. Spec** `evaluation/specs/exp42_stance_heldout.json`: eight per-country
   sub-batches, each pinning `seed_experiment_id: "exp36_frozen_headline"` and
   `seed_condition_label: "<CC>"`, plus the full knob set from the held-constant
   table. Pin `max_retries`, `num_queries`, `max_results_per_query` and `strategy`
   explicitly rather than inheriting dispatch defaults, which the EXP-40 spec did
   not do.
4. **DONE. Registry row** in `experiments` before any data (R1). Present in the
   canonical DB since 2026-07-27, zero data rows against it as of 2026-07-29.
5. **OUTSTANDING. Replay adaptation.** `evaluation/exp40_analysis.py` needs its
   `condition_label = ?` filter widened to accept the eight country codes, and its
   `EXP34` / `EXP34_COND` / `EXP40` constants repointed. The `researcher_only`
   attempt-1 query needs the same treatment. Unit-test the adapted replay against
   the known arm A yield of 526 commits before trusting it.
6. **OUTSTANDING. Seed-count preflight.** Assert 392 total seed hits, per the country table,
   and abort the dispatch if the count differs.
7. **OUTSTANDING. Dispatch runbook.** Resume-safe launcher plus supervisor, on the EXP-36
   pattern. Detached via nohup or setsid, with 30-minute polling; background
   notifications alone are not sufficient.
8. **Runtime freeze.** Pin the dispatch to a frozen commit. A parallel edit under
   `agents/` voided an EXP-41 replicate and forced a re-run.

## Rules compliance

- **R1** This document and the registry row exist before any data.
- **R2** Identical battery across arms; arms share attempt-1 evidence on the 392
  seeded pairs and share every pinned knob everywhere.
- **R4** Balance-aware, three-outcome endpoints on a battery carrying a real base
  rate (370 negative golds).
- **R8** Statistics fixed above, including the equivalence margin.
- **R9** Cold cache on the live arm, matching EXP-36.
- **R10** Deny-list applied pre-retrieval; committed-evidence audit post-hoc.
- **R11** n fixed at 1,144 before dispatch. No peeking, no stopping early.
- **R12** A negative result is a result. JSONL receipts per call.

## Limitations, disclosed up front

- Arm A is a decision-layer replay of a run from 2026-07-15..17, so it is frozen
  in time relative to the live arm. No dedicated control measures that gap; the
  seeded-vs-unseeded diagnostic is a partial substitute, confounded with
  difficulty. The defence is that drift is symmetric and McNemar tests asymmetry,
  so drift costs power rather than validity.
- Seeding covers 392 of 1,144 pairs, and the unseeded remainder is the harder
  subset by construction.
- The design cannot separate "corroborative stance" from "no arbitration" within
  arm B, because a corroborative architecture has no arbitration role: a
  corroborative check yields an absence of support, not a counter-case for a
  judge to weigh. The comparison is architecture-level and is stated as such.
  This is why the comparator is `no_adjudicator` rather than the full trio.
- Researcher and Verifier are the same model, so a stance swap is a prompt
  difference. Chowdhury et al. (2026) argue heterogeneous role assignment is what
  prevents collusion from shared representations, and Zhu et al. (2026) attribute
  debate gains to agent diversity rather than to the argumentation framework. A
  null here is consistent with both, and is evidence about same-model stance
  swaps, not about adversarial architectures in general.
- Second touch of the frozen held-out set (D47), disclosed above.
- Powered for effects of roughly 3 percentage points and larger. Not a small-effect
  test, and not an equivalence test unless the TOST clears ±0.05.

## Change log

| Date | Entry |
|---|---|
| 2026-07-27 | Pre-registration written. No data collected. Awaiting Benjy's approval and a supervisor call on the second held-out touch. |
| 2026-07-29 | **Build complete, dispatch still blocked.** The three defects this prereg identified were described as fixed on 2026-07-27; an audit found none of the wiring in the code. All three are now built and tested (`83d193a`, `tests/test_exp42_stance.py`, 13 tests). Still no data. **(1) Search direction.** `generate_adversarial_queries` was called unconditionally in `run_verifier`, so the cooperative arm searched for counter-evidence while corroborate step 4 asked for support. `verifier-corroborate` now calls the new `generate_corroborative_queries`. **Deviation from the prereg**, which named `generate_confirmation_probes`: that generator is absence-specific ("the Researcher has answered that some feature does NOT exist"), so it does not apply to a positive claim, and for an absence claim it hunts the positive thing, which is refutation rather than corroboration. Wiring it in would have made arm B search adversarially on every positive answer and refutationally on every negative one. The replacement is a direction mirror of the adversarial generator, same shape-awareness, so the arms still differ by stance alone. **(2) Corroborate V3.** V2's preamble is missing disprove V4's staleness criterion; V3 adds the corroborative mirror, "vague, paraphrased, or out-of-date evidence does not constitute corroboration". Steps 1-3 remain byte-identical to disprove V4, now pinned by test rather than by inspection. **(3) The D47 door.** `heldout_second_touch` did not exist; the only exemption was `headline: true`, which EXP-42 must not claim. A second touch now requires the flag, a non-empty justification, every country held-out, and no headline claim, and the justification is written to the run manifest and the event log so the disclosure survives with the rows. **The spec deliberately does not carry the flag.** Dry-run against the canonical DB with the flag added by hand passes clean at 8 arms / 1,144 pairs / `--no-cache` on every arm / SE last. Adding the flag plus a justification naming the sign-off is the only remaining step, and it is Benjy's and his supervisor's to take. |
