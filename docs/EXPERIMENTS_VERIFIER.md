# EXP-6: Verifier strategy discrimination (pre-registration)

Pre-registered 2026-06-03, in the spirit of `EXPERIMENTS_PROTOCOL.md`. This file
fixes the design of the Verifier-strategy comparison **before** the run, so the
result cannot be reverse-fitted to a hypothesis. The git commit that adds this
file is the pre-registration record; its timestamp predates the result file it
governs. SPEC D15 defines the four strategies; SPEC D17 commits to revisiting the
Verifier default once the strategies have been compared on real pairs.

---

## 1. Question

The Verifier is a binary classifier over a Researcher candidate answer: **accept
(`pass`)** or **reject (`fail`)**. SPEC D15 names four prompt strategies and the
metrics to compare them on: hallucination catch rate, false rejection rate, and
tokens per run. EXP-6 measures exactly those.

- **Primary question.** Which Verifier strategy best discriminates a *wrong*
  Researcher answer from a *correct* one, per unit of token cost?
- The four arms (SPEC D15, `agents/prompts/verifier.py`):
  `verifier-disprove` (default, sceptical stance), `verifier-negation` (search for
  the opposite label), `verifier-steelman` (build the strongest case, then attack
  it), `verifier-blind` (re-answer without seeing the Researcher, Python compares).

## 2. The Verifier as a signal detector

Ground truth for "was the Researcher right" is the ODMI `ground_truth.response`
for the same (question, country), classified by the same logic as
`_MATCH_STATUS_SQL` (`dashboard/lib/db.py`): exact match, the `yes`-prefix rule,
or an adjacent band. A candidate is labelled:

- **`should_pass`** — the Researcher's answer matches the ODMI gold. A correct
  Verifier returns `pass`.
- **`should_fail`** — the Researcher's answer differs from the ODMI gold,
  including a one-band-off miss (the Verifier prompts already treat an adjacent
  band as a fail, so labelling it `should_fail` is consistent with the apparatus
  under test). A correct Verifier returns `fail`.

The confusion matrix per strategy:

|                | gold = should_fail | gold = should_pass |
|----------------|--------------------|--------------------|
| verdict `fail` | TP (caught error)  | FP (false reject)  |
| verdict `pass` | FN (missed error)  | TN (correct accept)|

- **Catch rate** (sensitivity) = TP / (TP + FN), on the should_fail items.
- **False-rejection rate** (FPR, 1 − specificity) = FP / (FP + TN), on should_pass.
- **Primary endpoint:** **Youden's J = sensitivity + specificity − 1**, fixed
  here before the run. J is the single number that rewards catching errors and
  punishes false rejections symmetrically. A degenerate always-`pass` or
  always-`fail` strategy scores J = 0, which is the point: a strategy that rejects
  everything is not a good Verifier even though its catch rate is 100%.
- **Secondary:** Matthews correlation coefficient (MCC), balanced accuracy, the
  two rates separately with Wilson 95% intervals, per-dimension and natural-only
  splits, and cost.

## 3. Items and sampling

**Retargeted 2026-06-03 to a base-rate-balanced country**, per the universal rule
R4(c) (`EXPERIMENTS_PROTOCOL.md`, section 0). The first design drew its natural
errors almost entirely from France (20 of 21), where the binary gold runs 99%
`yes`. A should_fail class built there is both tiny and tilted to one country, and
a Verifier that waves everything through is barely penalised, so the primary
endpoint would have been measured where false positives can hardly occur. The
primary should_fail source moves to **Malta**: English is an official language, so
a missed error is not a language artefact, and about 30 binary questions carry a
`no` gold, so real Researcher errors on the minority class can actually happen.
**Netherlands** is the secondary test country (Dutch, well-resourced, already in
the pipeline). France and the injected flips are kept as **robustness arms**,
reported separately and never folded into the primary.

Selection is deterministic: RNG **seed 20260603**, stratified round-robin,
selected candidate IDs written into the results JSONL so the draw is reproducible
and verifiably not post hoc.

A **candidate** is a distinct `(question_id, country_code, researcher_answer)`
drawn from `phase2_researcher_runs`. The Researcher's real row supplies the
evidence the Verifier sees (`evidence_quote`, `source_url`, confidences, and the
persisted `search_snippets`). Candidates whose Researcher answer is
`inconclusive`/`not_applicable`, or which have no ODMI gold, are excluded: the
classifier question is only defined on a definite answer with a reference.

1. **NAT-fail-MT (primary should_fail).** Every natural error on Malta: a Malta
   Researcher answer that differs from gold, with the `no`-gold questions covered
   so errors on the minority class are visible. All are taken; none hand-picked.
   **The Malta dispatch (section 8) is now done (60/60 finalised, 2026-06-03), so
   this stratum is populated: the natural Malta errors include 3 no-gold false
   positives (I7, I8-b, PT29) and the yes-gold false negatives, and the primary J
   is now computable once the four-arm judge run is executed.**
2. **NAT-pass-MT (primary should_pass).** A stratified sample of correct Malta
   candidates, round-robin across ODMI dimension, matched in size to NAT-fail-MT.
3. **NAT-NL (secondary).** Natural fail and pass candidates on Netherlands, a
   second balanced country to check the Malta ranking is not Malta-specific. Run
   if the NL dispatch lands.
4. **NAT-fail-FR + INJ-fail (robustness).** The original France-dominated natural
   errors (21: 20 FR, 1 EE) and the injected label-flips (correct binary
   candidates with `yes`/`no` flipped, wrong by construction; FR and EE). These
   already exist in the DB and are the data behind the superseded partial run.
   They are kept as a robustness check: the injected flips remove the
   ODMI-staleness confound, and a strategy ranking that holds across the
   Malta-natural and the injected arms is more trustworthy than one that does not.
   Reported separately, never merged into the Malta primary.

Achieved counts per stratum, country, and dimension are reported with the result.
The Malta dispatch is now done, so the primary NAT-fail-MT / NAT-pass-MT strata
are runnable; the robustness arm (FR/injected) stays labelled robustness-only and
is never merged into the primary J.

## 4. Design: paired, frozen evidence

- **Paired.** All four strategies judge the **identical** candidate set. Strategy
  differences are then attributable to the prompt, not to a different item.
- **Frozen evidence (the key control).** A live Verifier runs its own adversarial
  query-generation and web search, which is non-deterministic and would vary
  between arms. For each candidate the harness runs the substring check, **one**
  query-generation call, and **one** search **once**, then freezes
  `(substring_result, queries, snippets)` and feeds the identical frozen block to
  all four strategy prompts. The only variable across arms is the system prompt.
  This also halves cost (one query-gen + one search shared across four arms) and
  removes search-quota luck as a between-arm confound.
- **Temperature 0** in the LLM wrapper, unchanged. One main call per
  (candidate, strategy).
- **Blind post-processing** is applied exactly as in production
  (`agents/verifier.py`): the blind model never sees the answer, forms its own,
  and Python overrides to `fail` on divergence.
- **No DB pollution.** Results are written only to a JSONL under
  `evaluation/results/`; the harness does not write `phase2_verifier_runs`, so the
  dissertation's headline numbers (D27) are untouched.

## 5. Statistics (fixed in advance)

- Each rate is a proportion: point estimate with a **Wilson 95% interval**. The
  interval, not the point, is the result. Catch rate on the should_fail n;
  false-rejection rate on the should_pass n.
- **Primary comparison.** Youden's J per strategy on the combined set. The
  strategy with the highest J is the candidate default. Because J has no simple
  closed-form CI on a paired design, the head-to-head between strategies is tested
  on the paired **verdict-correct** indicator (did the verdict match the gold
  label) with **McNemar's exact test** on the discordant pairs, **Holm-corrected**
  across the six strategy pairs. Discordant counts always reported.
- **Cost.** Main-call output tokens and wall-clock per (candidate, strategy);
  paired **Wilcoxon signed-rank** for each strategy against the disprove baseline.
  Median delta and IQR reported.
- **Trigger-happiness check.** Raw `pass` rate per strategy reported alongside J,
  so a strategy that buys catch rate by rejecting everything is visible.
- **Stopping rule.** Fixed sample. If the Claude quota is exhausted mid-run, the
  partial is reported as partial with the achieved n; no pair is selectively
  re-run to move a number. Results stream to JSONL so a partial is analysable.

## 6. Impartiality threats and controls

| Threat | Control |
|---|---|
| Question difficulty varies pair to pair | Paired: every strategy sees identical candidates. |
| Search luck differs between arms | Evidence frozen once per candidate, shared across all four arms. |
| Class base-rate flatters always-pass | J / MCC / balanced accuracy as headline, not raw accuracy; catch and false-reject reported separately; pass-rate per strategy shown. Reinforced by R4: the primary should_fail class is sourced from Malta, a base-rate-balanced country, not from yes-heavy France. |
| Cherry-picking items | All natural errors in the target country taken; correct/injected drawn by seeded stratified rule fixed here. |
| ODMI ground truth one cycle stale (D22) | A NAT-fail "error" may be a stale-gold disagreement, not a Researcher error. Mitigated by the INJ-fail stratum (wrong by construction) and reported as the headline NAT caveat; natural-only and injected-only J both reported. |
| Injection artefact | INJ-fail is a specific error type (label contradicts evidence); labelled secondary, reported separately, never folded into the primary headline silently. |
| Country skew | The first design had should_fail FR-dominated (20/21 natural), the breach the retarget fixes: the primary should_fail is now Malta-natural, NL secondary, FR kept only as a robustness arm. Per-country splits reported where n permits. |
| Order / cross-arm leakage | Each strategy is an independent stateless call; no shared context between arms. |
| Multiple comparisons | Six strategy pairs Holm-corrected; primary endpoint (J) fixed before the run. |
| Temperature noise | Temperature 0, unchanged. |

## 7. Honest reporting

A null result ("no strategy beats the default", or "the extra cost of steelman
buys no catch") is the finding and is reported plainly (CLAUDE.md, D17). Every
verdict is written to JSONL with the frozen evidence, so an examiner can replay
the judgement.

## 8. Registry (D27) and the Malta prerequisite

`experiment_id = verifier_strategy_disc_v1`, inserted into the `experiments`
table before the run; the registry `conditions` record the target countries.
Harness: `evaluation/verifier_strategies.py`. Result:
`evaluation/results/verifier_strategies_*.jsonl` plus a summary block.

**Prerequisite (done 2026-06-03).** The primary endpoint needs a Researcher
dispatch on Malta (target ~30 `no`-gold binary questions plus a matched ~30
`yes`-gold for the pass side, dimension-stratified). That dispatch is now done: all
60 canonical pairs finalised (`data/questions/malta_eval_pairs.json`, batches
`exp6_malta` + `malta_baseline`, baseline / no `experiment_id`), with the no-gold
minority class fully covered (the last two, I8-d and PT12, recovered from
`search_empty` once `head_ok` gained a Playwright fallback for the data.gov.mt
Cloudflare 403). The natural
Malta error set for NAT-fail-MT exists in the DB. Netherlands remains optional for
the secondary stratum. The primary J is now computable once the four-arm judge run
is executed; it has not been run yet.

## Change log

- 2026-06-03: created. Pre-registers EXP-6 (four-arm Verifier strategy
  signal-detection, frozen evidence, J primary). No run yet at commit time.
- 2026-06-03 (later): **retargeted to Malta** under the new universal base-rate
  rule (R4, `EXPERIMENTS_PROTOCOL.md` section 0). The primary should_fail class
  was France-dominated (20/21 natural errors) where the binary gold is 99% `yes`,
  so false positives could barely occur; the primary now sources natural errors
  from Malta (English official, ~30 `no` binary golds), with Netherlands secondary
  and France plus the injected flips kept as a robustness arm. This change
  predates the full run. The earlier partial run on the France/injected set
  (committed at 3 of 89, extended to ~40 of 89 in working state) is **superseded
  as the primary** and retained only as robustness-arm data, not deleted. Harness
  strata updated in `evaluation/verifier_strategies.py` to match. Primary J is not
  computable until the Malta dispatch lands (pending search quota).
