# Results

Working results collation for the ODMI agent-swarm dissertation. Every number
here is computed from the SQLite store or the live portals and is traceable to a
source; provisional and superseded items are flagged inline. Assembled
2026-07-17.

**Provenance and health warnings (read first)**
- EXP-36 numbers come from `phase2_final WHERE experiment_id='exp36_frozen_headline'`
  in the worktree DB `.claude/worktrees/exp36-run/data/odmi.db` (the run finished
  after the last push to `main`, so the canonical checkout does not yet hold these
  rows). Classification uses the project's own `_MATCH_STATUS_SQL`
  (`dashboard/lib/db.py`) and `evaluation/exp36_analysis.py`.
- Model verified as `claude-sonnet-4-6` across all EXP-36 subtrios (researcher,
  verifier, adjudicator). 33 agent rows carry an `unknown` model tag (a tagging
  gap to disclose, not model contamination). No Sonnet-5, no Opus.
- Catalogue numbers are deterministic recomputes from harvested portal metadata;
  ground truth is read only to score, never to compute.
- EXP-28 is Sonnet-5 and superseded; EXP-40 (its Sonnet-4.6 successor) is still
  running. Neither is reported as a headline result. See Section 5.

---

## 1. Evaluation design: development and held-out sets (D47)

**The design rationale.** A country's ODMI score is dominated by its share of
`yes` answers: high-maturity countries answer `yes` to almost everything, while
negative golds (`no` answers) are rare and cluster in the low-maturity tail. Two
consequences:

1. Guessing `yes` on every question reproduces the ODMI ranking, so naive
   accuracy on a high-maturity country measures nothing. The swarm's
   discrimination (can it correctly answer `no`) is only visible where negative
   golds exist, which is the low-maturity tail.
2. Negative golds are scarce and clustered. Binary no-share runs from 85%
   (Bosnia) to 0% (Lithuania); the usable negative-gold counts sit in the Western
   Balkans and accession states.

So the binding property of an evaluation set is negative-gold density, not grid
coverage.

**Why stratified, not random.** The quantity that carries the dissertation (the
false-positive and true-negative rates) is a rare-event quantity concentrated in
a few countries. A random country draw would be dominated by all-`yes` countries,
so the false-positive estimate would be unmeasurable or very wide. The design is
class-stratified (case-control style) sampling that oversamples the rare negative
class, with the inclusion rule pre-registered.

**Development set (in-sample, five countries; tuning only, never the headline).**
Chosen to span the regimes the pipeline is optimised against:

| Country | Binary no-share | Regime |
|---|---|---|
| Netherlands | 22% (balanced) | well-resourced, thick web |
| Malta | 31% (balanced) | low-resource English + Maltese; already burned as EXP-6/9/10 primary |
| Norway | 8% (degenerate) | well-resourced, existing dev trails |
| France | 1% (degenerate) | well-resourced, legacy D4 sandbox |
| Albania | 23% (balanced) | Albanian low-resource, thin web |

**Held-out evaluation set (eight countries, frozen, pre-registered rule).**
Selected before any headline run by an auditable rule:

- **Stratum A** (low/mid-resource language, negative-rich): the four highest
  negative-gold counts among non-major-Western-European languages outside the dev
  set = **BA, MK, ME, BG**.
- **Stratum B** (higher-resource language, as balanced as available): the four
  highest no-share well-resourced-language countries outside the dev set =
  **FI, HR, SE, BE**.

This yields ~368 binary negative golds (261 in A, 107 in B), all four ODMI
dimensions, all five answer shapes, across ~1,144 (question, country) pairs. The
A/B contrast replaces the matrix's language axis: a flat false-positive rate
across A and B means language drives abstention not error (the RQ3 prediction);
a rise in A is the headline negative result.

**Freeze protocol.** The pipeline (prompt versions and knob settings) is committed
before the eval runs; the commit SHA is the lock. The held-out eight are untouched
by any experiment until the frozen headline run, so the estimate is read exactly
once. (Exposure history: earlier held-out reads EXP-21 and EXP-31 were voided per
D57; EXP-36 under the D64 fresh pre-registration is the clean read.)

**France stays in the report as a labelled degenerate-baseline contrast** (1% no)
to show empirically why raw accuracy is the wrong metric.

---

## 2. EXP-36: frozen held-out headline run

Single frozen production configuration, Sonnet-4.6, on the eight D47 held-out
countries. n = **1,144** true distinct (question, country) pairs (1,151 raw rows;
7 re-dispatch duplicates removed; all tables use the strict 1,144 set).

### 2.1 Data funnel (n = 1,144)

| Stage | Count | Rate |
|---|---|---|
| Finalised | 1,144 | - |
| Committed (real answer) | 636 | 0.556 coverage |
| Abstained | 508 | 0.444 |
| Agent failure | 0 | 0 |

Terminal status: accepted_by_verifier 526 · accepted_by_adjudicator 205 ·
abstained_adjudicator 413. Committed = 526 verifier + 110 adjudicator. Abstained
= 413 hard-abstain + 95 adjudicator-accepted-but-`inconclusive`.

Of the 636 committed: match 437 · differ 176 · near_match 10 · flag_review 13 ·
no_ground_truth 0 (ground truth complete).

### 2.2 Headline metric and baselines

- **Commit accuracy = 437 / 623 = 0.701** (scoreable committed; `near_match` in the
  denominator, not the numerator; Wilson 95% ~ [0.665, 0.737]). Matches / all
  committed = 437/636 = 0.687.
- **Always-yes baseline (base rate):** binary golds n = 907 (yes 539, no 368),
  positive base rate = **0.594**.
- **Balance-aware:** raw all-pairs accuracy 385/907 = 0.425 (below the 0.594
  floor, because coverage is only 0.556); balanced accuracy 0.396; **Youden's J =
  -0.208** (driven by weak no-gold recall).
- Calibration: ECE = 0.062 (n_scored = 628).

Reading: commit accuracy ~0.70 is a lower bound pending a D22 staleness review of
the 176 differ rows. But balance-aware the run does **not** beat the always-yes
baseline, because it abstains ~44% and its negative-gold recall is weak. The
headline is the balance-aware picture, not the 0.70.

### 2.3 By ODMI dimension

| Dimension | n | committed | commit_acc | abstention | neg-gold FP |
|---|---|---|---|---|---|
| Portal | 360 | 189 | **0.784** (145/185) | 0.475 | 0.132 (15/114) |
| Quality | 232 | 99 | 0.707 (70/99) | 0.573 | 0.188 (9/48) |
| Policy | 248 | 184 | 0.686 (120/175) | **0.258** | **0.500** (33/66) |
| Impact | 304 | 164 | 0.622 (102/164) | 0.461 | 0.264 (37/140) |

Rank: Portal > Quality > Policy > Impact. Policy commits the most (lowest
abstention) but has the worst negative-gold false-positive rate: half its no-golds
are committed wrong.

### 2.4 By country (n = 143 each)

| Country | Stratum | committed | abstained | match | differ | commit_acc |
|---|---|---|---|---|---|---|
| BE | B | 79 | 64 | 64 | 13 | 0.821 (64/78) |
| FI | B | 106 | 37 | 84 | 20 | 0.800 (84/105) |
| SE | B | 101 | 42 | 77 | 21 | 0.770 (77/100) |
| BG | A | 61 | 82 | 42 | 16 | 0.724 (42/58) |
| HR | B | 77 | 66 | 50 | 24 | 0.667 (50/75) |
| ME | A | 83 | 60 | 50 | 27 | 0.610 (50/82) |
| BA | A | 55 | 88 | 32 | 21 | 0.604 (32/53) |
| MK | A | 74 | 69 | 38 | 34 | 0.528 (38/72) |

### 2.5 Per-class (committed binary golds)

| Class | Gold total | committed | correct | committed-conditional rate | all-gold recall |
|---|---|---|---|---|---|
| Yes-golds | 539 | 339 | 295 | TPR 0.870 | 0.547 |
| No-golds | 368 | 184 | 90 | TNR 0.489 | 0.245 |

- **Negative-gold false-positive rate** (committed `yes` on a `no` gold): 94 wrong
  = **0.255 over all 368 no-golds** (0.511 over the 184 committed no-golds). The
  system is strongly yes-biased when it commits on a negative gold.

### 2.6 Abstention

Overall 508/1,144 = **0.444**. Per dimension: Policy 0.258 · Impact 0.461 ·
Portal 0.475 · Quality 0.573.

### 2.7 By ODMI decision (self-report handling)

| decision | n | committed | commit_acc | neg-gold FP |
|---|---|---|---|---|
| complement | 173 | 113 | 0.830 (93/112) | 0.429 (3/7) |
| confirm | 716 | 383 | 0.728 (273/375) | 0.198 (47/237) |
| change | 255 | 140 | **0.522** (71/136) | 0.355 (44/124) |

### 2.8 Stratum A vs B (the RQ3 confirmatory contrast)

| Metric | Stratum A (lower-resource) | Stratum B (higher-resource) | p |
|---|---|---|---|
| commit_acc | 0.609 | 0.771 | < 0.001 |
| abstention | 0.522 | 0.363 | < 0.001 |
| neg-gold FP | 0.225 | 0.336 | 0.027 |

Abstention rises and commit accuracy falls in the lower-resource stratum, but the
negative-gold false-positive rate does **not** rise in A (it is lower). Consistent
with the RQ3 prediction that language drives abstention, not fabricated error.

### 2.9 EXP-36 caveats
- Commit accuracy is a lower bound pending the D22 staleness band on the 176
  differ rows (blind adjudication over frozen evidence, upper bound excludes
  confirmed-stale golds).
- 33 agent rows have an `unknown` model tag (tagging gap; no other model string
  exists in the run).
- Strict 1,144-pair set used; the analysis pack's 1,149 (keyed on
  `condition_label`) inflates by 5 phantom re-dispatch pairs; the deltas are
  < 0.001.

---

## 3. Deterministic catalogue recompute

Nine Quality questions (Q12, Q13, Q16-18, Q21, Q22, Q25, Q27) are computed
directly from harvested national-catalogue metadata, no LLM. Each row scores the
nine against ODMI: Exact = same band, Near-match = adjacent band, Differ = two or
more bands off.

### 3.1 Full catalogue breakdowns

| Country | Datasets assessed | Exact | Near-match | Differ |
|---|---|---|---|---|
| France | 74,624 (full) | 4 | 1 | 4 |
| Sweden | 23,305 (full) | 4 | 3 | 2 |
| Netherlands | 20,772 (full) | 5 | 0 | 4 |
| Romania | 5,143 (full) | 3 | 3 | 3 |
| Croatia | 3,867 (full) | 2 | 1 | 6 |
| Finland | 2,525 (full) | 7 | 1 | 1 |
| Hungary | 2,282 (full) | 8 | 1 | 0 |
| Montenegro | 898 (full) | 5 | 4 | 0 |
| Albania | 130 (full) | 8 | 1 | 0 |

### 3.2 Partial and zero coverage

**Partial:**
- **Germany** - 3,000 (sample only; full catalogue ~151k not harvested). Sample
  breakdown 4 / 2 / 3.

**Zero (no harvestable national catalogue):**
- **Estonia** - API returns 403 Forbidden to the harvester.
- **Bulgaria** - portal geo/IP-blocks the harvest network (Apache 403 on every path).
- **North Macedonia** - server unreachable (TCP timeout on every path).
- **Belgium** - Drupal HTML only; no CKAN / data.json / JSON:API / DCAT export / SPARQL.
- **Bosnia** - only a 43-dataset single-agency .NET portal (IDDEEA), no DCAT-AP graph; not a national catalogue.

Common wall: the machine-readable DCAT-AP for BG/BE/MK exists only on
data.europa.eu, which is deny-listed under D24 as the leakage source. The rule
that protects the evaluation also forecloses a deterministic recompute for
aggregator-only countries. Catalogue-recomputability correlates with maturity.

### 3.3 Completeness verification (harvested vs portal's own reported total)

| Country | Portal reports | Harvested | Coverage |
|---|---|---|---|
| Montenegro | 898 | 898 | 100% (exact) |
| Hungary | 2,282 | 2,282 | 100% (exact) |
| Sweden | 23,305 | 23,305 | 100% (SPARQL COUNT) |
| Croatia | 3,867 | 3,867 | 100% (SPARQL COUNT) |
| Albania | 129 | 130 | complete |
| France | 74,925 | 74,624 | 99.6% |
| Netherlands | 20,852 | 20,772 | 99.6% |
| Romania | 5,189 | 5,143 | 99.1% |
| Finland | 2,552 | 2,525 | 98.9% |

Gaps are not missed pages: NL/RO/FI/HU are June snapshots and the portals have
grown ~30-80 datasets since; France lost 3 of 750 pages to a malformed literal
(~300 datasets, 0.4%, fixable). Albania genuinely holds ~129 datasets (thin
estate), not a harvest failure.

### 3.4 Computation confidence

- Independent check, Montenegro Q12 (licence presence): tool 679/898 (75.6%) vs
  the portal's own CKAN facet 706/898 (78.6%). ~4% undercount from DCAT
  field-mapping, but both fall in the same band (71-90%), so the verdict is
  unchanged. The **band is robust to a few-percent counting difference; exact
  counts carry field-mapping noise**, which only bites near a band boundary.
- SHACL conformance (Q16/17/18) is computed on a <=1,000 evenly-spaced sample even
  for full catalogues.
- Field-mapping fidelity: a portal that encodes a field unusually reads as a false
  low. Croatia's 0% licences and 0% download-URLs are genuine, registry-documented
  portal gaps, not harvest bugs, but they illustrate the mechanism.
- Non-independence: the Verifier recompute runs the same code against the same
  snapshot, so nothing independently checks the harvest/computation itself.
- Methodology gap vs ODMI: ODMI's numbers come from data.europa.eu's MQA, a
  different DCAT-AP profile harvested at a different time; a differ/near is a flag
  to inspect, not proof either side is wrong.

Net: high confidence the harvests are essentially complete (verified per country);
moderate-high confidence in the band verdicts, with real uncertainty on
near-boundary cells and per-portal field mapping.

### 3.5 The two harvest bugs fixed (branch `dissertation-section-3-architecture`)

Both were silently corrupting RDF-route results:
1. **Malformed-IRI crash.** One malformed URL (an accessURL with an embedded
   space) crashed the page serialiser, and the harvest caught it as a partial
   harvest. Croatia went from a truncated 1,400 to the full 3,867. Fix: drop the
   malformed triple before serialising.
2. **Blank-node canonicalisation blow-up.** `to_canonical_graph` took ~109s per
   Sweden page (~230 blank nodes; worst-case exponential), so a 233-page harvest
   needed ~7h of CPU. This is the long-standing "SE SPARQL hang." Fix: skip
   canonicalisation above 40 blank nodes; 109s dropped to 0.04s and Sweden
   harvested full in minutes.

Divergences within France and Romania (self-report >90% vs recompute 51-70%) are
the strongest ODMI-is-wrong evidence in the project, because the recompute is
deterministic and reproducible.

---

## 4. Netherlands false-positive audit

Each NL committed binary false positive (swarm `yes`, gold `no`) is adjudicated
over the frozen stored evidence to separate genuine swarm error from
self-report/definitional mismatch. n = 22.

| Audit | Method | Result |
|---|---|---|
| Main (Opus) | gold shown, frozen evidence | 20 definitional-gap · 1 genuine error · 1 defensible/stale-gold |
| Adversarial | best-case-for-swarm steelman | **0 clean swarm wins** · 11 swarm-over-read · 11 ambiguous |
| Sonnet cross-check | as main | 17 definitional-gap · 2 error · 3 defensible |

ODMI's own decision on the 22 golds: 20 confirm, 2 change.

Reading: the NL false positives are **not** wholesale ODMI errors. Under
adversarial adjudication zero vindicate the swarm cleanly; the honest count is ~1-3
of 22 defensible, the rest measurement mismatch (the swarm reads the live portal
and answers `yes`; the gold encodes the country's self-reported internal practice)
or over-reads. This is the counterweight to the catalogue ODMI-is-wrong evidence:
on the LLM path the swarm is not vindicated wholesale.

---

## 5. Architecture / verification-mode experiments

**Research question:** does the adversarial-verifier design earn its place against
a single retrieval agent and against a cooperative alternative?

### 5.1 EXP-40 cooperative contrast (current, Sonnet-4.6) - IN PROGRESS

`exp40_cooperative_contrast`: a cooperative pipeline mode (corroborate V2,
consensus commit, no adjudicator) contrasted against the adversarial baseline,
seeded from EXP-34 `wide_only`, on the 156-pair dev battery (MT + NL + AL),
Sonnet-4.6. Dispatched 2026-07-17; ~1 of 156 finalised at time of writing.
**Results pending.** This is the rule-compliant replacement for the EXP-28 ladder.

### 5.2 EXP-28 architecture ablation - SUPERSEDED (Sonnet-5, not a headline)

`exp28_arch_ablation` ran the marginal-utility ladder (researcher-only -> +verifier
-> +adjudicator) on **Sonnet-5**, which the project rule excludes from any
reported result. It is superseded by EXP-40. Recorded here only as design history:
the ladder's paired McNemar comparisons were underpowered (all Holm-adjusted
p = 1.0) on the small overlapping committed sets. The only Sonnet-4.6 architecture
point that exists is the full trio via EXP-29 (n = 44), not the ablation arms. No
Sonnet-5 numbers are carried into this file.

---

## Appendix: open items and disclosures
- EXP-36 result rows live in worktree DBs, not yet on `main`; canonical analysis
  code is `evaluation/exp36_analysis.py` (worktree `compassionate-hypatia-d07df0`).
- Catalogue harvest fixes are on branch `dissertation-section-3-architecture`,
  uncommitted to `main` at time of writing.
- Statistical power: at n ~ 50-150 per stratum only large effects are detectable;
  null comparisons should read as "no large effect detected."
- Multiplicity: ~12 adopt/reject calls across the experiment programme; treat
  individual p-values accordingly.
- Data-leakage: the deny-list blocks direct copy; memorised priors can still steer
  query generation and label choice (closed-book baseline cb_20260709 bounds this:
  match 0.493, below the 0.681 always-yes floor, so no answer-key memorisation).
