# Results register

Every empirical number the dissertation reports, recomputed from the databases
and stated with its numerator, denominator, population, experiment identifier,
source database and the command that reproduces it. This file is the single
source of truth for project figures. Where the dissertation states a value this
register does not support, the disagreement is listed in
`docs/RESULTS_DISCREPANCIES.md`; nothing is silently reconciled.

Rebuilt 2026-07-31 by recomputing every figure from source. Prior versions of
this file quoted numbers under mixed definitions and are superseded.

---

## 1. How to read this file

Each row carries the value, `k/n`, the population it is over, the experiment id,
a source-database key from §2, and a reproduction path. Nothing here is copied
from prose. Where a quantity has two defensible definitions, both are given and
the one the dissertation uses is named.

`docs/RESULTS_COLLATION.md` is the working collation assembled 2026-07-17 and
moved into `docs/` on 2026-08-01. Its figures were checked against this register
and agree; it predates the definitional reconciliation, so it reports the
negative-gold rate on the any-wrong convention only and does not carry the
denominator splits in §3. Treat this file as authoritative and that one as
design history.

---

## 2. Source databases

`data/odmi.db` is git-tracked and each worktree holds a diverging copy. The copy
in the main checkout and the copy in this worktree were verified byte-identical
(md5 `553f5872…`) at the time of writing. Never query a database in place after
a run has touched it; copy it to a scratch path first.

| Key | Path | Holds | Why this copy |
|---|---|---|---|
| **D1** | `data/odmi.db` | `exp36_frozen_headline` (1,151 rows / 1,144 pairs), `exp42_stance_heldout` (1,146 / 1,144), `exp40_cooperative_contrast` (157 / 156), `exp41_stability_rep1..3` (155 / 154 / 151), `exp34_retrieval_strategy_s46` (314 / 156), `exp32_model_haiku` (156), `exp36_model_opus` (157 / 156), `closed_book_answers` `cb_heldout_20260725` (1,144), `ground_truth` (5,148), `questions` (143) | Maximal row count for every experiment the dissertation reports. Checked against 150 candidate databases: the canonical file, nine dated snapshots under `data/`, 40 worktree copies and 203 unreferenced `.git/lfs/objects/` blobs. |
| **D2** | `.claude/worktrees/exp36-run/data/odmi.db` | `claude_usage_log` (192,341 rows; 53,531 scoped to the EXP-36 pair ids) | The only surviving copy of the snippet-picker call log. D1 holds 140,806 usage rows and cannot reproduce the cost figures. Orphaned worktree; do not delete. |
| **D3** | `.git/lfs/objects/0b/e2/0be20b9c…` | `catalogue_metrics` (195 rows), `catalogue_snapshots` incl. Montenegro | D1 holds 132 catalogue rows and **no Montenegro metrics**, so the §4.1 recompute leg cannot be reproduced from D1 at all. Four other LFS blobs carry the same 195 rows. |

Databases with no unique content: `data/rescued_experiments.db` and its worktree
copies (36 MB, EXP-40 and recovered arms already merged into D1); the dated
`data/odmi.*.db` snapshots (each a superset of an older state, none holding a
row D1 lacks for any reported experiment); the 12 worktree files that are 134-byte
LFS pointers.

Copy before querying:

```bash
cp data/odmi.db "$SCRATCH/main.db" && sqlite3 "file:$SCRATCH/main.db?mode=ro"
```

---

## 3. Definitions, and which one the dissertation uses

Five definitional choices account for nearly every figure that appears two ways.

**D22 match classifier.** `dashboard/lib/db.py::_MATCH_STATUS_SQL` is
authoritative. It returns `match` / `near_match` / `differ` / `abstained` /
`flag_review` / `no_ground_truth` / `no_swarm_answer`. Any script whose scoring
differs from it is reporting a different quantity, not a better one.

**Committed.** `terminal_status IN ('accepted_by_verifier',
'accepted_by_adjudicator')` and `final_answer` present and not `inconclusive`.
This is `evaluation/exp36_analysis.py::is_committed`. The cooperative arm uses
`accepted_cooperative`.

**Commit-accuracy denominator.** Matches over *scoreable committed* pairs:
`match_status IN ('match','near_match','differ')`, all answer shapes.
**437/623 = 0.701.** The alternative 0.704 is 442/628, which is the classifier
run over every row including abstentions on `not applicable` golds; those pairs
never committed, so they belong on neither side of a commit ratio. `near_match`
counts in the denominator and not the numerator (10 pairs).

**Gold class.** Two conventions, both defensible:

| Convention | Binary golds | Negative golds | Used by |
|---|---|---|---|
| `questions.answer_shape = 'binary'` **and** gold in (yes, no) | **907** | **368** | Chapter 4 throughout, `exp36_analysis.py` |
| gold string is `yes` or `no`, any shape | 909 | 370 | `exp42_ladder.py`, `exp42_analysis.py`, §3.7, Appendix E |

The two extra pairs are `P29:SE` and `P29:BA`, a `count_band` question whose
gold is the bare string `no`. **Chapter 4's convention (907/368) is the one to
apply everywhere**, because every per-class rate, stratum table and dimension
table in the results chapter is already computed on it.

**Negative-gold false-positive rate.** Three quantities, all real:

| Reading | Value | Where it comes from |
|---|---|---|
| committed a **yes** against a `no` gold | **91/368 = 0.247** | the definition the dissertation prose settles on |
| committed **any wrong answer** against a `no` gold | 94/368 = 0.255 | `exp36_analysis.py::three_outcome`, and every table in the dissertation |
| the same on the 370 denominator | 95/370 = 0.257 | `exp42_analysis.py` |

The 94 are the 91 wrong yeses plus three `not_applicable` commitments
(`MK:I4`, `MK:Q5`, `MK:Q6`). The false-positive audit adjudicated the 91 and
flagged the 3, which is why the audit file holds 94 records and reports 91
verdicts. **Report wrong-yes, name it, and state the 94 separately.**

---

## 4. Chapter 4.1, Convergent Validity

Population: EXP-36, the eight D47 held-out countries, 143 questions each.
Source: **D1**. Reproduce the whole block with:

```bash
uv run python evaluation/exp36_analysis.py --db data/odmi.db
```

| Quantity | Value | k/n | Population | Source |
|---|---|---|---|---|
| Pairs dispatched | 1,144 | 8 × 143 | held-out eight | D1 |
| Raw `phase2_final` rows | 1,151 | 7 superseded duplicates collapsed | EXP-36 | D1 |
| Coverage | **0.5559** | 636/1,144 | all pairs | D1 |
| Abstentions | 508 | 508/1,144 = 0.4441 | all pairs | D1 |
| Agent failures | 0 | 0/1,144 | all pairs | D1 |
| Commit accuracy | **0.7014** [0.664, 0.736] | 437/623 | scoreable committed | D1 |
| Committed but unscoreable | 13 | `flag_review`; 0 `no_ground_truth` | committed | D1 |
| `near_match` inside the denominator | 10 | 10/623 | scoreable committed | D1 |
| Binary golds | 907 | 539 yes, 368 no | `answer_shape='binary'` | D1 |
| Yes-gold commit accuracy | **0.8702** | 295/339 | committed yes golds | D1 |
| Yes-gold recall | 0.5473 | 295/539 | all yes golds | D1 |
| Yes-gold abstention | 0.3711 | 200/539 | all yes golds | D1 |
| No-gold commit accuracy | **0.4891** | 90/184 | committed no golds | D1 |
| No-gold recall | 0.2446 | 90/368 | all no golds | D1 |
| No-gold abstention | 0.5000 | 184/368 | all no golds | D1 |
| Forced accuracy (abstention = miss) | 0.4245 | 385/907 | binary golds | D1 |
| Balanced accuracy | 0.3959 | (0.5473 + 0.2446)/2 | binary golds | D1 |
| Youden J | -0.2081 | | binary golds | D1 |
| Negative-gold FP, wrong-yes | **0.2473** | 91/368 | all negative golds | D1 |
| Negative-gold FP, any wrong commit | 0.2554 | 94/368 | all negative golds | D1 |
| Wrong-yes among committed negatives | 0.4946 | 91/184 | committed negative golds | D1 |

### Baselines

| Baseline | Value | k/n | Population | Source |
|---|---|---|---|---|
| Always-yes, held-out eight | **0.5943** | 539/907 | `answer_shape` binary golds | D1 |
| Always-yes, held-out eight | 0.5930 | 539/909 | gold-string binary golds | D1 |
| Always-yes, all 36 countries | **0.8188** | 3,393/4,144 | `answer_shape` binary golds | D1 |
| Always-yes, all 36 countries | 0.8184 | 3,393/4,146 | gold-string binary golds | D1 |

### Closed book, retrieval disabled

Run id `cb_heldout_20260725`, table `closed_book_answers`, source **D1**.
Reproduce: `uv run python evaluation/closed_book_baseline.py --db data/odmi.db`.

| Quantity | Value | k/n | Population |
|---|---|---|---|
| Rows | 1,144 | | held-out eight |
| Coverage (real answer, not `inconclusive`) | **0.7561** | 865/1,144 | all pairs |
| Rows not classified `abstained` | 0.7675 | 878/1,144 | all pairs; counts 13 abstentions on `n/a` golds as commitments |
| Commit accuracy | 0.5535 | 476/860 | scoreable committed |
| Forced accuracy | **0.4300** | 390/907 | binary golds |
| Yes recall | 0.4360 | 235/539 | yes golds |
| No recall | 0.4212 | 155/368 | no golds |
| Balanced accuracy | **0.4286** | | binary golds |
| Delivered accuracy vs its own floor | **0.4293** vs **0.4732** | 489/1,139 vs 539/1,139 | pairs with a classifiable status |
| Negative golds it committed on | 0.5679 | 209/368 | excludes `inconclusive` and `i don't know` |
| Negative-gold FP, wrong-yes | 0.1386 | 51/368 | all negative golds |
| Negative-gold FP, any wrong commit | 0.3614 | 133/368 | all negative golds |

Three separate quantities round to 42.9%: balanced accuracy on the 907
(0.4286), delivered accuracy on the 1,139 (0.4293), and neither is the forced
accuracy 0.4300. Name the one being used.

Swarm against closed book, paired on the 907 binary golds:

| Quantity | Value |
|---|---|
| Agree | 618 (243 both right, 375 both wrong) |
| Discordant | 289: 142 to the swarm, 147 to closed book |
| McNemar exact p | **0.8140** |
| Oracle upper bound | 0.5865 (532/907) |

### Independent recompute leg

Source: **D3** (`catalogue_metrics`). D1 cannot reproduce this: it holds no
Montenegro metrics.

| Quantity | Value | k/n | Population |
|---|---|---|---|
| Held-out countries with a harvestable portal | 4 | FI, HR, SE, ME | held-out eight |
| Distinct recomputed cells | 36 | 4 countries × 9 questions | D3 |
| Cells where the recomputed band equals the published band | **18/36 = 0.500** | FI 7/9, HR 2/9, ME 5/9, SE 4/9 | D3 |
| Divergence | **0.500** | 18/36 | D3 |
| Direction of the 18 disagreements | **11 the country overstated, 4 understated, 3 not band-comparable** | overstated FI Q25 Q27, HR Q12 Q16 Q21 Q25 Q27, ME Q12 Q25 Q27, SE Q21; understated HR Q22, SE Q12 Q18 Q25 | D3 |
| Catalogue-decided pairs inside the EXP-36 run | 33 | FI 9, HR 9, ME 9, SE 6 | D1 |
| Of those, swarm answer matches the key | 0.5152 | 17/33 | D1 |
| …counting `near_match` | 0.7576 | 25/33 | D1 |
| Croatia Q22 | key `10-30%`, recompute 97.8% and 97.6% on two routes | | D3 |
| Montenegro Q25 open licence | key `>90%`, recompute **70.0%** (629/898) | | D3 |
| Montenegro Q12 licence presence | key `>90%`, recompute **75.6%** (679/898) | | D3 |
| France Q12 licence presence | key `>90%`, recompute 37.8% (1,890/5,000) | | D3 |
| Romania Q17 / Q18 | key `10-30%` / `<10%`, recompute 100.0% / 99.7%, reproduced on two harvest routes | | D3 |

The nine computable questions are Q12, Q13, Q16, Q17, Q18, Q21, Q22, Q25, Q27.
Q2, Q26, Q28 and Q29 have no metric function and are not computable.

---

## 5. Chapter 4.2, Selectivity

Source **D1** throughout. Abstention codes reproduce with:

```bash
uv run python evaluation/abstention_gold_class_by_code.py --db data/odmi.db
```

| Code | Reason | Pairs | Share of 508 |
|---|---|---|---|
| E | Verifier relevance rejection | 208 | 0.4094 |
| G | Below the 0.65 confidence floor | 199 | 0.3917 |
| I | Researcher never committed | 30 | 0.0591 |
| D | Quote absent from retrieved pages | 24 | 0.0472 |
| Z | Instrumentation mismatch | 19 | 0.0374 |
| B | Fetch error | 16 | 0.0315 |
| C | Blocked by the deny-list | 12 | 0.0236 |
| A, F1, F3 | Thin web, schema-invalid, search-empty | 0 | 0 |
| | **Total** | **508** | 1.000 |

| Quantity | Value | k/n | Population |
|---|---|---|---|
| E and G between them | 407 | 208 + 199 | abstentions |
| E pairs also below the floor | 172 | 172/208 | code E |
| Failed the Verifier test alone | 36 | 208 − 172 | code E |
| Evidence-based codes E, G, I, D | 461 | 461/508 | abstentions |
| Adjudicator returned `abstain` | 413 | 413/508 | abstentions |
| Withheld at the 0.65 commit gate | 82 | 82/508 | abstentions |
| Adjudicator's own answer inconclusive | 13 | 13/508 | abstentions |
| A plain gold answer existed | **0.9429** | 479/508 | abstentions; excludes `i don't know` and `not applicable` |
| Questions abstained on by 7 or 8 countries | 19 | | 143 questions |
| …of those, on the 29-question out-of-reach list | 12 | 12/19 | |

### Calibration

| Quantity | Value | n |
|---|---|---|
| Expected calibration error, all | **0.0632** | 623 scoreable committed |
| ECE, yes golds | 0.0890 | 339 |
| ECE, no golds | **0.2990** | 184 |
| Populated bins of the 10 pre-registered | 4 (0.6-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0) | 6 empty |
| Top bin, negative golds against yes golds | 3 against 77 | |

Reliability curve, all scoreable committed answers:

| Bin | n | Accuracy | Mean confidence |
|---|---|---|---|
| 0.6-0.7 | 200 | 0.655 | 0.655 |
| 0.7-0.8 | 205 | 0.639 | 0.735 |
| 0.8-0.9 | 100 | 0.770 | 0.832 |
| 0.9-1.0 | 118 | 0.831 | 0.944 |

No-gold bins run backwards: 0.734 at 0.6-0.7, 0.308 at 0.7-0.8, 0.045 at
0.8-0.9, 0.000 at 0.9-1.0.

### Confidence floor sweep and the sub-floor tail

| Quantity | Value | k/n |
|---|---|---|
| Yes-gold accuracy at the 0.65 floor | 0.8702 | 295/339 |
| Yes-gold accuracy at 0.90 | 0.9870 | 76/77 |
| Yes-gold accuracy first reaches 1.000 | at 0.95 | 42/42 |
| No-gold accuracy at the 0.65 floor | 0.4891 | 90/184 |
| No-gold accuracy reaches zero | at 0.81 | 0/19, and stays there |
| Committed answers in the 0.65-0.70 band, all classes | 0.6550 | 131/200 |
| …negative golds only in that band | 0.7340 | 69/94 |
| Committed `no` answers, scoreable | 142 | |
| …sitting at exactly 0.65 | **86** | 86/142 |
| …reaching 0.95 | 0 | highest is 0.90 |
| Code-G withheld answers, yes gold | 73 | 18 correct |
| Code-G withheld answers, no gold | 89 | 79 correct |

---

## 6. Chapter 4.3, Attributability

| Quantity | Value | k/n | Share of 1,144 | Source |
|---|---|---|---|---|
| Committed answers that cleared the quote gate | 636 | 636/636 | 0.5559 | D1 |
| Abstentions recording an ungrounded quote (code D) | 24 | | 0.0210 | D1 |
| Verifier relevance rejections (code E) | 208 | | 0.1818 | D1 |
| Abstained for another reason | 276 | | 0.2413 | D1 |
| Verifier converts wrong or withheld into correct | **165** | | | D1 |
| Verifier loses in the other direction | **13** | | | D1 |
| Answers moved by the Verifier | 178 | | | D1 |
| Adjudicator commits | 110 | | | D1 |
| Adjudicator correct | 65 | 0.5909 | | D1 |
| Verifier-path accuracy for comparison | 0.7251 | 372/513 | | D1 |
| Adjudicator overturns a Verifier decision | 0 | | | D1 |

### False-positive audit

Source: `evaluation/results/heldout_fp_audit_merged94.jsonl`, 94 records.

| Quantity | Value |
|---|---|
| Records | 94: 91 committed `yes`, 3 committed `not_applicable` |
| Gold on every record | `no` |
| By country | MK 25, FI 14, ME 13, BA 10, BG 10, SE 10, BE 6, HR 6 |
| Charitable pass, genuine swarm error | 16/91 |
| Charitable pass, definitional gap | 69/91 |
| Charitable pass, defensible or stale gold | 6/91 |
| Charitable pass, gold is a self-report | 81/91 |
| Charitable pass, evidence supports the yes | **7/91**; 84/91 judged too weak |
| Adversarial pass, swarm over-read | 68/91 |
| Adversarial pass, ambiguous | 23/91 |
| Adversarial pass, gold wrong | **0/91** |

The 3 `not_applicable` pairs carry no verdict: the yes-rubric cannot adjudicate
them. They are flagged for manual review. The record carries no judge-model
field, so the Opus version cannot be settled from this artefact.

---

## 7. Chapter 4.4, Subgroup Equity

Stratum A = BA, MK, ME, BG. Stratum B = FI, HR, SE, BE. Source **D1**.

| Quantity | Stratum A | Stratum B |
|---|---|---|
| Pairs | 572 | 572 |
| Abstention | 0.5227 (299/572) | 0.3654 (209/572) |
| Commit accuracy | 0.6113 (162/265) | 0.7682 (275/358) |
| Negative golds, `answer_shape` convention | 261 | 107 |
| Negative golds, gold-string convention | 262 | 108 |
| Negative-gold FP, wrong-yes, all negatives | **0.2107** (55/261) | **0.3364** (36/107) |
| Negative-gold FP, any wrong commit | 0.2222 (58/261) | 0.3364 (36/107) |
| Negative-gold FP, committed only, wrong-yes | 0.4264 (55/129) | 0.6545 (36/55) |
| Negative-gold abstention | 0.5057 (132/261) | 0.4860 (52/107) |
| Negative-gold recall | 0.2720 (71/261) | 0.1776 (19/107) |

Abstention-code split, which is where the 15.7-point gap sits:

| Code | Stratum A | Stratum B |
|---|---|---|
| G, below the floor | **143** | **56** |
| E, relevance rejection | 101 | 107 |
| I | 13 | 17 |
| D | 10 | 14 |
| Z | 12 | 7 |
| B, fetch error | 16 (BG 14, ME 1, BA 1) | 0 |
| C, deny-list | 4 | 8 |
| Total | 299 | 209 |

The G gap is 87 of the 90-pair total gap, 0.967.

### Per country

Negative-gold FP is wrong-yes over all negative golds unless stated.

| Country | Published maturity | Pairs | Coverage | Commit acc | Neg golds | FP wrong-yes | FP any wrong |
|---|---|---|---|---|---|---|---|
| FI | 77.9 | 143 | 0.7413 | 0.8000 (84/105) | 29 | **0.4828** (14/29) | 0.4828 |
| SE | 77.8 | 143 | 0.7063 | 0.7700 (77/100) | 27 | 0.3704 (10/27) | 0.3704 |
| BE | 76.6 | 143 | 0.5524 | **0.8205** (64/78) | 24 | 0.2500 (6/24) | 0.2500 |
| HR | 73.5 | 143 | 0.5385 | 0.6667 (50/75) | 27 | 0.2222 (6/27) | 0.2222 |
| BG | 62.9 | 143 | 0.4266 | 0.7241 (42/58) | 51 | 0.1961 (10/51) | 0.1961 |
| ME | 59.9 | 143 | 0.5804 | 0.6098 (50/82) | 59 | 0.2203 (13/59) | 0.2203 |
| MK | 42.8 | 143 | 0.5175 | **0.5278** (38/72) | 73 | 0.3014 (22/73) | **0.3425** (25/73) |
| BA | 15.1 | 143 | **0.3846** | 0.6038 (32/53) | 78 | **0.1282** (10/78) | 0.1282 |

Spearman against published maturity, n = 8:

| Correlate | ρ |
|---|---|
| Coverage | **0.8095** |
| Commit accuracy | **0.8810** |
| Negative-gold FP over all negatives, wrong-yes | **0.7381** |
| Negative-gold FP over committed negatives, any wrong | **0.8333** |
| Negative-gold FP over committed negatives, wrong-yes | 0.9048 |

No-share by country, used in §3.7: BA 78/92 = 0.848 on the `answer_shape`
convention and 79/93 = 0.849 on the gold-string convention; BG 51/117 = 0.436;
FI 29/120 = 0.242; BE 24/115 = 0.209.

---

## 8. Chapter 4.5, Generalisability

Source **D1**. Negative-gold FP given both ways because Impact and Quality
differ between them.

| Dimension | Pairs | Coverage | Commit accuracy | FP wrong-yes | FP any wrong | Forced accuracy |
|---|---|---|---|---|---|---|
| Policy | 248 | 0.7419 | 0.6857 (120/175) | **0.5000** (33/66) | 0.5000 (33/66) | 0.4839 (120/248) |
| Portal | 360 | 0.5250 | **0.7838** (145/185) | **0.1316** (15/114) | 0.1316 (15/114) | 0.3667 (132/360) |
| Impact | 304 | 0.5395 | **0.6220** (102/164) | 0.2571 (36/140) | 0.2643 (37/140) | 0.3355 (102/304) |
| Quality | 232 | **0.4267** | 0.7071 (70/99) | 0.1458 (7/48) | 0.1875 (9/48) | **0.3017** (70/232) |
| All | 1,144 | 0.5559 | 0.7014 (437/623) | 0.2473 (91/368) | 0.2554 (94/368) | 0.4245 (385/907) |

By answer shape:

| Shape | Questions | Pairs | Coverage | Commit accuracy | Correct over all pairs |
|---|---|---|---|---|---|
| binary | 124 | 992 | 0.5796 | **0.7229** (407/563) | 0.4103 |
| percentage_band | 12 | 96 | 0.3125 | 0.5333 (16/30) | 0.1667 |
| ordinal_magnitude | 3 | 24 | 0.5833 | 0.5385 (7/13) | **0.2917** |
| categorical | 2 | 16 | 0.6875 | 0.5455 (6/11) | **0.3750** |
| count_band | 2 | 16 | 0.3750 | 0.1667 (1/6) | **0.0625** (1 of 16) |

The four percentage-band questions with no catalogue route (Q2, Q26, Q28, Q29)
are declined on all 32 of their pairs.

Quality split by catalogue route:

| Group | Pairs | Committed | Commit accuracy |
|---|---|---|---|
| Catalogue-decided | 33 | 33 | 0.5152 (17/33) |
| Everything else in Quality | 199 | 66 | **0.8030** (53/66) |

---

## 9. Chapter 4.6, Reproducibility

EXP-41, three replicates on the 156-pair development battery, source **D1**.
Reproduce: `uv run python evaluation/exp41_analysis.py --db data/odmi.db`.

| Replicate | Finalised | Commit rate | Committed | Commit accuracy | Aggregate accuracy |
|---|---|---|---|---|---|
| rep1 | 155/156 | 0.4662 | 69 | 0.6912 (47/68) | 0.318 (47/148) |
| rep2 | 154/156 | 0.4459 | 66 | 0.6769 (44/65) | 0.297 (44/148) |
| rep3 | 151/156 | 0.5000 | 74 | 0.6849 (50/73) | 0.338 (50/148) |

| Quantity | Value |
|---|---|
| Pairs present in all three | **148** |
| Three-way outcome unanimity | **0.7027** (104/148), Fleiss κ 0.654 |
| Commit-accuracy range across runs | **0.0143** |
| Commit-rate range | 0.0541 |
| Label agreement once all three commit | **0.9216** (47/51), Fleiss κ 0.849 |
| Outcome unanimity, yes golds | 0.8000 (56/70) |
| Outcome unanimity, no golds | **0.6053** (46/76) |
| Unanimously committed and agreed pairs | 47 |
| …citing two or more distinct URLs | 42 |
| …citing three | 17 |
| Evidence-path divergence | **0.8936** (42/47) |

---

## 10. Chapter 4.7, the ablation ladder

Four arms plus the closed-book floor, over all 1,144 held-out pairs, Sonnet 4.6.
The trio and no-adjudicator arms are replayed off `exp36_frozen_headline`; the
cooperative arm is `exp42_stance_heldout`, run live. Source **D1**.

```bash
uv run python evaluation/exp42_ladder.py --db data/odmi.db
```

Commit accuracy is given both ways because the two reference scripts disagree.
The D22 column is the dissertation's.

| Arm | Coverage | Commit acc, D22 (all shapes) | Commit acc, binary-gold string equality | FP wrong-yes /368 | FP any wrong /368 | Balanced acc | Youden J |
|---|---|---|---|---|---|---|---|
| Researcher alone | 0.2657 (304/1,144) | **0.7432** (220/296) | 0.7667 (184/240) | **0.1250** (46) | 0.1332 (49) | 0.1733 | -0.6535 |
| + adversarial Verifier | 0.4598 (526/1,144) | **0.7251** (372/513) | 0.7396 (321/434) | **0.2337** (86) | 0.2418 (89) | 0.3150 | -0.3700 |
| + Adjudicator, full trio | 0.5559 (636/1,144) | **0.7014** (437/623) | 0.7347 (385/524) | **0.2473** (91) | 0.2554 (94) | 0.3959 | -0.2081 |
| Corroborative Verifier | 0.4764 (545/1,144) | **0.7116** (380/534) | 0.7273 (328/451) | **0.2717** (100) | 0.2799 (103) | 0.3159 | -0.3682 |
| Closed book, no retrieval | 0.7561 (865/1,144) | **0.5535** (476/860) | | **0.1386** (51) | 0.3614 (133) | 0.4286 | -0.1428 |

Correct answers delivered over all 1,144: 220 → 372 → 437 for the three swarm
rungs. Pairs with no attempt-1 researcher row, counted as abstentions in the
Researcher-alone arm: 46.

Per-class recall over the 907:

| Arm | Yes recall | No recall |
|---|---|---|
| Researcher alone | 0.3302 (178/539) | 0.0163 (6/368) |
| + Verifier | 0.5213 (281/539) | 0.1087 (40/368) |
| Full trio | 0.5473 (295/539) | 0.2446 (90/368) |
| Corroborative | 0.5584 (301/539) | 0.0734 (27/368) |

Paired contrasts, exact McNemar:

| Contrast | Discordant | p | Population |
|---|---|---|---|
| Researcher alone vs + Verifier, committed correctness | 13 vs 174 | < 0.0001 | 1,144 |
| …on binary golds | 13 vs 150 | < 0.0001 | 907 |
| Researcher alone vs + Verifier, negative-gold FP | 8 vs 48 | < 0.0001 | 368 |
| + Verifier vs full trio, committed correctness | 0 vs 65 | < 0.0001 | 1,144 |
| + Verifier vs full trio, negative-gold FP | 0 vs 5 | 0.0625 | 368 |
| **Adversarial vs corroborative, committed correctness** | **51 vs 59** | **0.5047** | 1,144 |
| …on binary golds | 50 vs 57 | 0.5621 | 907 |
| **Adversarial vs corroborative, negative-gold FP** | **18 vs 32** | **0.0649** | 368 |

Forced accuracy on the 907, adversarial 0.3539 (321) against corroborative
0.3616 (328). TOST against the pre-registered ±0.05 margin returns equivalence
at p = 0.0001; reproduce with `evaluation/exp42_analysis.py`, which runs over
1,111 pairs after excluding the 33 catalogue-decided pairs and reports the
negative-gold rate on the 370 denominator. `exp42_ladder.py` keeps all 1,144.
Both are defensible; every quoted figure must name its base.

---

## 11. Chapter 4.8, cost and timeliness

Cost is notional: the run bills against a flat subscription, and sterling
converts logged tokens at list prices with `USD_TO_GBP = 0.79`. The
`phase2_final.cumulative_cost_usd` column is **agent-only** and misses the
snippet picker, so it cannot produce these figures. Source: **D2**,
`claude_usage_log` scoped to the 1,151 EXP-36 `pair_run_id` values.

| Quantity | Value | Basis |
|---|---|---|
| Usage rows scoped to EXP-36 | 53,531 | D2 |
| Total | $475.63 = **£375.75** | D2 |
| Agent-only total, for comparison | $107.40 = £84.84 | D1 `cumulative_cost_usd` |
| Agent share | **0.226** | 84.84 / 375.75 |
| Snippet-picker share | **0.774** | remainder |
| Per pair attempted | **£0.33** | 375.75 / 1,144 |
| Per answer given | **£0.59** | 375.75 / 636 |
| Per answer matching the key | **£0.86** | 375.75 / 437 |
| Mean cost, a committed pair | £0.26 | 211.84 × 0.79 / 643 |
| Mean cost, an abstained pair | **£0.41** | 263.80 × 0.79 / 508 |
| Abstained over committed, per pair | 1.58× | |
| Mean retries, committed pairs | 1.20 | so 2.2 attempts |
| Mean retries, abstained pairs | 3.00 | the full budget |

Per-country cost per pair: BG £0.385, BA £0.348, ME £0.337, BE £0.334,
MK £0.321, HR £0.302, SE £0.301, FI £0.300. The most expensive country is
**Bulgaria**, not Bosnia.

Timing. `cumulative_wall_clock_ms` is agent-only and gives a median of 61 s;
the reported figures come from the span between the first researcher call and
the finalised row, which is the honest per-pair latency.

| Quantity | Value |
|---|---|
| Median pair latency | **200.0 s** |
| 95th percentile | 341 s, inside six minutes |
| Longest pair | 2,923 s = 48.7 minutes |
| Pairs over 30 minutes | 3 |
| Wall-clock envelope of the run | first final 2026-07-15 17:01:39, last 2026-07-17 13:38:59, **44.6 h** |

Extrapolation to all 36 countries: 44.6 × 4.5 = **200.7 h**, £375.75 × 4.5 =
**£1,691**. At 0.5559 coverage the system commits 2,862 of 5,148 pairs and
declines 2,286; at 0.7014 commit accuracy that is 2,008 right and 855 wrong.

### Model comparison, 156-pair development battery

Source **D1**. Sonnet is the `wide_only` arm of `exp34_retrieval_strategy_s46`,
which is the arm the ablation ladder is replayed off.

| Model, all roles | Commit rate | Commit accuracy | Delivered accuracy | Cost |
|---|---|---|---|---|
| Haiku 4.5 (`exp32_model_haiku`) | **0.4295** (67/156) | 0.6716 (45/67) | 0.2885 (45/156) | £6.14 |
| Sonnet 4.6 (`exp34…s46/wide_only`) | **0.4679** (73/156) | 0.7260 (53/73) | 0.3397 (53/156) | £10.65 |
| Sonnet 4.6 (`…/baseline_narrow_then_wide`) | 0.4936 (77/156) | 0.6883 (53/77) | 0.3397 (53/156) | £10.39 |
| Opus 4.8 (`exp36_model_opus`) | **0.2949** (46/156) | 0.7391 (34/46) | 0.2179 (34/156) | £22.12 |

Opus records 9 `agent_failure` pairs from a Serper outage; Sonnet 8; Haiku 2.
`docs/MODEL_COST_ACCURACY_LANDSCAPE.md` reports 50.0% and 30.1% for Sonnet and
Opus. Those are stale: 50.0% is the `narrow_then_wide` arm, recomputed at
49.4%, and Opus recomputes to 29.5%.

---

## 12. Chapter 4.10, reconstructing the index

Source **D1**; `evaluation/results/exp36_maturity_reconstruction.json`.
Reproduce: `uv run python evaluation/exp36_maturity_reconstruction.py`.

| Quantity | Value |
|---|---|
| Distinct answer-to-score mappings recovered | **345** across 143 questions |
| Questions scored per country | 130 of 143 |
| Spearman, reconstructed ceiling against published | **0.9286** |
| Spearman, reconstructed floor against published | **0.9762** |
| Mean band width | **26.4** points |
| Published score inside the band | **6 of 8** |
| Outside, both above | HR published 73.5 against ceiling 68.6; ME 59.9 against 54.2 |

| Country | Published | Floor | Ceiling | Width |
|---|---|---|---|---|
| FI | 77.9 | 69.9 | 91.3 | 21.4 |
| SE | 77.8 | 61.3 | 83.9 | 22.6 |
| BE | 76.6 | 50.0 | 87.7 | 37.7 |
| HR | 73.5 | 40.3 | 68.6 | 28.2 |
| BG | 62.9 | 28.8 | 70.2 | 41.5 |
| ME | 59.9 | 33.6 | 54.2 | 20.6 |
| MK | 42.8 | 28.3 | 54.9 | 26.6 |
| BA | 15.1 | 12.2 | 24.5 | 12.3 |

Per-country commit accuracy spans 0.528 (MK) to 0.821 (BE); coverage spans
0.385 (BA) to 0.741 (FI).

---

## 13. Chapters 2 and 3, questionnaire and ground-truth facts

Source **D1**, tables `ground_truth` and `questions`.

| Quantity | Value | k/n |
|---|---|---|
| Question-country pairs in the assessment | 5,148 | 36 × 143 |
| Questions | 143 | |
| Countries | 36 | |
| Binary | 124 | 0.867 of 143 |
| Percentage-band | 12 | 0.084 |
| Ordinal-magnitude | 3 | 0.021 |
| Categorical | 2 | 0.014 |
| Count-band | 2 | 0.014 |
| Questions by dimension | Portal 45, Impact 38, Policy 31, Quality 29 | |
| Pairs with an empty evidence comment | **0.1505** | 775/5,148 |
| Capgemini confirms | **0.6311** | 3,249/5,148 |
| Capgemini complements | **0.2690** | 1,385/5,148 |
| Capgemini changes | **0.0998** | 514/5,148 |
| The 29 out-of-reach questions answered yes | **0.7929** | 758/956 yes-or-no rows |
| …over all 1,044 rows of those questions | 0.7261 | 758/1,044 |
| Impact answers that are `i don't know` | **0.0907**, 1 in 11 | 124/1,368 |
| Policy and Portal `i don't know` | 0 | Quality 5 |
| Catalogue questions: rows | 324 | 9 × 36 |
| …confirmed | 280 | 0.864 |
| …changed | 44 | |
| …empty evidence box | 87 | |
| …evidence box reading only `N/A` | 207 | 294/324 = 0.907, nine in ten |
| Countries with a portal registry entry | **22** | `data/catalogue/portals/*.json` |
| Countries with at least one complete snapshot | **9** | AL, DE, FI, FR, HU, ME, NL, RO, SE (D3) |
| Held-out negative golds, gold-string convention | 370 | 262 in stratum A |
| Held-out negative golds, `answer_shape` convention | 368 | 261 in stratum A |

---

## 14. Appendix C, other completed experiments

| Experiment | Population | Recomputed result | Source |
|---|---|---|---|
| EXP-40, cooperative contrast | 156 dev pairs, MT + NL + AL, 78 negative golds | coverage 0.4038 (63/156), commit accuracy 0.6508 (41/63), negative-gold FP wrong-yes 0.2436 (19/78), balanced accuracy 0.2618, Youden J -0.4764 | D1 |
| EXP-28, architecture ablation | 156 dev pairs | **Not recomputable per arm.** Every researcher row is `claude-sonnet-5`, and the canonical dedup leaves only the `researcher_only_s5` finals. Superseded by the 1,144-pair ladder in §10. | D1 |
| EXP-34, retrieval strategy | 156 dev pairs, Sonnet 4.6 | see §11; the two arms deliver the same 53 correct answers and differ only in commit rate | D1 |
| Closed-book probe `cb_heldout_20260725` | 1,144 held-out pairs | see §4 | D1 |
| False-positive audit `heldout_fp_audit_merged94` | 94 EXP-36 false positives, 91 adjudicable | see §6 | JSONL |

---

## 15. What could not be reconciled

- **§4.1's "thirty-two measurable cells".** The recompute covers 36 distinct
  cells across four countries. The count of agreements, 18, reproduces; the
  denominator does not, and 18/36 is 50.0% agreement, not 56%.
- **§4.2's "100% near 0.88, on nine answers".** At 0.88 the yes class holds 82
  committed answers at 98.8%; the class first reaches 100% at 0.95 on 42
  answers. No sweep in any database produces a nine-answer point at 0.88.
- **The snippet-picker prompt and model version for the EXP-36 run.** Not
  logged, by the run's own admission. `claude_usage_log` in D2 records the
  model and the token counts but no prompt version, so the picker call replays
  from its output rather than its inputs.
- **The false-positive audit's judge model.** The merged JSONL carries no model
  field. Chapter 4 says Opus 4.6 and Appendix C says Opus 4.8; neither can be
  confirmed from the artefact.
- **EXP-28 per-arm figures.** The three arms share one experiment id and the
  canonical dedup keeps only the last final per pair, which is the
  researcher-only arm. The rows are Sonnet 5 in any case.
