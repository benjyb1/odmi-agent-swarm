# Overnight Review Report — Final Compilation

> ## Two corrections, checked after compilation. Do not apply these two.
>
> **1. Opus 4.8 is real. Leave it alone.** Fix-first item 7 and the Appendices
> row say Opus 4.8 does not exist and should be 4.6. That is wrong. `opus-4-8`
> is in `agents/tools/llm.py`, `docs/MODEL_COST_ACCURACY_LANDSCAPE.md` and two
> test files. The document is already correct and uses the two versions for two
> different jobs: **Opus 4.6 is the false-positive audit judge** (§4.3) and
> **Opus 4.8 is the model in the cost-accuracy comparison** (Appendix C, §4.8).
> The appendix CC note says the same. Changing 4.8 to 4.6 would introduce an
> error. Saves 2 minutes; delete the note, keep both numbers.
>
> **2. The 19% and 69% appendix figures are correct. Do not change them.** The
> Number Verification section says to fix them to 17% and 68%. That would
> misquote the source. Fumega and Gao (2026), *Data & Policy* 8, e20, §4.3
> states verbatim: the lowest mismatch was Data Protection (19%, or 2 out of 12
> questions), the highest Land Tenure (69%, or 17 out of 25). The dissertation
> reproduces the source exactly and the next sentence already notes that their
> percentages do not reconcile with their own counts. The arithmetic defect is
> theirs. Nothing to do. This also removes the last item in UNVERIFIED.

## FIX THESE FIRST

Twelve items, ordered by marks-at-risk divided by minutes. Running total in the right column.

| # | Ch. | What | Quote (Ctrl-F) | Min | Σ Min |
|---|-----|------|-----------------|-----|-------|
| 1 | All | **Delete every editorial note.** Search for `[CC:`, `[CC red figure`, `[Good but`, `[Say why`, `[TABLE IS MISSING]`, `[REF]`, `FIGURE X`. The QA sweep counts 17 outstanding notes and 6 scaffolding markers. An examiner sees unfinished draft. | `[CC — citation sweep, 2026-07-23: eight missing references have now been ADDED` / `[TABLE IS MISSING] AND IVE MESSED WITH THES SECTION ORDERING` / `[CC red figure, accept or replace.]` / `Table 4.1.1 Caption: [Say why its 907]` / `as FIGURE X makes plain` / `Appendix E [REF] details how these works score against` / `[Good but I think we need a few more citations` / `[CC: this sentence is right and can now be evidenced. Chowdhury runs over a static` / `[CC: F.1 and F.2 are two renderings of the same baselines and they disagree` | 15 | 15 |
| 2 | Conclusion | **FP ladder wrong.** Three numbers and the denominator are all wrong. | `against the 370 negative golds rise along the same ladder, 46 to 86 to 91` → should be `against the 368 negative golds rise along the same ladder, 49 to 89 to 94` | 3 | 18 |
| 3 | §3 + Conclusion | **368, not 370.** Two chapters use the wrong negative-gold count. | `1,144 question-country pairs and 370 binary negative golds, 262 of which sit in stratum A` → 368 and 261. Also `against the 370 negative golds` in the conclusion. | 3 | 21 |
| 4 | Intro | **Coverage is 55.6%, not 55.4%.** | `It provides an answer for 55.4 % of questions` | 1 | 22 |
| 5 | Intro | **Accuracy does not improve.** The intro says accuracy improves as agents are added; §4.7 shows commit accuracy falls (74.3% → 70.1%). The number of correct answers rises; the rate drops. | `with accuracy on those answers improving similarly (§ 4.7).The` | 5 | 27 |
| 6 | §4.1 | **Duplicate passage.** Two drafts of the same abstention-asymmetry paragraph survive (lines ~77–85 and ~87–93). | `The asymmetry underneath is sharper than the headline. Of the pairs where` | 5 | 32 |
| 7 | Appendix C | **Opus 4.8 does not exist.** Should be Opus 4.6. Appears twice. | `Sonnet 4.6 delivered 34.0% at 1.4 times Haiku's cost per correct answer, and Opus 4.8 delivered` | 2 | 34 |
| 8 | Conclusion | **"Two of the six criteria hold" overclaims.** Table 5.1 gives Reproducibility "Half met on both" and Attributability "Settled one way, open the other". Neither is a clean hold. | `Two of the six criteria hold` | 5 | 39 |
| 9 | Appendix F | **Table F.2 contradicts F.1, §4.1 and the conclusion.** F.2 says 909 binary golds / 59.3%; every other source says 907 / 59.4%. Delete F.2 or align it. | `59.3%` (Table F.2 always-yes row) | 3 | 42 |
| 10 | §4.1 | **"19 of the 1,144 questions"** — 1,144 is pairs, not questions. Should be 143. | `19 of the 1,144 questions were abstained on by at least 7 countries` | 1 | 43 |
| 11 | Appendix C | **"Cooperative" should be "Corroborative".** Every other occurrence uses corroborative. | `Cooperative vs adversarial verifier, end to end` | 1 | 44 |
| 12 | Appendix E | **"calibrated confidence floor" overclaims.** §2.6 says "nothing makes it track truth"; §4.2 reports ECE of 0.299 on no-golds. In a table next to Chowdhury et al.'s ECE of 0.034, this is misleading. | `Three-way outcome with a calibrated confidence floor driving abstention` → add "calibration assessed post-hoc" | 3 | 47 |

**Total: ~47 minutes for the 12 highest-value fixes.**

---

## BY CHAPTER

### Introduction

| Sev | Quote | Issue | Min |
|-----|-------|-------|-----|
| MARKS | `with accuracy on those answers improving similarly (§ 4.7).The` | Contradicts §4.7 ablation. Commit accuracy falls from 74.3% to 70.1%. | 5 |
| EXAM | `It provides an answer for 55.4 % of questions` | Should be 55.6%. | 1 |
| EXAM | `similarly (§ 4.7).The premise that adversarial` | Missing space after full stop. | 1 |
| POLISH | `Crucially, a large share of the questions ask a team` | "Crucially" is on the banned word list. | 1 |

### Chapter 2 — Background and Related Work

| Sev | Quote | Issue | Min |
|-----|-------|-------|-----|
| EXAM | `Using a basic large language model in a evidence-retrieval setting` | "a evidence" → "an evidence". | 1 |
| EXAM | `LLMs are optimised to match the statistical distribution of its training corpus` | "its" → "their". Number disagreement. | 1 |
| EXAM | `but is not the case for the ODMI, where the evidence` | Missing subject. Needs "that is not" or "this is not". | 1 |
| EXAM | `Previous works in retrieval -augmented generation` | Stray space in "retrieval -augmented". | 1 |
| EXAM | `as while commercial research agents leave a per-claim trail, but have no method` | Grammar collision: "as while X, but Y" mixes two constructions. | 1 |
| MARKS | `it improves on standard multi-agent debate by 10.0 points` | No metric or base given. A reader cannot assess magnitude. | 2 |
| MARKS | `since the Researcher and the Verifier are one model separated by a prompt` | The text concedes the Zhu et al. homogeneity condition but never states that the fixed-evidence-pool premise (the actual escape) does not hold. | 5 |
| MARKS | `This work` (Table 2.2, all six ✓) | Self-awarding a full tick on every criterion before any results. Needs forward-reference to §4.1–§4.7. | 3 |

### Chapter 3 — Approach and Methodology

| Sev | Quote | Issue | Min |
|-----|-------|-------|-----|
| MARKS | `[TABLE IS MISSING] AND IVE MESSED WITH THES SECTION ORDERING – MAKE SURE ALL REFS ARE CORECT` | Shouted author note. Table 3.2 absent. Covered by fix-first item 1. | 30 |
| EXAM | `A single threshold governs commitment, 0.65` | Same paragraph introduces a second floor of 0.60. "Single" is wrong. | 5 |
| EXAM | `The first four sections cover the architecture, taking the three agents and the loop they run` | Roadmap does not match actual section order. | 15 |
| EXAM | `22 of the 36 countries carry a registry entry` | Then 9 have a complete snapshot (59% attrition) with no explanation. | 5 |
| EXAM | `within the January 2026 training-data window of Sonnet 4.6, though after August 2025 the point to which` | Hard to parse. Split into two sentences. | 3 |
| POLISH | `The full list of experiments ran for both tuning and results is detailed` | "ran" → "run" (past participle). | 1 |
| POLISH | `a policy decision, between balancing accuracy and coverage` | "between balancing" is broken. Delete one word. | 1 |

### Chapter 4 — Results (§4.1–§4.4)

| Sev | Quote | Issue | Min |
|-----|-------|-------|-----|
| MARKS | Duplicate passage at lines ~77–93. | Two drafts of the abstention asymmetry paragraph left in. | 5 |
| MARKS | `Table 4.1.1 Caption: [Say why its 907]` | Orphan caption with editorial placeholder. | 3 |
| EXAM | `19 of the 1,144 questions were abstained on by at least 7 countries` | 1,144 is pairs; 143 is questions. | 1 |
| EXAM | `On these nine they do not. The self-report and an independent count` | "These nine" has no referent; "they do not" overstates (56% agreement). | 5 |
| EXAM | `and it overturns none of the Verifier's existing decisions` | Vacuously true by design. Presenting a guarantee as a finding. | 5 |
| EXAM | `the component placed here to govern what the swarm asserts governed how much it asserts` | Broken syntax: two "governed" clauses collide. | 1 |
| EXAM | `Removing the Verifier from the 1,144 pairs drops the commit rate from 46.0% to 26.6%` | 46.0% is not the system's coverage (55.6%). Framing misleads. | 3 |
| EXAM | `swapping the Verifier's stance changes nothing measurable` | EXP-42 shows corroborative trends worse on neg-gold FPR (p = 0.065). "Nothing measurable" elides a near-significant direction. | 2 |
| EXAM | `S ` | Lone stray character between sections. | 1 |
| EXAM | `across 992 pairs The four percentage-band questions` | Missing full stop after "pairs". | 1 |
| EXAM | `a difference of 0.7 points against a paired standard error of 0.9, equivalent at p below 0.0001` | TOST not named, equivalence margin not stated. Reader will misread as a significance test. | 5 |

### Chapter 4 — Results (§4.7–§4.9)

| Sev | Quote | Issue | Min |
|-----|-------|-------|-----|
| MARKS | `it asserts a wrong yes on 13.9% of the negative golds against the full trio's 24.7%` | Table says 36.1% (133/368). 13.9% inverts the argument. | 20 |
| MARKS | `It commits on 56.8% of the negative golds where the full swarm commits on 50.0%, so it answers more of them and still recovers 42.1%` | Arithmetic is internally inconsistent given 133 FPs from the table. | 15 |
| MARKS | `on 70.1% of the answers it commits to, against 42.9% for the same model with no retrieval` | Cross-denominator comparison. §4.7 gives forced like-for-like at 42.4% vs 43.0%, no gap. | 5 |
| EXAM | `the false-positive rate climbs with it, from 12.5% to 23.4%` | Systematic 3-FP offset from the table (13.3%/24.2% vs 12.5%/23.4%) throughout ablation prose. No explanation. | 10 |
| EXAM | `the adversarial arm commits a wrong answer on 23.4% against the corroborative arm's 27.2%` | Same 3-FP offset. Table says 24.2% and 28.0%. | 3 |
| EXAM | `What the system declines are the questions whose answer is no` | 200 of 508 abstentions (39%) are on yes-golds. "Are the questions whose answer is no" is factually wrong. | 2 |
| EXAM | `The ten sections above describe one constraint` | Chapter has nine sections, not ten. | 1 |

### Chapter 5 — Discussion

| Sev | Quote | Issue | Min |
|-----|-------|-------|-----|
| MARKS | `as FIGURE X makes plain` | Unresolved placeholder. | 2 |
| MARKS | `if the yes-share continues to climb as §1.2 records it doing each cycle` | §1.2 records maturity climbing, not yes-share. Different quantities. CC note flags this but survives. | 3 |
| EXAM | `Agreement with answer key, and with and independent measure` | "with and" → "with an". | 1 |
| EXAM | `a Verifier with stronger reasoning may be aiming at the wrong bottleneck, leaving the harder task of finding evidence untouched` | Missing full stop at end of paragraph. | 1 |
| EXAM | `The replicate battery of §4.6 holds 156 pairs` | §4.6 says 148 after exclusions. | 1 |
| EXAM | `What appeared instead is that measurement error tracks maturity` | ρ = 0.81 across n = 8 is thin for a rank correlation. Flag the small n. | 2 |
| EXAM | `which is comparatively reliable at finding logical inconsistencies (Tyen et al., 2024)` | Tyen et al. find LLMs *cannot* find reasoning errors. "Finding" reverses their conclusion. Use "judging" or "correcting". | 2 |
| EXAM | `Holding the assessment to public evidence divided the questionnaire into the questions` | Tense error. "divided" → "divides". | 1 |
| POLISH | `the precision failure is invisible on such thin-evidence.` | "thin-evidence" is not a compound adjective here. Remove hyphen. | 1 |
| POLISH | `§5.3 sets out the change to the questionnaire that would remove it` | Forward-reference may be broken if section order shifted. Verify. | 3 |

### Conclusion

| Sev | Quote | Issue | Min |
|-----|-------|-------|-----|
| MARKS | `against the 370 negative golds rise along the same ladder, 46 to 86 to 91` | All wrong. 368, and 49/89/94. | 3 |
| MARKS | `Two of the six criteria hold` | Overclaims vs Table 5.1. | 5 |
| EXAM | `Of the 623 committed answers that with a complete ground truth answer` | Broken syntax. "that with" is not grammatical. | 1 |
| EXAM | `Policy commits on 74.2% of its pairs and returns a wrong yes on half of its 66 negative golds, where Portal commits at 78.4% accuracy` | Parallel structure implies like-for-like. 74.2% is coverage; 78.4% is commit accuracy. | 3 |

### References

| Sev | Quote | Issue | Min |
|-----|-------|-------|-----|
| MARKS | `[CC — citation sweep, 2026-07-23: eight missing references have now been ADDED` | 200-word editorial note in the bibliography. | 2 |
| EXAM | 20 uncited bibliography entries (Bai, Cambronero, Chern, Golchin, Irving, Kadavath, Khan, Lipton, Luo, Madaan, Magar, Ogundepo, Pineau, Sainz, Sculley, Wang 2023, Wen 2025, Zhang R-Tuning, Zhang Self-Alignment, one resolved). | ~19 phantom entries. Cite or remove. | 30 |
| EXAM | `Thellmann (2024) author list is wrong` | CC note flags it; fix not applied. Check arXiv 2410.08928. | 5 |
| EXAM | Reiter year: CC note says "corrected to 1978". Verify in-body citation matches. | Grep body for "Reiter" and confirm year. | 3 |

### Appendices

| Sev | Quote | Issue | Min |
|-----|-------|-------|-----|
| MARKS | `Opus 4.8 delivered` | No such model. Opus 4.6. Two occurrences. | 2 |
| MARKS | Table C.1 missing EXP-42 row. | §4.7 discusses EXP-42 with specific numbers but the "comprehensive" experiment table omits it. | 5 |
| MARKS | `59.3%` (Table F.2) | Contradicts F.1, §4.1 and the conclusion. 907/59.4% is canonical. | 3 |
| MARKS | `Three-way outcome with a calibrated confidence floor driving abstention` | "Calibrated" overclaims. Hand-set threshold with ECE 0.299 on no-golds. | 3 |
| EXAM | `Cooperative vs adversarial verifier, end to end` | Should be "Corroborative". | 1 |
| EXAM | `a gold answer existed for 94.2% of these questions` | 479/508 = 94.3%, not 94.2%. Appendix and §4.2 disagree. | 2 |
| EXAM | `Reports a state-of-the-art MedQA result for GPT-3` | Smit et al. use GPT-3.5-Turbo and GPT-4, not GPT-3. | 2 |
| EXAM | `The baselines the held-out result is read against. Moved here from Appendix E` | "Moved here from Appendix E" is a housekeeping note. Delete. | 1 |

### Number Verification (deterministic)

Two arithmetic mismatches found:
- Appendix states 19% for Data Protection (2 of 12) but 2/12 = 16.67%.
- Appendix states 69% for Land Tenure (17 of 25) but 17/25 = 68%.

Both are rounding errors. Fix to 17% and 68%, or state "roughly" before each.

### Prose Scan (deterministic)

8 flagged runs out of 194. All are in CC notes (which will be deleted) or verbatim reference titles (which must be kept). No action beyond the editorial-note purge.

---

## TOO LATE TO FIX

1. **§3 section order vs roadmap.** The chapter-opening roadmap promises architecture (1–4), evaluation (5–7), controls (8–9). The actual order interleaves them. Reordering sections this morning risks breaking every cross-reference in the document. Note it and leave it.

2. **Missing Table 3.2.** The `[TABLE IS MISSING]` marker flags an absent table. If the table has not been authored, building and formatting one from scratch under time pressure risks introducing new errors. Delete the marker and the reference to "Table 3.2" if the table cannot be produced.

3. **19 uncited bibliography entries.** Removing 19 entries is safe but tedious. Adding citations for them in the body is not feasible this morning. If you cannot do a removal pass, leave them; an examiner may note the padding but it does not change any claim.

4. **The 91-vs-94 FP convention.** The ablation prose (§4.7) systematically uses 91 yes-FPs while the table uses 94 (including 3 not-applicable MK pairs). Aligning them means rewriting every percentage in the ablation prose and the conclusion. If you choose to align, do it in one pass and recheck every number. If you cannot, add a single footnote explaining the 3-pair exclusion.

---

## CONTRADICTIONS TO SETTLE

These are places the document disagrees with itself and the correct value could not be determined from the input files alone. The author must decide.

1. **91 or 94 FPs?** The ablation prose uses 91 (yes-FPs only). The ablation table uses 94 (91 + 3 not-applicable MK pairs). The conclusion uses 46/86/91 (matching the prose convention). Which denominator is canonical? If 91, the table needs a footnote. If 94, the prose and conclusion need updating throughout.

2. **13.9% closed-book FP rate.** The table three paragraphs above gives 36.1% (133/368). 13.9% does not match any reading of the data visible in the inputs. Either 13.9% was computed from a different denominator the reviewers could not see, or it is wrong. If it is wrong, the entire paragraph's argument inverts (the closed-book model commits *more* false yeses, not fewer). The author must recompute from the closed-book arm data.

3. **56.8% closed-book commit rate on neg-golds + 42.1% no-recall.** These two numbers are arithmetically inconsistent given 133 FPs from the table. At least one is wrong. The author must pick the correct values from the source data.

4. **"Two of the six criteria hold" vs Table 5.1.** The Discussion gives Reproducibility "Half met" and Attributability "Settled one way, open the other". The Conclusion counts both as full holds. The author must decide whether to loosen the conclusion or tighten the discussion.

5. **94.2% or 94.3%?** 479/508 = 94.29%. §4.2 rounds down (94.2%); the appendix rounds up (94.3%). Pick one.

---

## UNVERIFIED

These could not be confirmed either way from the input files.

- **Wei et al. (2024), SAFE** — two quotes attributed to "p.28". Page number could not be verified against the primary PDF. If the NeurIPS published version has different pagination, p.28 may be wrong.

- **Anthropic (2024), Claude 3 model card** — Sonnet 69.0% translated MMLU and 79.0% English MMLU. Multiple secondary sources corroborate. Not confirmed against the primary document.

- **Williamson, Xi and Breyer (2012)** — the claim "a machine marking alone would need stricter criteria than it supplies". Paper focus confirmed by secondary sources; specific claim could not be verified without full text.

- **Feng et al. (2024)** — "models abstain less when predicting future election outcomes for African and Asian countries". Title and venue confirmed; the specific regional finding could not be checked.

- **Bold formatting on the four ODMI dimensions** (Background, ¶105) — Benjy's Word comment says "Not sure these need to be in bold — it's giving written by AI." Cannot confirm from plain-text extract whether the bold was removed.

- **Reiter year** — CC note says corrected from 1979 to 1978 in the bibliography. Whether the in-body citation was also corrected could not be confirmed without grepping the compiled document.

- **Appendix arithmetic** — 2/12 stated as 19% (actual 16.7%) and 17/25 stated as 69% (actual 68%). These may be intentional rounding or errors. The number-verify script flagged both.

---

**End of report.** 47 minutes covers the top 12 fixes. Everything marked TOO LATE or UNVERIFIED is noted for the viva, not for this morning.