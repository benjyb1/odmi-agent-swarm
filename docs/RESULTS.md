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

## EXP-42: the architecture ladder and the verifier stance, on the held-out eight

**Design.** The same four-arm ladder as EXP-40, moved from the 156-pair dev
battery to the eight D47 held-out countries the results chapter is framed
around: 1,144 pairs, 909 binary golds, 370 negative golds. Seven times the
power, and on the right population.

Three of the four rungs cost nothing. EXP-36 is a completed trio run, so every
arm below it is recoverable from its stored rows: `researcher_only` is the
attempt-1 answer at or above the D37 floor, `no_adjudicator` commits iff the
Verifier accepted, `trio` is the outcome as it stands. Only `cooperative` needed
new calls, and that is EXP-42 arm B (1,144 pairs, ~17h, £330, prereg
`docs/EXPERIMENTS_EXP42_STANCE_HELDOUT.md`).

| arm | coverage | commit-acc | neg-gold FPR | balanced-acc | Youden J |
|---|---|---|---|---|---|
| researcher_only | 0.266 | 0.767 | 0.124 (46/370) | 0.173 | -0.654 |
| no_adjudicator | 0.460 | 0.740 | 0.232 (86/370) | 0.315 | -0.371 |
| **trio** | 0.556 | 0.735 | 0.246 (91/370) | 0.395 | -0.209 |
| cooperative | 0.476 | 0.727 | 0.270 (100/370) | 0.316 | -0.369 |

Wilson 95% on the FPR column: researcher_only [0.095, 0.162], no_adjudicator
[0.192, 0.278], trio [0.205, 0.292], cooperative [0.228, 0.318].

**Result 1: the Verifier still does not filter for precision, now at n=1,144.**
Adding the adversarial Verifier nearly doubles the negative-gold
false-positive rate, 0.124 to 0.232 (paired 8 vs 48, p < 0.0001), while lifting
coverage 0.266 to 0.460. The dev battery said this at n=156 and it holds on the
held-out set. It remains the opposite of what section 2.5 predicts.

**Result 2: the Adjudicator earns its place.** trio over no_adjudicator adds
9.6 points of coverage and 64 pairs it gets right that no_adjudicator misses
against 0 the other way (p < 0.0001), for 5 extra false positives out of 370
(p = 0.0625). Coverage and accuracy for almost nothing in precision.

**Result 3: stance is equivalent on accuracy, unresolved on precision.**
no_adjudicator vs cooperative is the one-variable stance contrast, since both
are two-agent arms with no arbitration. Committed-correctness 50 vs 57
discordant, p = 0.562. Delivered accuracy 0.353 vs 0.361, and **TOST against the
pre-registered +/-0.05 margin gives p = 0.0001, equivalent**. That is the result
EXP-40 could not supply: a McNemar null fails to reject, it does not establish
equivalence.

The negative-gold false-positive rate moves the other way, 0.232 to 0.270 (18 vs
32 discordant, p = 0.065). That is the direction section 2.5 predicts, on the
reasoning that corroboration compounds the guessing bias where refutation checks
it, but it is not significant and must not be written as though it were.

**Reading.** Stance does not change how often the system is right, and that is
now settled by an equivalence test rather than by a failure to reject. Stance may
change what the system is willing to assert, and that question stays open at 370
negative golds. Section 4.2's "the Verifier's stance does not matter" is
therefore supported for accuracy and **not** supported for the negative-gold
false-positive rate; sections 4.2 and 5.2 need revising rather than deleting.
Characterisation only, no adoption rule, production stays trio (D45).

**Caveats.** 46 of 1,144 pairs have no attempt-1 researcher row
(catalogue-computed or seeded) and count as abstentions in `researcher_only`,
the same convention the dev-battery table uses. 33 pairs decided by the D30
catalogue recompute are excluded from the stance contrast, where the Verifier
makes no LLM call and stance cannot reach the outcome; both arms commit on all
33 and agree on 32, so keeping them would have been guaranteed ties that make
equivalence easier to declare than the evidence warrants. Second touch of the
D47 frozen set, authorised by Benjy on 2026-07-29 with no supervisor sign-off on
record, and owed in the dissertation limitations. Deny-list clean, 0 violations
across the run. Reproduce with `evaluation/exp42_ladder.py`; result JSON
`evaluation/results/exp42_ladder.json`.

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
