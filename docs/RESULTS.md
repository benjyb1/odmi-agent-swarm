# Results

Headline empirical results for the ODMI agent swarm. Each entry states the
design in one line, the numbers, and the honest reading. Full pre-registrations
and per-experiment detail live in the linked docs; the machine record is the
`experiments` table and `evaluation/results/*.json`.

Evaluation is balance-aware and three-outcome throughout (D38 R4, D47): commit
accuracy / coverage / negative-gold false-positive rate, plus per-class recall,
balanced accuracy and Youden's J against the majority-class baseline. Negative
results count (R12).

---

## EXP-40: adversarial vs cooperative verification architecture

**Design.** Four-arm architecture ablation on the dev battery (MT 60 + NL 52 +
AL 44, 78 negative golds). trio / no_adjudicator / researcher_only are replayed
off the frozen exp34 wide_only run; **cooperative** is the one live arm: a fair,
accuracy-seeking corroborative verifier (seek independent support, "adjacency is
not corroboration"), consensus commit, no adjudicator. The primary contrast is
no_adjudicator vs cooperative, where the only variable is the verifier's stance
(refute vs corroborate). Full prereg: `docs/EXPERIMENTS_COOPERATIVE_CONTRAST.md`.

| arm | coverage | commit-acc | neg-gold FPR | balanced-acc | Youden J |
|---|---|---|---|---|---|
| trio | 0.47 | 0.73 | 0.22 (17/78) | 0.33 | -0.34 |
| no_adjudicator | 0.39 | 0.69 | 0.22 (17/78) | 0.26 | -0.48 |
| researcher_only | 0.24 | 0.65 | 0.13 (10/78) | 0.15 | -0.70 |
| **cooperative** | 0.40 | 0.65 | 0.24 (19/78) | 0.26 | -0.48 |

**Primary result: a clean null.** no_adjudicator vs cooperative: balanced
accuracy 0.261 vs 0.262, Youden J -0.477 vs -0.476, paired McNemar on committed
correctness over 154 shared binary-gold pairs 8-vs-8, **p = 1.00**. The
pre-registered prediction (cooperative abstains more, lower FPR) is refuted in
the mild-negative direction: it commits marginally more (0.40 vs 0.39) at a
marginally higher FPR (0.24 vs 0.22), both within noise.

**Reading.** A fair corroborative verifier is indistinguishable from the
adversarial one at the system level. This reconciles with EXP-38, which found
the adversarial stance clearly better at the verifier's *isolated* job (Youden
J 0.41 vs 0.16 on frozen candidates): the stance governs the verifier's own
discrimination but washes out end to end, because system precision is set by the
D37 confidence floor and retrieval quality, not by the verifier's accept/reject
framing (consistent with D45 -- the verifier verdict is decision-relevant on few
pairs). The secondary ladder is coherent: the Adjudicator earns its place (trio
vs no_adjudicator: +0.08 coverage, +0.04 commit-acc at flat FPR), and the
Verifier loop lifts coverage (0.24 -> 0.39) but also FPR (0.13 -> 0.22).
Production is unchanged (trio stays, D45). Deny-list clean (0 blocked across the
run). Result JSON: `evaluation/results/exp40_analysis.json`.

---

## EXP-36: frozen headline, eight held-out countries

**Design.** The frozen production architecture, end to end, on the eight D47
held-out countries it was never tuned on (BA MK ME BG / FI HR SE BE), 1,144
pairs. Single configuration, no adoption rule -- the reported headline. Prereg:
`docs/EXPERIMENTS_EXP36_PREREG.md`; audit: `docs/EXP36_LEAKAGE_AUDIT.md`.

- Coverage 0.556, **commit accuracy 0.701** [0.664, 0.736], negative-gold FPR
  0.255, expected calibration error 0.063 (well calibrated).
- RQ3 resource-stratum contrast (A low/mid-resource vs B higher): stratum A
  abstains +0.16 more (p < 0.001), commits -0.16 less accurately (p < 0.001),
  with a *lower* negative-gold FPR (-0.11, p = 0.023). Low resource drives
  abstention, not false confidence.
- FM-14 committed-evidence audit clean: 0 committed pairs cite a deny-listed
  source. 7 verifier counter-search hits were disclosed and drove the deny-list
  fix now shipped (see EXP-40).

## EXP-38: corroborative vs adversarial verifier discrimination

**Design.** Search-free replay over the 150 frozen EXP-11 stage-1 candidates,
disprove vs corroborate, Youden's J primary. Prereg: `docs/EXPERIMENTS_CORROBORATE.md`.

- disprove J **0.41** (sensitivity 0.72), corroborate J **0.16** (sensitivity
  0.32). The corroborative framing loses 0.26 of J through a sensitivity
  collapse: it passes bad claims it finds adjacent support for. Adversarial
  framing is the better verifier stance in isolation -- the component-level
  counterpart to EXP-40's system-level null.

## EXP-39: is language a confound? (no DeepL)

**Design.** Four independent tests of whether evidence language, not data
availability, limits the swarm. Prereg: `docs/EXPERIMENTS_LANGUAGE_PROBE.md`.

- Query ablation (AL): bilingual recall 46% vs English-only 48% -- thin web, not
  language.
- 127-case pre-translation replay (DeepL): 0.8% net movement toward gold.
- On-the-fly local-MT swap probe (argos, en->fr/bg/sq): null after the quality
  gate (the sq flag was degraded translation, not comprehension).
- Held-out evidence-language contrast: MH odds ratios scatter 0.33-1.39, no
  direction.

**Four independent nulls converge:** data availability, not evidence language,
is the binding constraint on the swarm's deficit.
