# EXP-7: Retry chaining / evidence accumulation (pre-registration)

Pre-registered 2026-06-03, in the spirit of `EXPERIMENTS_VERIFIER.md` and under
the universal rules in `EXPERIMENTS_PROTOCOL.md` section 0 (R1 to R12). This file
fixes the design of the chaining experiment **before** the run, so the result
cannot be reverse-fitted to a hypothesis. The git commit that adds this file, and
the commit that adds the chained code path it governs, are the pre-registration
record; their timestamps predate any result file. SPEC D32 to D37 define the
current independent-retry loop this experiment treats as its baseline.

The chained code path is built and committed in the same change as this file but
is gated behind a flag (`--chained`) that defaults off, so production and the
EXP-8 / EXP-9 baseline are byte-identical to the pre-EXP-7 loop. The Malta
dispatch is now done and the run is no longer quota-gated (20x plan). As of
2026-06-09 EXP-7 is reframed from a confirmatory "does chaining help" test to a
chaining-optimisation target (see `EXPERIMENTS.md`); this pre-registration and
the `--chained` code stand as the starting point.

---

## 1. Question

Up to eight calls run per pair (four Researcher, four Verifier across the retry
budget), but today they are independent shots. The Verifier searches the web
every round and often finds real counter-evidence, then the loop keeps only its
verdict and bins the evidence. The Researcher on retry 3 does not know what the
Verifier turned up on rounds 1 and 2. The calls are spent and the findings are
thrown away (SPEC D33 carries queries and the rejection reason forward, D34
persists snippets, D37 applies the commit-confidence floor, but no round sees the
evidence the earlier rounds gathered).

- **Primary question.** Does chaining the evidence across the retry loop recover
  more correct answers per call than today's independent retries, **without
  raising the false-positive rate** (a committed answer that is wrong)?
- **Pre-registered hypothesis (H1, directional).** The chained arm's balanced
  accuracy on Malta is greater than or equal to the baseline arm's, at no worse a
  committed-but-wrong rate, for the same or fewer calls per resolved pair. A
  result that buys recovery by committing more false positives is a **failure of
  the hypothesis**, not a partial win, and is reported as such.

## 2. The two conditions

Both arms run the identical Coordinator state machine. The only difference is the
`--chained` flag, so any difference in outcome is attributable to chaining and
not to a different loop, model, or prompt.

- **`baseline` (control).** The current loop (SPEC D32 to D37). Each retry is a
  fresh Researcher shot carrying only the Verifier's verdict, the rejection
  reason, and a diverging query (D33). The Adjudicator weighs the per-attempt
  summaries. The commit-confidence floor (`COMMIT_CONFIDENCE_FLOOR = 0.65`, D37)
  and honest abstention apply.
- **`chained` (treatment).** Three changes, all behind the flag:
  1. On retry, the Verifier's counter-evidence (its `counter_evidence_quote` and
     `counter_source_url`) is fed back into the `ResearcherInput`, not just the
     verdict and a suggested query.
  2. An evidence corpus accumulates across rounds (the snippets the Researcher
     read and the Verifier's independent snippets, both already persisted under
     D34) and is carried forward, so each round sees everything found so far.
  3. The Adjudicator synthesises over the whole corpus, committing only above the
     D37 floor and returning `inconclusive` otherwise.

  The D37 floor and the abstention rules are **unchanged** in the chained arm. The
  treatment adds evidence to what each call sees; it does not relax the commit
  bar. This is the control that lets a recovery gain be read as better evidence
  use rather than a lower threshold.

System prompts and registered prompt versions are identical across the two arms:
the carried evidence and its using-instruction travel in the per-call user
message, not the system prompt, so the `prompt_versions` rows do not move and the
two arms are distinguished only by `condition_label` and the `--chained` flag.

## 3. Endpoints (balance-aware, per R4)

Read balance-aware because Malta's binary gold is skewed (68 `yes` / 30 `no`, a
69% majority baseline; `EXPERIMENTS_PROTOCOL.md` section 0). Raw recovery alone
cannot be told apart from majority-class guessing, the D35 / D37 lesson, so the
headline is the per-class pair, not a single accuracy number.

- **E1, recovery (primary, balance-aware).** The finalised answer joined to the
  ODMI `ground_truth` row and classified `match` / `near_match` / `differ` /
  `no_ground_truth` by `_MATCH_STATUS_SQL` (`dashboard/lib/db.py`). Reported as
  **balanced accuracy** and the **per-class rates** (catch rate on the `no`-gold
  minority, accuracy on the `yes`-gold majority), with the 69% Malta majority
  baseline printed beside it (R4(a)). A figure that does not clear the baseline is
  not a result.
- **E2, false-positive rate (the co-primary, the whole point).** The share of
  **committed** pairs (terminal status accepted, not abstained) whose committed
  answer differs from the ODMI gold. This is the number the experiment exists to
  protect: chaining must not raise it. Reported per arm with a Wilson 95%
  interval. The `no`-gold pairs are where a false `yes` shows up, so Malta's 30
  `no` golds are deliberately retained in the sample.
- **Abstention rate.** The share of pairs ending `inconclusive` /
  `escalate_human`. An honest abstention is not a false positive; a treatment that
  recovers answers by converting abstentions into **correct** commits is the win,
  one that converts them into **wrong** commits is the failure E2 catches.
- **Calls per resolved pair (efficiency).** Total Claude calls (query-gen + main,
  across Researcher / Verifier / Adjudicator) divided by resolved pairs, from
  `claude_usage_log`, per R9. "Recovers more correct answers **per call**" is the
  framing; a chained arm that recovers the same answers but costs more calls is
  reported as that trade, not as a win.

The four are reported together. The confirmatory claim is the **joint** one:
balanced-accuracy non-decrease (E1) at a non-increased false-positive rate (E2).
Calls per resolved pair and abstention rate are secondary, reported alongside.

## 4. Design: paired, same pairs both arms

- **Paired (R2).** Both arms run the **identical** Malta pair set. A difference is
  then attributable to chaining, not to an easier pair. The pair is the unit.
- **Same models, strategy, provider, retry budget.** Only `--chained` varies. The
  Verifier strategy is the production default (`verifier-disprove`) unless the
  EXP-6 result has by then named a better one, in which case the same strategy is
  used in both arms and the choice is recorded with the result.
- **No DB-state leakage between arms.** The two arms are dispatched as separate
  `condition_label`s (`baseline`, `chained`) under one `experiment_id`. The
  resume path (`_find_resumable_researcher`) is disabled or scoped so a baseline
  Researcher row is never reused by a chained run or vice versa; verified before
  the run.
- **Cold cache (R9).** Both arms start cold with DIY caching off (`--no-cache`),
  so neither inherits the other's free SERP/snippet hits and the calls-per-pair
  figure is honest. The chained arm naturally re-reads more (it carries a corpus),
  which is exactly what the per-pair cost endpoint should capture.
- **Temperature 0**, unchanged.

## 5. Items and sampling

- **Country: Malta primary (R4(c)).** Malta is the base-rate-balanced,
  well-resourced-language pick: English is an official language so a poor result
  is the pipeline's doing and not a language artefact, and about 30 binary
  questions carry a `no` gold so a false `yes` can occur. France (99% `yes`) is
  **barred** as the primary set: a recovery number there cannot be told apart from
  majority-class guessing (the explicit D35 / D37 / R4 lesson). **Netherlands** is
  the secondary check (Dutch, well-resourced, 78% majority baseline) if its
  dispatch lands. The lower-resource `no`-heavy countries (BA, MK, ME, BG, IS) are
  deferred to a follow-on so a poor result there is not blamed on language.
- **Sample (R3).** The Malta finalised pairs, stratified by ODMI dimension,
  round-robin, RNG **seed 20260603**, selected pair IDs written into the results
  JSONL so the draw is reproducible and verifiably not post hoc. Target ~40 pairs
  across the four dimensions, with the `no`-gold pairs deliberately retained.
  Achieved per-stratum and per-class counts reported with the result. The Quality
  dimension is kept here (unlike the search experiments) because chaining is about
  the retry loop, not web retrieval; catalogue-computed Quality answers (D30) do
  not retry, so they neither help nor hurt either arm and are reported separately.
- **Both arms see the identical pair set.** No pair is hand-picked; no pair is
  dropped from one arm only.

## 6. Statistics (fixed in advance, R8)

- **Proportions** (balanced accuracy, the two per-class rates, false-positive
  rate, abstention rate): point estimate with a **Wilson score 95% interval**. The
  interval, not the point, is the result.
- **Primary comparison (paired accuracy).** Recovery is a paired binary outcome
  per pair (did the arm's committed answer match the gold). The chained-vs-baseline
  difference is tested with **McNemar's exact test** on the discordant pairs.
  Discordant counts always reported.
- **False-positive comparison.** The committed-but-wrong indicator is paired per
  pair across arms; **McNemar's exact test** on the discordant pairs, reported
  with the raw per-arm rates and their Wilson intervals. The pre-registered
  decision rule: chaining is adopted only if it does **not** raise the
  false-positive rate (the upper bound of the chained-minus-baseline difference
  does not exceed a small margin, fixed here at **0.05**, the same
  decision-rule discipline as the EXP-1 non-inferiority margin).
- **Calls per resolved pair (paired, skewed, small n):** **Wilcoxon signed-rank**
  on the per-pair call count, chained vs baseline; median delta and IQR reported.
- **One confirmatory primary.** The joint claim (balanced-accuracy non-decrease at
  a non-increased false-positive rate). Per-dimension and per-class splits are
  **secondary and exploratory**, Holm-corrected within the secondary family before
  any claim.
- **Stopping rule (R11).** Fixed sample. If the Claude quota is exhausted mid-run,
  the partial is reported as partial with the achieved n; no pair is selectively
  re-run to move a number. Results stream to JSONL so a partial is analysable.

## 7. Impartiality threats and controls

| Threat | Control |
|---|---|
| Pair difficulty varies | Paired (R2): both arms see the identical Malta pair set. |
| Base-rate flatters always-`yes` | Balanced accuracy and per-class rates as headline, not raw accuracy; Malta primary per R4(c); 69% majority baseline printed beside every figure (R4(a)). |
| Recovery confounded with guessing | The false-positive co-primary (E2) on the `no`-gold pairs: a chained arm that recovers by guessing `yes` more raises E2 and fails the joint claim. |
| Chaining lowers the commit bar by stealth | The D37 floor and abstention rules are **identical** across arms; the treatment only changes what each call sees. Verified in code (the chained flag does not touch `COMMIT_CONFIDENCE_FLOOR` or `_should_accept_verifier_pass`). |
| Prompt-version drift between arms | System prompts unchanged; carried evidence travels in the user message, so `prompt_versions` rows are identical across arms. |
| Cache reuse inflating one arm's thrift | Both arms cold-cache (R9); the corpus-carrying arm's extra reads are captured by calls-per-pair, not hidden. |
| Cross-arm DB-state leakage | Separate `condition_label`s under one `experiment_id`; resume path scoped so no row crosses arms. Verified before the run. |
| ODMI gold one cycle stale (D22) | A `differ` may be a stale-gold disagreement, not a swarm error; each disagreement gets a human glance and the caveat is reported, the same as every other experiment. |
| Country skew | Malta primary, NL secondary; per-class and per-dimension splits reported where n permits. |
| Temperature noise | Temperature 0, unchanged. |

## 8. Honest reporting (R12)

A null or unflattering result is the finding and is reported plainly (CLAUDE.md,
METHODOLOGY.md). "Chaining recovers no more than independent retries", or
"chaining recovers more but commits more false positives", or "chaining helps but
costs more calls per pair", are each the result if the run shows them. Any
coverage bound (the 40-pair cap, a dropped dimension, a quota truncation) is
logged with what it removed. Every finalised pair streams to the DB and the
results JSONL with its raw evidence and the carried corpus, so an examiner can
replay the judgement from logs alone.

## 9. Rules compliance (section 0 self-grade)

| Rule | Met? |
|---|---|
| R1 pre-register before data | Yes: this file and the gated code predate any result file. |
| R2 pair within the item | Yes: identical Malta pair set across both arms. |
| R3 sample by a fixed rule | Yes: dimension-stratified, seed 20260603, IDs logged. |
| R4 refuse a degenerate sample | Yes: Malta primary, balance-aware endpoints, 69% baseline reported. |
| R5 / R6 judge controls | n/a: no LLM evidence-quality judge here (the endpoint is accuracy vs ODMI gold, not a head-to-head). |
| R7 break a confound | Yes: the false-positive co-primary breaks the recovery-vs-guessing confound. |
| R8 fix statistics first | Yes: Wilson, McNemar (×2), Wilcoxon, one confirmatory joint primary. |
| R9 cost per item, retries counted, cold cache | Yes: calls per resolved pair, both arms cold. |
| R10 deny-list before retrieval | Yes: inherited from the shared search path, unchanged by chaining. |
| R11 fix the sample, no peeking | Yes: fixed n, partial reported as partial. |
| R12 report the negative, keep receipts | Yes: null is the finding; per-pair JSONL + DB receipts. |

## 10. Registry (D27) and prerequisites

`experiment_id = retry_chaining_mt_v1`, inserted into the `experiments` table
before the run; the registry `conditions` record the two arms (`baseline`,
`chained`) and the target countries (MT primary, NL secondary). Harness: the
existing dispatch path with `--chained` (`scripts/dispatch_subtrios.py` →
`scripts/run_coordinator.py`), tagged with the experiment_id and condition_label.
Result: the finalised pairs in the phase2 tables plus an analysis JSONL under
`evaluation/results/`.

**Prerequisites (pending).**
1. **The Malta dispatch** (the binding one, shared with EXP-6 / EXP-8 / EXP-9):
   target ~30 `no`-gold binary questions plus a matched ~30 `yes`-gold for the
   majority side, dimension-stratified. The `no`-gold candidates do not exist in
   the DB yet. Gated on search quota, the same constraint as the parked D28 Phase
   3 re-dispatch. Do not assume it has run.
2. **An analysis harness** that reads the two `condition_label`s, computes the
   section 6 statistics, and writes the JSONL. **Built and unit-tested**
   (`evaluation/chaining_analysis.py`, `tests/test_chaining_analysis.py`, 15
   cases): a pure layer (PairOutcome classifiers, `arm_summary`,
   `paired_comparison` with paired McNemar on recovery and on the
   committed-but-wrong indicator, Wilcoxon on calls, and a mechanical joint
   verdict against the 0.05 false-positive margin) over a thin DB layer that
   reuses `_MATCH_STATUS_SQL` so recovery is classified exactly as elsewhere.
   Balanced accuracy is reported only when both binary classes are present, so a
   one-class sample cannot be passed off as balance-aware (R4). Committed and
   unit-tested before the run, the same standard as the search experiments
   (`EXPERIMENTS_PROTOCOL.md` section 9).
3. **Resume-path scoping** so no Researcher row crosses arms. **Done.**
   `_find_resumable_researcher` now matches on `experiment_id` and
   `condition_label`, so a chained run cannot inherit a baseline Researcher row
   or vice versa; production (NULL experiment, `baseline`) resumes only its own
   rows, unchanged. Covered by `tests/test_resume_arm_scoping.py` (5 cases).

The two arms are kept apart for **data isolation, not the rate limit**: the resume
path is scoped by `experiment_id` + `condition_label` (requirement 3) so a chained
run cannot inherit a baseline Researcher row, and per-arm cost attribution stays
clean. The shared Claude Max budget is consumed linearly whether the arms overlap
or not, so running them in sequence is a cleanliness choice, not a throughput one
(`EXPERIMENTS_PROTOCOL.md` section 10).

## Change log

- 2026-06-03: created. Pre-registers EXP-7 (retry chaining / evidence
  accumulation), Malta primary, baseline vs chained, balance-aware endpoints with
  the false-positive rate as a co-primary, paired McNemar / Wilcoxon, one
  confirmatory joint claim. The chained code path is committed in the same change,
  gated behind `--chained` (default off) so production and the EXP-8/9 baseline
  are byte-identical. No run at commit time; gated on the Malta dispatch (search
  quota) and Claude headroom.
- 2026-06-03 (later): built the analysis harness
  (`evaluation/chaining_analysis.py`, `tests/test_chaining_analysis.py`),
  pre-run requirement 2, ahead of the run. Pure stats layer over a thin DB layer
  reusing `_MATCH_STATUS_SQL`; the joint confirmatory verdict is computed
  mechanically against the 0.05 false-positive margin. Still gated on the Malta
  dispatch and resume-path scoping (requirements 1 and 3).
- 2026-06-03 (later still): closed requirement 3. `_find_resumable_researcher`
  scoped to its own `experiment_id` + `condition_label` so the two arms cannot
  cross-contaminate via the resume path; `tests/test_resume_arm_scoping.py` (5
  cases). Only the Malta dispatch (requirement 1) now stands between the code and
  the run.
