# EXP-41 run-to-run stability: final three-run result

Three fresh dispatches of the incumbent trio over the 156-pair dev battery, one
frozen configuration (fingerprint `272db6b28e88`, verified byte-identical across
all three at every gate), nothing seeded or replayed, cold cache each time.
Pre-registration `docs/EXPERIMENTS_RUN_STABILITY.md` (D65). Result JSON
`evaluation/results/exp41_analysis.json`.

## What ran

| replicate | finalised | dropped (Albanian search stalls) |
|---|---|---|
| rep1 | 155/156 | PT16:AL |
| rep2 | 154/156 | PT38:NL, PT9:NL |
| rep3 | 151/156 | Q4/Q8/Q11/Q15/Q23:AL |

**Three-way intersection: 148 pairs.** Each run completed gate-clean; the drops
are benign non-returning-search stalls, disclosed, dropped from the
intersection as the pre-registration says (n is the intersection by design).

## Result against the pre-registered bars

| metric | value | bar | verdict | predicted |
|---|---|---|---|---|
| M1 outcome unanimity | 0.703 [0.625, 0.770] | >= 0.80 | **miss** | miss |
| M1 Fleiss kappa | 0.654 [0.563, 0.735] | >= 0.60 | **clear** | -- |
| M2 commit-rate range | 0.054 (sd 0.022) | <= 0.10 | clear | clear |
| M3 label unanimity | 0.922 [0.815, 0.969], n=51 | >= 0.90 | clear | clear |
| M3 Fleiss kappa | 0.849 [0.672, 0.967] | >= 0.70 | clear | clear |
| M5 evidence-path divergence | 0.894 [0.774, 0.954], n=47 | (descriptive) | -- | > 0.50 |

Every axis landed where the pre-registration predicted.

## Reading

**The commit/abstain decision is the unstable part; the label is not.** Outcome
unanimity is 0.70: on three in ten pairs at least one run commits where another
abstains. But agreement is still "substantial" on the Landis-Koch scale
(kappa 0.65), and once all three runs commit, they agree on the label 0.92 of
the time (kappa 0.85). This is the §4.7 story exactly: a generative assessor
reproduces its answers well and reproduces its decision to answer less well.

**The instability is concentrated on negative-gold pairs** (M4): yes-gold
outcome unanimity 0.80 (kappa 0.74) against no-gold 0.61 (kappa 0.55). The hard
thin-evidence pairs, where commit-versus-abstain is a close call at the 0.65
floor, are where the runs diverge. Where the evidence is there, the runs agree.

**The headline (M5): 0.894 evidence-path divergence.** Of the 47 pairs where all
three runs commit and agree on the answer, 42 reached that answer citing two or
more distinct source URLs across the runs, and 17 used three distinct URLs. The
system converges on the same answer through different evidence far more often
than it repeats one retrieval. This is the direct evidence for the §2.2 claim
that agreement across independent evidence paths is worth more than one
computation repeated: high answer agreement (M3) sitting on high evidence
divergence (M5) is exactly that claim, measured.

**Empirical noise floor for §4.2.** Per-run commit accuracy is 0.691 / 0.677 /
0.685, a range of 0.014. The §4.2 ablation ladder spans 0.649 to 0.726, so its
steps are an order of magnitude larger than run-to-run noise. The ladder is a
real ordering, not a sampling artefact, and §4.2 can now say so with a measured
figure rather than only overlapping Wilson intervals.

**M6, the floor pile-up, is not the D7 leak.** These are the first runs after
the D7 floor-leak fix. Retried commits still land at exactly 0.65 at 0.33-0.39
(rep1-3), against the exp34 pre-fix baseline of 0.327; first-attempt commits at
0.10-0.16 against 0.094. Removing the leak did not move the pile-up. So the
clustering at the floor is a real attractor in the researcher's retried
confidence, not an artefact of being told the threshold. The D7 concern is laid
to rest as a distributional worry, though the fix stands on its own merits.

## Caveats

Development battery (MT/NL/AL), burned, not the held-out set: this
characterises the system's reproducibility, it does not generalise without that
assumption stated. Three replicates is the minimum for a variance estimate, so
the kappa intervals are wide. The runs ran hours apart against a live web, so
part of the measured instability is the web moving, not the model sampling; the
measurement is of end-to-end reproducibility, which is what §2.2 asks for.
