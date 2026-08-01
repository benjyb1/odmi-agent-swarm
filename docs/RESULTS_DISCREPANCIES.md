# Discrepancies: dissertation against recomputation

Every place `Dissertation/Dissertation.docx` states a number that recomputation
from the databases does not support. Both values are given, with the location
and which is correct. The docx was read only and not edited; fixing it is a
separate job.

Recomputed 2026-07-31 against `data/odmi.db`, the orphaned
`.claude/worktrees/exp36-run/data/odmi.db` and an LFS-recovered catalogue
snapshot. Full method, definitions and reproduction paths in `docs/RESULTS.md`.

Severity: **A** the stated number is wrong; **B** the number is right but names
the wrong quantity, or two places in the document disagree; **C** rounding or a
naming slip with no effect on a claim.

Counts: **15 wrong numbers in the docx** (A1 to A17, less A8 which was withdrawn
on re-check and A17 which is a repo markdown file rather than the
dissertation), **16** right-number-wrong-quantity or internal-disagreement
cases, **5** rounding and naming notes.

---

## A. Wrong numbers

| # | Location | Document says | Recomputed | Verdict |
|---|---|---|---|---|
| A1 | §1.4 Approach | coverage "55.4 %" | **55.6%** (636/1,144) | Document wrong. Every other statement in the document says 55.6%. |
| A2 | §4.1, third paragraph | "The run contains 94 of them", describing pairs where the swarm "committed a yes against a negative gold" | **91** committed a yes. 94 is the count of *any* wrong commitment on a negative gold (91 yes plus 3 `not_applicable`) | Document wrong on the definition it states. §4.3's "the 91 cases where the swarm committed a yes" is right. |
| A3 | §4.1, same sentence | "51.1% of the 184 the swarm was willing to commit on" | **49.5%** (91/184) on wrong-yes. 51.1% is 94/184 | Follows from A2. |
| A4 | Table 5.1, Generalisability row | "0 of 16 count-band correct" | **1 of 16** | Document wrong. §4.5's "the swarm gets 1 of the 16 count-band questions exactly right" is right. |
| A5 | §4.5 and §5.3 | Quality without the catalogue questions commits at "81.5%" / "0.815" | **80.3%** (53/66) | Document wrong. 81.5% would need a denominator of 65. |
| A6 | §4.1 | "Across the thirty-two measurable cells the recompute agrees with the published key on eighteen, 56% agreement" | 18 agreements is right; the population is **36** cells (4 countries × 9 questions), so **50.0%** | Denominator wrong. |
| A7 | §4.1 and §4.9 | "The self-report and an independent count disagree on 44% of the measurable cells" | **50.0%** (18 of 36 disagree) | Follows from A6. |
| ~~A8~~ | ~~§4.1, Montenegro~~ | **Withdrawn.** An earlier pass of this list called the Montenegro licence claim unsupported. That was a checking error: it read Q21 and Q22, which are URL-presence metrics, not licence metrics. On the licence questions the claim holds — Q25 open licence recomputes to **70.0%** (629/898) and Q12 licence presence to **75.6%** (679/898), both against a `>90%` key. See C5 for the one small precision point that remains. | | |
| A9 | §4.2 | "Of the 161 that are scoreable, 73 carry a yes gold and 88 carry a no gold … against 73 of the 88 no answers" | The sub-floor population (code G) is **73 yes and 89 no**; the withheld answers are correct on **18 of 73** yes and **79 of 89** no | Document wrong on the no-gold counts. "Around a fifth of the yes answers are correct" understates: 18/73 is 24.7%. |
| A10 | §4.2 | "the 0.65 to 0.70 group is correct 73% of the time" | **73.4%** on negative golds only (69/94). Over every committed answer in that band it is **65.5%** (131/200) | Right number, unstated population. Say "negative golds in that band". |
| A11 | §4.2 | yes-gold accuracy "reaching 100% near 0.88, on nine answers" | At 0.88 the class holds **82** committed answers at **98.8%**; 100% is first reached at **0.95** on **42** answers | Not reproducible from any database. |
| A12 | §4.8 | per-country cost "from £0.31 in Finland to £0.39 in Bosnia" | Finland **£0.30** is the cheapest, correct in kind. The most expensive is **Bulgaria at £0.385**; Bosnia is £0.348 | Wrong country named at the top of the range. |
| A13 | §4.8 | a committed pair "cost £0.28" | **£0.26** | Document wrong. The £0.41 abstained figure is right. |
| A14 | §4.8 | "an abstained pair costs 50% more than a committed one" | **58% more** (£0.41 against £0.26) | Follows from A13. |
| A15 | §4.8 | a committed pair "required 2.4 attempts" | mean `retry_count` on committed pairs is **1.20**, so **2.2 attempts** | Document wrong. The abstained figure, the full three-retry budget, is right. |
| A16 | Table 5.2, Quality row | "Quality, computable from the catalogue, 13 of 29 (Q2, Q12, Q13, Q16 to Q18, Q21, Q22, Q25 to Q29)" | The tool computes **9**: Q12, Q13, Q16, Q17, Q18, Q21, Q22, Q25, Q27. Q2, Q26, Q28 and Q29 have no metric function | Document wrong, and it contradicts "Nine Quality questions" in §2.2, §3.1 and §3.5. |
| A17 | `docs/MODEL_COST_ACCURACY_LANDSCAPE.md` | Sonnet commit rate 50.0%, Opus 30.1% | **46.8%** (73/156) and **29.5%** (46/156) | **The dissertation is right and the doc is stale.** §4.8 and Appendix C already say 46.8% and 29.5%. 50.0% belongs to the `narrow_then_wide` arm, which itself recomputes to 49.4%; the dissertation quotes `wide_only`, the arm the ablation ladder replays off. Fix the markdown, not the docx. |

---

## B. Right number, wrong quantity, or the document disagreeing with itself

| # | Location | Issue | Resolution |
|---|---|---|---|
| B1 | Tables 4.5.1 and 4.7.1, "negative-gold FP rate" columns | Every cell is the **any-wrong-commit** rate, while the §4.7 prose uses **wrong-yes**. Trio 25.5% (94/368) against 24.7% (91/368); Researcher alone 13.3% against 12.5%; + Verifier 24.2% against 23.4%; corroborative 28.0% against 27.2%; closed book 36.1% against 13.9% | Both are computed correctly. The document settles on wrong-yes, so the tables should carry 24.7 / 12.5 / 23.4 / 27.2 / 13.9, or the column must be relabelled. The closed-book row is the extreme case: 36.1% against 13.9% is a factor of 2.6, and the prose comparison "13.9% against the full trio's 24.7%" only works on wrong-yes. |
| B2 | Table 4.4.1, stratum A | Negative-gold FP 22.2% (58/261) and committed-only 45.0% (58/129) are **any-wrong**. On wrong-yes they are **21.1%** (55/261) and **42.6%** (55/129) | Stratum B is 33.6% under both, so only the A row moves. The §5.1 scorecard's "stratum A FPR 0.222 vs B 0.336" inherits this. |
| B3 | Table 4.5.1, Impact and Quality | 26.4% and 18.8% are **any-wrong**. On wrong-yes they are **25.7%** (36/140) and **14.6%** (7/48) | Policy 50.0% and Portal 13.2% are identical under both conventions, which is why the inconsistency is easy to miss. |
| B4 | §3.7 against Chapter 4 | §3.7 says "370 binary negative golds, 262 of which sit in stratum A" (gold-string convention). Chapter 4 uses 368 and 261 throughout (`answer_shape = 'binary'`) | Both are right on their own convention. Pick `answer_shape`, which Chapter 4 already uses, and change §3.7 to 368 and 261. The two extra pairs are `P29:SE` and `P29:BA`, a count-band question with a bare `no` gold. |
| B5 | §3.7 | Bosnia's no-share "84.9%" is the gold-string convention (79/93). Its three neighbours in the same sentence, BG 43.6%, BE 20.9%, FI 24.2%, are all `answer_shape` | On `answer_shape` Bosnia is **84.8%** (78/92). One convention per sentence. |
| B6 | Chapter 4 against Appendix E | Always-yes on the held-out eight: 59.4% over 907 in Chapter 4, 59.3% over 909 in Appendix E | Both arithmetically right. Under the recommended convention it is **59.4% over 907**. |
| B7 | §5.3 against Appendix E | Always-yes across 36 countries: 81.9% in §5.3, 81.8% over 4,146 in Appendix E | 81.9% is 3,393/4,144 (`answer_shape`) and 81.8% is 3,393/4,146 (gold string). **81.9%** is the one consistent with Chapter 4. |
| B8 | Table 4.1.2 against Table 4.7.1 | Closed-book coverage is 76.7% (878/1,144) in one table and 75.6% (865/1,144) in the other | **865 is right.** 878 counts 13 abstentions on `not applicable` golds as commitments, which is exactly the error the 70.4%-versus-70.1% commit-accuracy variant makes. |
| B9 | §4.1, consecutive paragraphs | One says the closed-book run "reaches 43.0% on the same 907 golds", the next says it "reaches 42.9% on the equivalent set" | 43.0% is forced accuracy (390/907); 42.9% is balanced accuracy. Different quantities, both right. A third quantity, delivered accuracy over 1,139 pairs, is also 42.9%. Name the one meant. |
| B10 | §4.10 | "reproduces the published key on 70.1% of the answers it commits to, against 42.9% for the same model with no retrieval at all" | 70.1% is commit accuracy; 42.9% is balanced accuracy. The comparable closed-book figure is **55.3%** commit accuracy. As written the sentence compares two different measures. |
| B11 | §4.4 | "Measured only on the negative golds it committed to, the correlation with maturity rises to 0.83" | **0.833** on any-wrong, **0.905** on wrong-yes | Right on the any-wrong convention. Under B1 it becomes 0.905. |
| B12 | §4.5 | catalogue questions' "accuracy of 50%" | **51.5%** strict match (17/33), or 75.8% counting `near_match` (25/33) | Round to 52%, or say "about half". |
| B13 | Appendix C, EXP-28 row | Reports commit rates 0.237 / 0.391 / 0.468 and commit accuracies 0.649 / 0.689 / 0.726 for the three-arm ladder | Every EXP-28 researcher row is **`claude-sonnet-5`**, a model the project does not use, and the canonical dedup leaves only the researcher-only arm, so the row cannot be recomputed per arm. The 1,144-pair ladder in Table 4.7.1 supersedes it. Drop the row or mark it Sonnet 5 and historical. |
| B14 | §4.3 against Appendix C | The audit judge is "Opus 4.6" in §4.3 and "Opus 4.8" in the Appendix C note | The merged audit JSONL carries **no model field**, so neither can be confirmed from the artefact. Already flagged in a red note. |
| B16 | §4.1 | "The disagreements do not all run in the same direction, so this is not a case of countries systematically inflating their score" | Literally true, but the split is **11 overstatements against 4 understatements** (3 not band-comparable). The lean is real even if it is not unanimous | Soften to something like "the disagreements run mostly but not only one way", or state the 11-against-4 split. As written it reads as balance where there is a 3:1 tilt. |
| B15 | Appendix E, closed-book row | "42.9%, against a 47.3% floor, 1,139 held-out pairs" | Confirmed exactly: 489/1,139 = 0.4293 against 539/1,139 = 0.4732. The 1,139 excludes 5 `flag_review` pairs | Correct, but it is a third distinct quantity that reads as the same 42.9% used twice elsewhere. Say which. |

---

## C. Rounding and naming

| # | Location | Document | Recomputed | Note |
|---|---|---|---|---|
| C1 | §2.1 | "15.1% of the 5,148 pairs carry no comment" | 775/5,148 = **15.05%** | Rounds to 15.0% or 15.1% depending on convention. Harmless. |
| C2 | §5.4 red note | "§1.2 records average maturity climbing from 46% to 83%" | §1.2 body text says **86%** | The note and the body disagree. Neither is a project figure; it comes from the 2025 ODMI report. |
| C3 | Appendix C, `exp36_model_opus` | "£22.12, £0.65 per correct answer" | £22.12 confirmed; 22.12/34 = **£0.65** confirmed | Correct. |
| C4 | §4.8 | "£375", "45 hours", "roughly 200 hours and £1,700" | £375.75, 44.6 h, 200.7 h and £1,691 | All confirmed within rounding. |
| C5 | §4.1 | Montenegro's licence coverage "recompute reads 71%" | Q25 open licence **70.0%**, Q12 licence presence **75.6%**; both land in the `71-90%` band | The claim is right. "71%" looks like the band floor rather than either raw value. Say 70% and name Q25, or say "the 71-90% band". |

---

## D. Confirmed, for the avoidance of a second pass

These were checked against source and reproduce exactly. Do not re-audit them.

Coverage 0.5559 (636/1,144); commit accuracy 0.7014 (437/623) with its
[0.664, 0.736] interval; yes 0.8702 (295/339) and no 0.4891 (90/184); recalls
0.5473 and 0.2446; abstention 0.3711 against 0.5000; forced accuracy 0.4245
(385/907); balanced accuracy 0.3959; always-yes 0.5943; ECE 0.0632 overall and
0.2990 on negative golds, with 3 negatives against 77 yes golds in the top bin
and six of ten bins empty; the abstention table 208 / 199 / 30 / 24 / 19 / 16 /
12 summing to 508, with 172 overlapping and 479 carrying a gold; 413 adjudicator
abstains plus 82 gate withholdings plus 13 inconclusive; 636 committed answers
through the quote gate and 24 ungrounded; Table 4.3.1's 24 / 208 / 636 / 276;
the Verifier's +165 and -13 and the Adjudicator's +65 and -0; 110 adjudicator
commitments at 0.5909 against the Verifier path's 0.7251; 84 of 91 audited false
positives judged too weak and 7 sufficient, 0 of 91 vindicating the swarm, with
the charitable split 16 / 69 / 6; stratum abstention 0.5227 against 0.3654 and
commit accuracy 0.6113 against 0.7682, negative-gold abstention 0.5057 against
0.4860, negative recall 0.2720 against 0.1776, the code-E split 101 against 107,
the code-G split 143 against 56 carrying 96% of the gap, and 16 fetch errors
against none with 14 in Bulgaria; Finland's 48.3% and Bosnia's 12.8%; Spearman
0.81, 0.88 and 0.74; the whole dimension table's pairs, coverage and commit
accuracy; forced accuracy 30.2% for Quality and 48.4% for Policy; binary pairs
992 at 0.7229; the four percentage-band questions declined on all 32 pairs;
ordinal 29.2% and categorical 37.5%; every cell of Table 4.6.1 and the 148-pair
intersection, 0.7027 unanimity, 0.9216 label agreement, 0.0143 accuracy range,
60.5% against 80.0% class unanimity, 42 of 47 and 17 of 47 on evidence paths;
every coverage and commit-accuracy cell of Table 4.7.1 including Researcher
alone at 220/296; the closed-book row's 865/1,144 and 476/860; 243 agreements,
289 discordant at p = 0.8140 and the 58.7% oracle; the stance contrast 51
against 59 at p = 0.5047 and 18 against 32 at p = 0.0649; yes-recall 52.1% to
55.8% and no-recall 10.9% to 7.3%; 86 of 142 committed noes at exactly 0.65 with
none reaching 0.95; no-gold accuracy hitting zero at 0.81; £375 and its three
per-pair denominators, the 23/77 agent-picker split, median 200 s, 95% inside
six minutes, three pairs over thirty minutes with the longest at 49, and 45
hours; 345 rubric keys, Spearman 0.929 and 0.976, a 26.4-point mean band, six of
eight inside it, and Croatia and Montenegro outside it in the same direction;
per-country commit accuracy 52.8% to 82.1% and coverage 38.5% to 74.1%; Table
3.1's answer shapes; 63 / 27 / 10 on the Capgemini decision split; 79.3% yes on
the 29 out-of-reach questions; one Impact answer in eleven being "I don't know"
with none in Policy or Portal; 280 confirmations against 44 amendments over 324
rows with 87 empty and 207 `N/A`; 22 registry entries and nine complete
snapshots; 19 questions abstained on by seven or more countries with 12 of them
internal-practice; France's 37.8% over five thousand datasets and Romania's
100% and 99.7% across two harvest routes; EXP-40's 0.40 / 0.65 / 0.24 / 0.262 /
-0.476.
