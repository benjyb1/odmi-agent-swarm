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

### Arm C: adversarial, `no_adjudicator`. Live drift control. 200 pairs.

A pre-specified 200-pair stratified subsample (25 per country, drawn by fixed
seed from the 1,144, stratified by ODMI dimension), run live under the arm A
configuration in the same dispatch window as arm B.

Arm C exists because arm A is frozen at the 2026-07-15..17 dispatch window and
arm B runs roughly ten days later. Without arm C, any A-vs-B difference confounds
stance with the web having moved and with run-to-run stochasticity. Arm C measures
that combined nuisance directly: A-vs-C discordance on the same 200 pairs is
drift plus noise with stance held constant, and it is the yardstick the A-vs-B
discordance has to beat. It converts the largest limitation from an assumption
into a measured quantity for about 9% extra spend, which is why it is registered
rather than left optional.

## What is held constant, and what varies

The one intended variable is the Verifier's verdict prompt. Everything below is
pinned identically across arms A, B and C.

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
| Adjudicator | absent in every arm | arm A by replay rule, arm B by construction, arm C by `pipeline_mode` |

| Varies | Arm A / C | Arm B |
|---|---|---|
| Verifier verdict prompt | `verifier-disprove` V4 (`prompt_versions.id=23`) | `verifier-corroborate` V3 (new, see below) |
| Burden of proof | pass unless refuted | pass only if corroborated |
| Verifier search direction | counter-evidence | supporting evidence |

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

### 2. The query generator is shared. DISCLOSED, and it is the fair choice.

`generate_adversarial_queries` (`agents/verifier.py:628-630`) produces the
Verifier's independent search queries in both stances. It is not swapped for the
corroborative arm. Only the verdict prompt differs.

This is deliberate and it is the tighter design: it isolates the variable to the
verdict rule rather than confounding stance with a different search generator. It
does mean the corroborative arm searches with adversarially generated queries and
then judges them under a corroborative burden. An examiner will ask about it, so
the dissertation states it rather than waiting to be asked.

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

EXP-42 is therefore specified as **eight arms, one per country**, each with
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

**Nuisance quantification**, reported before the primary is interpreted:

- Arm A vs arm C on the 200 shared pairs: outcome discordance and label
  discordance, with stance held constant. This is drift plus run-to-run noise.
- The A-vs-B discordance is interpreted against that yardstick.

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
| C (live adversarial control) | 200 | ~610 | ~2,440 | **~10,100** |
| **total** | | | | **~68,000** |

Budget ceiling 80,000 calls, with the orchestrator budget pause as the hard guard.

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

0. **Guard decision and, if approved, the auditable override** described above.
   Nothing else on this list matters until that call is made.
1. **`verifier-corroborate` V3.** Add the corroboration-mirror sentence to the
   preamble in `agents/prompts/verifier.py`, bump `_CORROBORATE_VERSION` to 3,
   insert the `prompt_versions` row. Assert in tests that steps 1 to 3 remain
   byte-identical to disprove V4 and that the new sentence is present.
2. **Spec** `evaluation/specs/exp42_stance_heldout.json`: eight arms, one per
   country, each pinning `seed_experiment_id: "exp36_frozen_headline"` and
   `seed_condition_label: "<CC>"`, plus the full knob set from the held-constant
   table. Pin `max_retries`, `num_queries`, `max_results_per_query` and `strategy`
   explicitly rather than inheriting dispatch defaults, which the EXP-40 spec did
   not do.
3. **Registry row** in `experiments` before any data (R1).
4. **Replay adaptation.** `evaluation/exp40_analysis.py` needs its
   `condition_label = ?` filter widened to accept the eight country codes, and its
   `EXP34` / `EXP34_COND` / `EXP40` constants repointed. The `researcher_only`
   attempt-1 query needs the same treatment. Unit-test the adapted replay against
   the known arm A yield of 526 commits before trusting it.
5. **Arm C subsample.** Fixed-seed stratified draw of 200 pairs, 25 per country,
   written to the spec as an explicit pair list so it is reproducible.
6. **Seed-count preflight.** Assert 392 total seed hits, per the country table,
   and abort the dispatch if the count differs.
7. **Dispatch runbook.** Resume-safe launcher plus supervisor, on the EXP-36
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
- **R9** Cold cache on both live arms, matching EXP-36.
- **R10** Deny-list applied pre-retrieval; committed-evidence audit post-hoc.
- **R11** n fixed at 1,144 before dispatch. No peeking, no stopping early.
- **R12** A negative result is a result. JSONL receipts per call.

## Limitations, disclosed up front

- Arm A is a decision-layer replay of a run from 2026-07-15..17, so it is frozen
  in time relative to the live arms. Arm C measures that gap rather than assuming
  it away, but it measures it on 200 pairs, not all 1,144.
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
