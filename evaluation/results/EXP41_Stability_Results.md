# EXP-41 — Run-to-run stability of the ODMI agent swarm

**Completed 23 July 2026.** Three fresh dispatches of the incumbent trio over the
156-pair development battery, one frozen configuration, nothing seeded or
replayed, search cache purged cold before each run.

- Pre-registration: `docs/EXPERIMENTS_RUN_STABILITY.md` (decision D65)
- Machine result: `evaluation/results/exp41_analysis.json`
- Runtime fingerprint held byte-identical across all three runs: `272db6b28e88`

---

## 1. What the experiment measures

The §2.2 Reproducibility criterion sets two conditions: a record complete enough
to repeat a run, and evidence that a repeat returns the same answers. A
generative assessor cannot satisfy the second by argument, because it samples
from a range of outputs, so it has to be run more than once and measured. §4.7
left this open; EXP-41 closes it. It also gives §4.2 an empirical noise floor
for its ablation ladder, which that section could previously only bound with
overlapping Wilson intervals.

Three replicates, not two: two runs give a pairwise agreement rate and nothing
else, while three give unanimity, separate a consistently unstable pair from one
flaky run, and are the minimum for any variance estimate.

## 2. Configuration (identical across all three runs)

`claude-sonnet-4-6` for researcher / verifier / adjudicator / picker · DIY
search · `wide_only` retrieval · 5 results per query · 3 queries · 3 retries ·
bilingual queries · adversarial verifier, counter-search always · standard
adjudicator selection · full researcher prompt · abstention floor 0.65 · trio
pipeline · cold cache (`no_cache`). No attempt-1 seed. Generated from a single
frozen-knob dictionary so no setting could drift between runs.

## 3. What ran

| replicate | finalised | dropped pairs (all benign Albanian search stalls) |
|---|---|---|
| rep1 | 155 / 156 | PT16:AL |
| rep2 | 154 / 156 | PT38:NL, PT9:NL |
| rep3 | 151 / 156 | Q4:AL, Q8:AL, Q11:AL, Q15:AL, Q23:AL |

Each run completed gate-clean. The dropped pairs are non-returning-search
stalls, disclosed and excluded. **The analysis runs on the three-way
intersection: 148 pairs present in all three runs.**

## 4. Result against the pre-registered bars

| # | Metric | Value (95% CI) | Bar | Verdict | Predicted |
|---|---|---|---|---|---|
| M1 | Outcome unanimity | **0.703** [0.625, 0.770] | ≥ 0.80 | **miss** | miss |
| M1 | Fleiss' κ (3 raters, 3 categories) | **0.654** [0.563, 0.735] | ≥ 0.60 | **clear** | — |
| M2 | Commit-rate range across runs | **0.054** (sd 0.022) | ≤ 0.10 | clear | clear |
| M2 | Commit-accuracy range | 0.014 | — | — | — |
| M3 | Label unanimity (all three committed) | **0.922** [0.815, 0.969] | ≥ 0.90 | clear | clear |
| M3 | Fleiss' κ | **0.849** [0.672, 0.967] | ≥ 0.70 | clear | clear |
| M5 | Evidence-path divergence | **0.894** [0.774, 0.954] | descriptive | — | > 0.50 |

Every axis landed where the pre-registration predicted.

### M2 — per-run detail

| run | commit rate | committed | commit accuracy |
|---|---|---|---|
| rep1 | 0.466 | 69 | 0.691 |
| rep2 | 0.446 | 66 | 0.677 |
| rep3 | 0.500 | 74 | 0.685 |

Commit rate ranges 0.054 across the three; commit accuracy ranges 0.014.

### M4 — decomposed by gold class

| class | n | M1 unanimity | Fleiss' κ | M3 (of committed) |
|---|---|---|---|---|
| yes-gold | 70 | 0.800 | 0.740 | 25 / 27 unanimous |
| no-gold | 76 | 0.605 | 0.553 | 21 / 23 unanimous |

The instability sits on the negative-gold pairs, where commit-versus-abstain is
a close call at the floor. Where the evidence exists, the runs agree.

### M5 — evidence-path divergence (the headline)

Of the **47** pairs where all three runs commit and agree on the answer:
- **42** (0.894) cite two or more distinct source URLs across the runs
- **17** cite three distinct URLs

### M6 — floor distribution, first runs after the D7 leak fix

Share of committed answers landing at exactly 0.65:

| run | first-attempt | retried |
|---|---|---|
| rep1 | 0.161 | 0.342 |
| rep2 | 0.100 | 0.333 |
| rep3 | 0.107 | 0.391 |
| **exp34 (pre-D7-fix baseline)** | 0.094 | 0.327 |

---

## 5. Reading

**The commit/abstain decision is the unstable part; the label is not.** Outcome
unanimity is 0.70 — on roughly three pairs in ten, at least one run commits
where another abstains — yet agreement remains "substantial" on the Landis-Koch
scale (κ 0.65). Once all three runs commit, they agree on the label 0.92 of the
time (κ 0.85). This is the §4.7 story exactly: a generative assessor reproduces
its answers well and reproduces its decision to answer less well.

**The instability is concentrated on negative-gold pairs** (M4: no-gold
unanimity 0.61 against yes-gold 0.80). Those are the thin-evidence pairs where
the commit decision sits closest to the 0.65 floor. Where the evidence is there,
the runs converge.

**The headline is M5.** In 89% of the pairs where all three runs commit and
agree, they reached that answer through different source URLs, and 17 used three
distinct URLs. The system converges on the same answer through varied evidence
far more often than it repeats one retrieval. High answer agreement (M3) sitting
on high evidence divergence (M5) is the direct evidence for the §2.2 claim that
agreement across independent evidence paths is worth more than one computation
repeated.

**An empirical noise floor for §4.2.** Per-run commit accuracy is 0.691 / 0.677
/ 0.685, a range of 0.014. The §4.2 ablation ladder spans 0.649 to 0.726, so its
steps are an order of magnitude larger than run-to-run noise. The ladder is a
real ordering, not a sampling artefact, and §4.2 can now say so with a measured
number rather than only overlapping intervals.

**M6 lays a worry to rest.** These are the first runs after the D7 floor-leak
fix, which stopped the retry text from naming the 0.65 threshold. The retried-
at-floor rate is 0.33 to 0.39, against the exp34 pre-fix baseline of 0.327:
removing the leak did not move the pile-up. So the clustering at the floor is a
real attractor in the researcher's retried confidence, not an artefact of being
told the threshold. The D7 fix stands on its own merits, but the floor pile-up
was never mainly the leak.

## 6. Caveats

- Development battery (Malta, Netherlands, Albania), already burned for tuning;
  this characterises the system's reproducibility rather than generalising
  without that assumption stated.
- Three replicates is the minimum for a variance estimate, so the κ intervals
  are wide and reported as such.
- The runs ran hours apart against a live web, so part of the measured
  instability is the web changing under the system rather than the model
  sampling differently. The measurement is therefore of end-to-end
  reproducibility, which is what §2.2 asks for.

## 7. Provenance and integrity

- Every run passed a 14-check gate at the 5%, 40% and 100% marks: no held-out
  country, models pinned, deny-list clean over every URL-bearing column, no
  evidence replayed between runs, no ODMI scoring vocabulary in committed
  evidence, and the runtime fingerprint unchanged.
- rep3 took two false starts, both caught rather than hidden: a rate-limit at
  0/156 from the 5-hour Claude window being exhausted by the first two runs, and
  a void at 62/156 when a parallel edit to `agents/` moved the runtime
  fingerprint mid-run. The gate caught the second; rep3 was re-run under the
  restored frozen runtime.
- No adoption rule. Production is unchanged (D45). The output is a measured
  §4.7, a noise floor for §4.2, and a Reproducibility row for Table 3.1.
