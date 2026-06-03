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

Three strata, fixed before the run. Selection is deterministic: RNG **seed
20260603**, stratified round-robin, selected candidate IDs written into the
results JSONL so the draw is reproducible and verifiably not post hoc.

A **candidate** is a distinct `(question_id, country_code, researcher_answer)`
drawn from `phase2_researcher_runs`. The Researcher's real row supplies the
evidence the Verifier sees (`evidence_quote`, `source_url`, confidences, and the
persisted `search_snippets`). Candidates whose Researcher answer is
`inconclusive`/`not_applicable`, or which have no ODMI gold, are excluded: the
classifier question is only defined on a definite answer with a reference.

1. **NAT-fail (primary, scarce class).** Every distinct natural error: a
   Researcher answer that differs from gold. The DB holds **21** (20 FR, 1 EE).
   All are taken; none are hand-picked.
2. **NAT-pass (primary).** A stratified sample of correct Researcher candidates,
   drawn round-robin across country and ODMI dimension to cover all five
   countries present (FR, EE, DE, NL, RO) and all four dimensions. Target ~45.
3. **INJ-fail (secondary, controlled).** A counterfactual error stratum: take
   correct binary candidates and flip the stated answer (`yes`↔`no`) while
   leaving the evidence intact. The candidate is then wrong **by construction**,
   which removes the ODMI-staleness confound that clouds NAT-fail, and balances
   the should_fail class. Restricted to binary questions; FR and EE only (the two
   countries with enough binary candidates). Target ~20. Labelled secondary and
   reported separately, because a flipped label is a specific error type
   (stated answer contradicts the cited evidence), not a random draw from the
   real error distribution.

Combined target ≈ 86 candidates (≈41 should_fail, ≈45 should_pass). Achieved
counts per stratum, country, and dimension are reported with the result.

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
| Class base-rate flatters always-pass | J / MCC / balanced accuracy as headline, not raw accuracy; catch and false-reject reported separately; pass-rate per strategy shown. |
| Cherry-picking items | All 21 natural errors taken; correct/injected drawn by seeded stratified rule fixed here. |
| ODMI ground truth one cycle stale (D22) | A NAT-fail "error" may be a stale-gold disagreement, not a Researcher error. Mitigated by the INJ-fail stratum (wrong by construction) and reported as the headline NAT caveat; natural-only and injected-only J both reported. |
| Injection artefact | INJ-fail is a specific error type (label contradicts evidence); labelled secondary, reported separately, never folded into the primary headline silently. |
| Country skew | should_fail is FR-dominated (20/21 natural). Per-country splits reported where n permits; FR-dominance named as the headline limitation, consistent with the project's France-first baseline (D4). |
| Order / cross-arm leakage | Each strategy is an independent stateless call; no shared context between arms. |
| Multiple comparisons | Six strategy pairs Holm-corrected; primary endpoint (J) fixed before the run. |
| Temperature noise | Temperature 0, unchanged. |

## 7. Honest reporting

A null result ("no strategy beats the default", or "the extra cost of steelman
buys no catch") is the finding and is reported plainly (CLAUDE.md, D17). Every
verdict is written to JSONL with the frozen evidence, so an examiner can replay
the judgement.

## 8. Registry (D27)

`experiment_id = verifier_strategy_disc_v1`, inserted into the `experiments`
table before the run. Harness: `evaluation/verifier_strategies.py`. Result:
`evaluation/results/verifier_strategies_*.jsonl` plus a summary block.

## Change log

- 2026-06-03: created. Pre-registers EXP-6 (four-arm Verifier strategy
  signal-detection, frozen evidence, J primary). No run yet at commit time.
