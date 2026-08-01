# Submission checklist

Everything found across the overnight run (17 passes) and the earlier session,
deduplicated and ordered. Reviewed against snapshot `e4465875`.

Work top to bottom. Each quote is verbatim, so Ctrl-F finds it.

**Total: about 2 hours 40 minutes**, of which the first 50 minutes carry most of
the risk. Four items need a decision from you and are marked DECIDE. Four
citations could not be verified and are listed at the end as accepted risk.

---

## A. Debris that must not ship (25 min)

Nothing here needs thought. All of it is visible to an examiner.

- [ ] **Delete 3 resolved notes.** All three record completed work.
  - `[CC: swept 31 Jul, nothing left to do.` (Appendix)
  - `[CC: this chart was sitting uncaptioned at the end of Appendix E.` (Appendix)
  - `[CC: three rows added in red, 2026-07-29; all three settled 31 Jul` (Appendix)
- [ ] **Resolve 4 figure-caption notes.** These sit in visible caption text.
  - `Figure 1.1: The assumption the questionnaire runs on. [CC red figure, accept or replace.]`
  - `Figure 2.1: Why the objective produces hallucination. [CC red figure, accept or replace.]`
  - `Figure 2.2: Prior-steered retrieval. [CC red figure, accept or replace.]`
  - `Figure 2.3: What each prior method buys and gives up. [CC red figure, accept or replace.]`
- [ ] **`[TABLE IS MISSING] AND IVE MESSED WITH THES SECTION ORDERING – MAKE SURE ALL REFS ARE CORECT`** (Methodology). Delete the note. If Table 3.2 cannot be produced this morning, delete the reference to it too.
- [ ] **`Appendix E [REF] details how these works score against the full criteria.`** Delete `[REF]`.
- [ ] **`as FIGURE X makes plain`** (Discussion). Name the figure or cut the clause.
- [ ] **`Table 4.1.1 Caption: [Say why its 907]`** (Results). Orphan caption with a placeholder.
- [ ] **Stray lone `S`** on its own line in Results, between sections.
- [ ] **`[Good but I think we need a few more citations, and is the register especially in the second half correct`** (Introduction). Your own note.
- [ ] **`[CC — citation sweep, 2026-07-23: eight missing references have now been ADDED`** (References). A 200-word note inside the bibliography.
- [ ] **`[CC: this sentence is right and can now be evidenced. Chowdhury runs over a static curated corpus`** (Discussion). The evidence is inside the note, not in the prose. Fold it in or drop it.
- [ ] **`[CC: F.1 and F.2 are two renderings of the same baselines and they disagree`** (Appendix). See item C3.
- [ ] **Three open Word comments** (Background): "Not sure these need to be in bold - it's giving written by AI", "explain", "check this". Resolve and clear.

---

## B. Number corrections, all sourced (20 min)

Each is confirmed against `evaluation/results/exp36_headline.json`, computed from
the DB. No judgement involved.

- [ ] **368, not 370.** Ledger: `n_no_gold = 368`, stratum A 261, stratum B 107, and 261+107=368.
  - `1,144 question-country pairs and 370 binary negative golds, 262 of which sit in stratum A` (Methodology) → **368** and **261**
  - `against the 370 negative golds` (Conclusion) → **368**
- [ ] **Conclusion FP ladder.** `against the 370 negative golds rise along the same ladder, 46 to 86 to 91` → `against the 368 negative golds rise along the same ladder, 49 to 89 to 94` (matches Table 4.7.1).
- [ ] **`It provides an answer for 55.4 % of questions`** (Introduction) → **55.6%**. 636/1,144 = 55.59%. Appears as 55.6% six times in Results. Also close the stray space before `%`.
- [ ] **`19 of the 1,144 questions were abstained on by at least 7 countries`** → **143**. 1,144 is the pair count.
- [ ] **`reaches 42.9% on the equivalent set`** (Results) → **43.0%**. 42.9% is the balanced-accuracy cell; the 907-gold accuracy is 390/907 = 43.0%.
- [ ] **`against 42.9% for the same model with no retrieval at all`** (Results §4.10) → **43.0%**, same reason.
- [ ] **`a gold answer existed for 94.2% of these questions`** → **94.3%**. 479/508 = 94.29%. Appendix already says 94.3%.
- [ ] **`The replicate battery of §4.6 holds 156 pairs`** (Discussion) → **148**. §4.6 excludes search stalls.
- [ ] **`The ten sections above describe one constraint`** (Results) → **nine**.

---

## C. Decisions only you can make (DECIDE)

These are places the document disagrees with itself and no source settles it.

- [ ] **C1. The closed-book false-positive rate.** The single most consequential item.
  - Prose: `it asserts a wrong yes on 13.9% of the negative golds against the full trio's 24.7%`
  - Table 4.7.1, three paragraphs above: **36.1% (133/368)**
  - If the table is right, the sentence inverts: the closed-book model commits **more** false yeses, not fewer, and the paragraph's whole argument goes with it. I could not settle this. `cb_heldout_20260725` is not in this worktree's DB and there is no closed-book pack under `evaluation/results/`. Two independent agents reached opposite conclusions.
  - Related and equally unresolved: `It commits on 56.8% of the negative golds where the full swarm commits on 50.0%, so it answers more of them and still recovers 42.1%` is arithmetically inconsistent with 133 FPs.
- [ ] **C2. 91 or 94 false positives?** The ablation prose uses 91 (yes-only), the tables use 94 (91 plus 3 not-applicable MK pairs), the Conclusion uses the 91 convention. This produces a systematic offset running through §4.7: prose says 12.5% / 23.4% / 24.7% where the table says 13.3% / 24.2% / 25.5%, and prose says 23.4% vs 27.2% for the stance arms where the table says 24.2% vs 28.0%. **A one-line footnote explaining the 3-pair exclusion is faster and safer than rewriting every percentage.**
- [ ] **C3. Table F.2 versus F.1.** F.2 says 909 binary golds and 59.3%; F.1, Table 4.1.2, the §4.1 prose and the Conclusion all say 907 and 59.4%. Your own note says keep F.1's figures. Deleting F.2 is the quickest fix. Also `4,146 / 81.8%` → `4,144 / 81.9%`.
- [ ] **C4. "Two of the six criteria hold"** (Conclusion) against Table 5.1, which gives Reproducibility "Half met on both" and Attributability "Settled one way, open the other". Either loosen the Conclusion or tighten the table. The Discussion's own wording is the more careful of the two.

---

## D. Grammar and typography (15 min)

One-line fixes, no thought required.

- [ ] `Using a basic large language model in a evidence-retrieval setting` → **an**
- [ ] `LLMs are optimised to match the statistical distribution of its training corpus` → **their training corpora**
- [ ] `but is not the case for the ODMI, where the evidence` → **but that is not the case**
- [ ] `Previous works in retrieval -augmented generation` → close the space
- [ ] `Agreement with answer key, and with and independent measure` → **an independent**
- [ ] `Of the 623 committed answers that with a complete ground truth answer` → **with a complete ground-truth answer**
- [ ] `similarly (§ 4.7).The premise that adversarial` → missing space after the full stop
- [ ] `across 992 pairs The four percentage-band questions` → missing full stop
- [ ] `as while commercial research agents leave a per-claim trail, but have no method` → split into two sentences
- [ ] `the component placed here to govern what the swarm asserts governed how much it asserts` → two `govern` clauses collide
- [ ] `The full list of experiments ran for both tuning and results` → **run**
- [ ] `a policy decision, between balancing accuracy and coverage` → delete one word
- [ ] `Holding the assessment to public evidence divided the questionnaire` → **divides**
- [ ] `the precision failure is invisible on such thin-evidence.` → remove the hyphen
- [ ] `a Verifier with stronger reasoning may be aiming at the wrong bottleneck, leaving the harder task of finding evidence untouched` → missing full stop
- [ ] `Crucially, a large share of the questions ask a team` → banned word, delete it
- [ ] `Furthermore, intrinsic self-correction may bolster` → banned scaffolding
- [ ] `where no single work arrives at the set of requirements the ODMI requires` → tautology
- [ ] `judgment` → **judgement** (Discussion)
- [ ] `Cooperative vs adversarial verifier, end to end` (Appendix C, EXP-40 row) → **Corroborative**, as everywhere else

---

## E. Claims to correct or soften (45 min)

These change what the document asserts, so read each in context first.

- [ ] **`with accuracy on those answers improving similarly`** (Introduction). §4.7 has commit accuracy **falling**, 74.3% → 72.5% → 70.1%. The count of correct answers rises, the rate drops. Suggested: "with the number of correct answers roughly doubling, though accuracy on committed answers edges down".
- [ ] **Duplicate passage in §4.1.** Two drafts of the abstention-asymmetry argument survive, opening `The asymmetry underneath is sharper than the headline` and `Counting every abstention as an error`. **Deleting the second copy also removes the 37%/37.1% split and one of the two 42.9%/43.0% errors.** Highest leverage single edit in the document.
- [ ] **`keeping a complete set of receipts for reproduction`** (Introduction). §4.6 says `The first condition holds with one gap` because the snippet picker writes no row. A contribution claim your own chapter contradicts.
- [ ] **`the search scope, the snippet cap and the ablations in §4.7 were all run on this set`** (Methodology). §4.7 says the ablation ran on the eight held-out countries. This is the contradiction an examiner will actively hunt for, because it is the test-set-contamination question. Strike the ablations from the tuning list.
- [ ] **`A single threshold governs commitment, 0.65`** (Methodology). The same paragraph then describes a second floor at 0.60. Give the dev-sweep result that selected 0.65, and justify or remove the inner floor.
- [ ] **`which is comparatively reliable at finding logical inconsistencies (Tyen et al., 2024)`**. The paper is titled "LLMs Cannot Find Reasoning Errors, but Can Correct Them Given the Error Location". "Finding" reverses their conclusion, and §2.4 cites the same paper for the opposite claim. Change to **judging** or **correcting**. Your argument still stands: the agents have already surfaced the errors.
- [ ] **`Three-way outcome with a calibrated confidence floor driving abstention`** (Appendix E). §2.6 says "nothing makes it track truth" and §4.2 reports ECE 0.299 on no-golds. It sits in a table beside Chowdhury's real ECE of 0.034. Add "calibration assessed post-hoc".
- [ ] **`if the yes-share continues to climb as §1.2 records it doing each cycle`** (Discussion). §1.2 records **maturity** climbing 46% to 86%, not the yes-share. Different quantities. Reword or drop the trend claim.
- [ ] **`With retrieval the swarm recovers 87.0% and 48.9%`** (Results). Mismatched denominators: the preceding closed-book figures are all-gold recalls, these are commit-conditional. Like-for-like the swarm is **54.7% and 24.5%**, which reverses the sentence, and §4.7 already says retrieval nearly halves no-recall.
- [ ] **`on 70.1% of the answers it commits to, against 42.9% for the same model with no retrieval`**. Cross-denominator comparison implying a 27-point gain. The like-for-like pair is 70.1% against 55.3%.
- [ ] **`What the system declines are the questions whose answer is no`**. 200 of 508 abstentions are on yes-golds. Factually wrong as stated.
- [ ] **`Removing the Verifier from the 1,144 pairs drops the commit rate from 46.0% to 26.6%`**. 46.0% is not the system's coverage, which is 55.6%.
- [ ] **`swapping the Verifier's stance changes nothing measurable`**. EXP-42 has corroborative trending worse on negative-gold FPR at p = 0.065. "Nothing measurable" elides a near-significant direction.
- [ ] **`a difference of 0.7 points against a paired standard error of 0.9, equivalent at p below 0.0001`**. Name the TOST and state the equivalence margin, or the reader misreads it as a significance test.
- [ ] **`This work` row, Table 2.2** (Background). Six ticks awarded before any results. Add a forward reference to §4.
- [ ] **`Reports a state-of-the-art MedQA result for GPT-3`** (Appendix). Smit et al. use GPT-3.5-Turbo and GPT-4.
- [ ] **`Policy commits on 74.2% of its pairs ... where Portal commits at 78.4% accuracy`** (Conclusion). 74.2% is coverage, 78.4% is commit accuracy. The parallel structure implies like-for-like.
- [ ] **`Table C.1`** (Appendix) omits EXP-42, which §4.7 discusses with specific numbers. Add the row or drop the word "complete".

---

## F. References (35 min)

- [ ] **25 bibliography entries flagged as never cited in the body.** Bai, Cambronero, Chern, Eurostat, Franklin, Golchin, Irving, Kadavath, Khan, Lipton, Luo, Madaan, Magar, Ogundepo, Pineau, Powell, Sainz, Sculley, Wang (x2), Wen, Weng, Xie, Zhang (x2). Check each, then cite or remove. Some may be cited in a form the scan missed, so verify before deleting.
- [ ] **Thellmann (2024) author list is wrong** per your own note. Check arXiv 2410.08928.
- [ ] **Reiter year** corrected to 1978 in the bibliography. Confirm the in-body citation matches.
- [ ] **Powers et al. (2002)** — RESOLVED. Now cited in §5.3. Nothing to do.

---

## G. Do not touch. Verified correct.

Two earlier findings did not survive checking. Acting on either would introduce
an error.

- **Opus 4.8 is a real model.** `opus-4-8` appears in `agents/tools/llm.py`, `docs/MODEL_COST_ACCURACY_LANDSCAPE.md` and two test files. The document is already right and uses the two versions for two different jobs: **Opus 4.6 is the false-positive audit judge** (§4.3), **Opus 4.8 is the model in the cost-accuracy comparison** (Appendix C, §4.8). Your own appendix note confirms it.
- **The 19% and 69% appendix figures are correct.** Fumega and Gao (2026), *Data & Policy* 8, e20, §4.3 states verbatim: lowest mismatch Data Protection (19%, or 2 out of 12 questions), highest Land Tenure (69%, or 17 out of 25). You reproduce the source exactly and already note their percentages do not reconcile with their own counts. The arithmetic defect is theirs.

Also checked and clean, so do not spend time here:
- All three research questions are answered explicitly, in Discussion §5.1, §5.2, §5.3 and again in the Conclusion.
- All four claimed contributions are delivered.
- Every ratio in the Conclusion computes: 437/623, 385/907, 539/907, 295/339, 90/184, 636/1,144.
- 34 of 36 self-checking sentences across the document verify; the other two are the Fumega quotes above.
- The bibliography resolves in both directions for every cited surname.
- AI-prose scan: 1 flag across 176 red runs, 13 across 293 black paragraphs. Nothing systemic.

---

## H. Accepted risk. Could not be verified.

Not errors. Nobody could confirm them either way overnight. Listed so you know
what is exposed if an examiner checks.

- **Wei et al. (2024), SAFE** — two direct quotes attributed to p.28. The quotes exist; the page number could not be confirmed against the primary PDF. If the NeurIPS pagination differs, p.28 is wrong. **A page number on a direct quote is the highest-risk unverified item here.**
- **Anthropic (2024) model card** — Sonnet 69.0% translated MMLU against 79.0% English. Corroborated by secondary sources only; the PDF exceeded fetch limits. Separately, the card is two generations older than the Sonnet 4.6 actually deployed, which is worth one conceding clause.
- **Williamson, Xi and Breyer (2012)** — the specific claim that solo machine marking needs stricter criteria could not be checked without full text.
- **Feng et al. (2024)** — the regional abstention finding could not be checked without full text.
- **Closed-book table rows** (Tables 4.1.2 and 4.7.1) — internally consistent, since 235+155=390, but not sourceable from any pack. This is why C1 cannot be settled.
- **Cost figures** — £375, 45 hours, £0.28 and £0.41 per pair, 2.4 attempts. No cost pack exists under `evaluation/results/`. Everything downstream follows arithmetically from them.

---

## Honest position

Working through A, B, D, E and F removes every defect anyone found. That is the
part a checklist can promise.

It does not make the dissertation unimpeachable, and two things are worth saying
plainly. C1 is unresolved and load-bearing: if the table is right, a paragraph in
§4.7 currently argues the opposite of what the data show. And the four items in
H stay unverified whatever you do this morning, with the Wei page number the one
most likely to be checked.

Everything else on this list is mechanical.
