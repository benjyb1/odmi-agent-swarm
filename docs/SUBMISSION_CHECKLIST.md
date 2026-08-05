# Pre-submission checklist, ODMI dissertation

Written 2026-08-05 after the Word to LaTeX migration; re-verified end to
end 2026-08-05 (second pass) against the compiled PDF, with every page
rendered to an image and inspected. The build is now 131 pages (was 132;
the failure-register table lost a page of wrapped labels).

Third pass 2026-08-05, section 5 re-run in full. All 131 pages of the
local build rendered at 150 dpi and inspected again, plus a targeted
sweep of the author's own Overleaf-compiled PDF of the same day
(pdfTeX-1.40.27, 128 pages), which settles most of section 6 by
artefact. The Overleaf copy carried cover and prose edits the repo did
not have; those are now mirrored into the tree (commits `2f4a4b2`,
`c0db7e1`), so a fresh zip upload no longer reverts them. Status below
is against the sources as of this pass.

Legend: `[ ]` outstanding, yours. `[x]` checked and clean. `[fixed]` was
broken, fixed in a pass.

---

## 1. Blocking. The document cannot be submitted until these are done

- [fixed] **Student number.** Now `\studentnumber{K25117192}`, mirrored
      from your own Overleaf edit. Verified on both rendered covers.
- [fixed] **Release-of-project box.** Now `\ReleaseProject{1}` (agree),
      mirrored from your own Overleaf edit. Tick renders on both builds.
- [fixed] **Signature.** Was the template's red "Signature" placeholder
      image. Now typeset directly, `\mbox{{\calligra\LARGE Benjamin
      Bream}}` at `kclthesis.cls:197`, with `\usepackage{calligra}` in
      `main.tex`. No image file involved, so it survives any re-upload
      and needs no binary in the Overleaf project.
      `figures/signature.png` deleted as now unreferenced. Verified on
      the rendered cover, one line, no wrap. Third pass closes the
      pdfLaTeX caveat. Your Overleaf PDF of 2026-08-05 is a
      pdfTeX-1.40.27 build and the calligra signature renders correctly
      on its cover, embedded as Type 1, no Type 3 fonts anywhere in the
      file.

- [ ] **Word count and length limit.** Cover now says 22,606, your
      Overleaf figure, mirrored into the repo. Verified basis. It is
      chapters 1 to 6 excluding tables and captions (a detex recount of
      that basis gives 22,555, delta 51; the same chapters including
      tables and captions give 25,683, which is the old 25,675 cover
      figure's basis). The `main.tex` comment now records this. The
      template's own guidance says "The dissertation should be less
      than 15000 words". Confirm the real 7CCSMPRJ limit and the
      counting basis on KEATS. If the limit binds, this is the largest
      single risk to the mark and nothing else on this list matters as
      much.

## 2. Unaddressed review comments the migration dropped

The frozen docx carried seven comments. Word comments do not survive
conversion, so they are not in the LaTeX and not in the PDF. Second-pass
correction to what this section said before. The first comment was
already acted on in Word before the freeze (the frozen docx has no bold
on the dimension names, verified in its `document.xml`), so six remain,
not seven. The six anchor passages below stand verbatim in the LaTeX.

- [x] "Not sure these need to be in bold - it's giving written by AI"
      → §2.1 dimension names. Already resolved in Word; nothing bold
      there in the frozen docx or the PDF.
- [ ] "explain" (your own)
      → §2.3, "so the gradient signal rewards predicting the most likely
      next token".
- [ ] "Consider rephrasing this (unless 'load-bearing' is accepted
      terminology in engineering)"
      → Chapter 4, "stance of the Verifier is load-bearing".
- [ ] "Is 'decline' the right word here?"
      → Chapter 4 opening paragraph; the comment range sits on "abstains
      on | many it would have got right".
- [ ] "Double check the wording in this bit, is this the clearest way you
      can say this?"
      → §5.1, "the accuracy it reaches in normal operation is bought by
      declining the questions whose true answer is no."
- [ ] "What does this mean?" → §5.1, "structurally underserved".
- [ ] "What does this mean, is 'innocent' the right word here?"
      → §5.1, "innocent reading".

## 3. Content contradictions. Your call, examiner-visible

- [fixed] **£0.28 against £0.26** for the same per-committed-pair cost,
      Table 4.7 against the prose below it. Settled by the register and
      the arithmetic, so the table cell was corrected to £0.26.
      Working. `docs/RESULTS.md` line 520 gives the committed-pair mean
      as £0.26 ($211.84 × 0.79); 636 × £0.26 + 508 × £0.41 ≈ £374,
      matching the stated £375 total, while £0.28 gives £386 and
      matches nothing.
- [ ] **88/73 against 89/79** for the same sub-floor negative-gold
      population. Verified against the canonical analysis
      (`evaluation/figures/abstention_gold_class_by_code.json`,
      exp36_frozen_headline) and `docs/RESULTS.md` lines 274-275. Code
      G holds 199 pairs, of which 89 carry a no gold (79 correct) and
      73 carry a yes gold (18 correct, "around a quarter"). Third-pass
      state. You corrected the Chapter 4 opener to 89/79 on Overleaf,
      and the repo now matches (`c0db7e1`); the same commit corrects
      Table 5.1's Selectivity cell, a third site of the claim the
      earlier passes had missed, which still reads 88/73 on your
      Overleaf. What remains open is Figure J.6. Its caption and its
      baked-in render annotation still say "73 of the 88", in the repo,
      on your Overleaf, and in the List of Figures line the caption
      generates, and they now openly disagree with the corrected body.
      No generating script survives for the figure. Decide. Align the
      caption to 89/79 and re-render or drop the annotation, or cut the
      figure.
- [ ] **P28 against PT28.** Verified against the question bank. Search
      keyword monitoring is PT28 (Portal); P28 asks about training
      plans for civil servants. Table 5.2's Policy row (P22 to P29)
      uses "as P28 asks for search-term monitoring" as its example, so
      a bare swap to PT28 would place a Portal question inside a Policy
      row. No P22 to P29 question covers monitoring (P23's monitoring
      is of policy implementation, not search terms). Third-pass note.
      Your Overleaf now carries exactly that bare swap, "as PT28 asks
      for search-term monitoring" inside the Policy implementation row,
      so the row cites a Portal question. The repo deliberately keeps
      P28 rather than entrench the swap. The row needs a different
      example (P27's assistance activities or P29's annual events both
      fit "whether the team carries out a practice") or rewording,
      which is your prose.
- [fixed] **Appendix B 407-pair overlap** double-counted. Corrected to
      "Of the 235 pairs they cover between them, 172 failed both, 36
      the Verifier test alone and 27 the floor test alone." Working.
      The canonical analysis gives E = 208, G = 199, overlap = 172, so
      the union is 208 + 199 − 172 = 235, Verifier-alone is 36,
      floor-alone is 27. The old sentence's 407 was 208 + 199 with the
      172 counted twice, and its own neighbouring sentence states the
      172 overlap.
- [ ] **Two arithmetic mismatches** flagged by `verify_numbers.py`, both
      in Appendix E and both inside verbatim quotes from Fumega and Gao
      ("19% ... 2 of 12", "69% ... 17 of 25"). Correct as quotations;
      leave them. Re-confirmed this pass, still the only two.
- [ ] **Internal identifiers on the page.** Appendix C's run-ID row
      labels still render as stacked fragments (`exp36_ model_ opus`,
      `cb_ heldout_ 20260725`, `heldout_ fp_ audit_ merged94`), and
      `data/odmi.db`, `catalogue_snapshots`, `catalogue_metrics` and
      `exp34_retrieval_strategy_s46` / `wide_only` appear in Appendix H
      and I prose. One decision across all of them. Reword for an
      outside reader, or keep deliberately as the receipts trail and
      say so.

Found on the third pass, all still in both builds.

- [ ] **Catalogue cells, 36/50% against 32/44%.** The same comparison is
      stated two ways. §4.1 says "Across the thirty-six measurable
      cells the recompute agrees with the published key on eighteen,
      50% agreement" and "disagree on 50% of the measurable cells", and
      the Conclusion says "diverged from the answer key 50% of the
      time". Table 5.1's Convergent row says "agreement on 18 of 32
      measurable cells across four countries, so 44% divergence" and
      §5.3 says "44% of the cells it could reach". Both framings share
      the 18 agreements; they differ on whether Croatia's four
      harvest-artefact cells (Q12, Q13, Q21, Q25, which Appendix H's
      own note calls "an artefact of the harvest and not a measurement
      of the portal", rendered n/a in Figure 4.3) count as measured
      disagreements. `docs/RESULTS.md` §15 records this as
      unreconciled and sides with 36 distinct cells. Counting from
      Figure 4.3's own cells gives 18 agree, 14 differ, 4 n/a. Pick one
      framing and align the four sites; the choice is methodological,
      not arithmetic.
- [ ] **§4.2 "reaching 100\% near 0.95, on nine answers"** pairs two
      different points on the same curve. Both numbers are real and
      both are on the page, but they do not belong together. Figure
      4.4's own right-hand annotation reads "Yes-golds ends 1.00 at
      n = 9", so nine is the count at the far end of the sweep, near a
      threshold of 1.00. `docs/RESULTS.md` line 269 gives "Yes-gold
      accuracy first reaches 1.000 | at 0.95 | 42/42", so at 0.95 the
      count is 42. The sentence takes the threshold from the first
      point and the sample size from the last. Either write "reaching
      100\% near 0.95, on 42 answers" or "reaching 100\% by the end of
      the sweep, on nine answers". Check which one you meant against
      Figure 4.4 before changing it. Supersedes the earlier
      `docs/RESULTS.md` §15 note, which was written against the
      superseded "0.88" wording and concluded no nine-answer point
      existed; the figure shows one, at the other end of the range.
- [ ] **Appendix H omits Montenegro.** §4.1 names four countries with
      harvestable portals (Finland, Croatia, Sweden and Montenegro) and
      Figure 4.3 renders nine ME cells, but Table H.1 lists no ME
      harvest, Table H.2's 75 metrics contain no ME rows, and the
      canonical `data/odmi.db` has no ME in `catalogue_snapshots` or
      `catalogue_metrics`. Figure 4.3 is a docx-era PNG with no
      generating script, so the ME column has no surviving data source
      in the repo. An appendix titled "The Catalogue Recompute in Full"
      is missing one of the four evaluation countries it exists to
      back. Recreate the ME harvest rows, or note the omission and its
      reason in H.
- [ ] **Appendix J's opener promises notes that no longer exist.** "Two
      carry a note where their numbers do not line up with the body,
      which is exactly why they were left out." No J caption carries
      any such note (all sixteen grepped and read on the page; the one
      note that existed at port time is gone). Either add the two notes
      (J.3's closed-book 42.9% is over the register's 1,139
      classifiable pairs, not the "1,144 pairs" its rendered subtitle
      claims, and Table F.1 already states 1,139; J.4's 0.503/0.701
      sit on a different base than the body's binary numbers) or
      reword the sentence.

## 4. Fixed

First pass (cover alignment, front-matter page numbers, fonts, rubric
items) as before:

- [fixed] **Cover fields misaligned.** Two-column tabular now; the
  "Supervisor: LLM Agent Swarm" column slip is gone. Re-verified on the
  page this pass.
- [fixed] **Contents had no page numbers for the front matter.**
  Acknowledgements, Abstract and Nomenclature list as i, ii, iii.
  Re-verified on the page.
- [fixed] **Font encoding.** T1 and `lmodern` for real accented glyphs
  under pdfLaTeX. But see the sterling item below for what T1 broke
  under XeTeX.
- [fixed] Contractions, nomenclature completeness, float and appendix
  references. Re-verified this pass; zero contractions in prose, the
  nomenclature additions all present and alphabetical.

Second pass, all found on the rendered page:

- [fixed] **£ printed as č, ± printed as ś.** 21 sterling signs and 2
  plus-minus signs were literal characters. Under XeTeX with `[T1]`
  fontenc a literal £ resolves by byte to the T1 slot holding c-caron,
  so every cost figure in Table 4.7, §4.8, §5.4 and Appendix C printed
  "č0.33", and Appendix E's "67.0 ± 4.7" printed "ś". pdfLaTeX was
  unaffected, which is why source and Overleaf story looked fine. All
  are now `\pounds{}` and `$\pm$`, correct under both engines.
- [fixed] **"MSc in MSc Advanced Computing"** on the title page. The
  class prints "the degree of MSc in \programme", so the field must not
  itself start with "MSc". Field set to "Advanced Computing"; the cover
  now reads "Degree Programme: Advanced Computing". Put "MSc" back in
  `main.tex` line 28 if you prefer it on the cover label and accept the
  doubled title-page sentence.
- [fixed] **Bold full stop** after the citation "[3]." on page 1
  (`\textbf{.}` cruft) and **spurious bold** on "as Section 1.2
  records" mid-sentence in §5.4. Both unbolded.
- [fixed] **Wrong-direction quotes.** Apostrophes standing as opening
  quotes ('We are working on it', 'Do you monitor search keywords?',
  'Caught'/'LLM-only'/'Structural', 'always'/'standard'/'never', and
  eleven sites in the Appendix G question bank). All now open with a
  backtick. Q22's unbalanced double quote stays. Verified verbatim in
  the ODMI source, which also lacks the closing quote.
- [fixed] **Missing space** in "portal traffic?'(Appendix D".
- [fixed] **Italic span closed two letters early** on
  "merged_responses" in §3.6 (was italic to "merged_respons"). The
  deny-list code confirms the full token.
- [fixed] **Raised-tilde approx signs** in Table C.1 (`\textasciitilde`)
  now `$\sim$`.
- [fixed] **Failure-register table geometry.** The ID column was 19pt,
  so all 34 labels wrapped as "FM-" over "01"; the Severity header
  collided with Status ("SeverityStatus"); "Deterministic" overfilled
  the Stage column. Columns rebalanced; every ID now sits on one line,
  headers have gaps, and the table is a page shorter, which is where
  page 132 went.
- [fixed] **Table 5.1 column collision** "TraceabilityEvery" in the
  Reproducibility row (Verdict column too narrow for the word). Now
  hyphenates like the row label beside it.
- [fixed] **§4.1 heading stranded** as the last line of the Chapter 4
  opener. The section's lead paragraph now follows the heading (moved
  verbatim from below Table 4.1; floats unchanged), so the heading is
  no longer orphaned.
- [fixed] **Table 4.7 committed-pair cost** and **Appendix B overlap
  sentence**, per section 3 above.

## 5. Post-migration checks. What a Word to LaTeX port breaks

Re-run in full on the second pass and again on the third. Deterministic
gates re-run at the final commit (refs 199/199 with 0 undefined, cites
PASS, arithmetic 96/98 with the two known quote mismatches, parity
824 docx-only against 91 tex-only with the +4/+4 delta being exactly
the mirrored Overleaf edits, 131 pages, 18 overfull over 5pt, largest
the class's own 37.9pt, zero missing glyphs); every page of the
compiled PDF rendered at 150 dpi and inspected.

### Content that silently vanishes

- [x] **Word count of body text.** Parity re-run. 820 docx-only tokens,
      87 tex-only; the delta against the first pass is exactly the
      three number corrections above. Classes unchanged (citations,
      cross-references, regenerated lists, repeated headers, deliberate
      insertions). No content word lost.
- [x] **Footnotes and endnotes.** None in the docx, none needed.
- [ ] **Comments.** Seven existed; one was already acted on in Word,
      six remain. See section 2.
- [x] **Hyperlinks.** Regenerated (contents, references). No body
      hyperlink lost.
- [x] **Lists.** Nothing lost (the six numbered paragraphs in the docx
      were empty artefacts).
- [x] **Emphasis.** Re-verified via the sweep; the §2.1 bold names are
      absent in the frozen docx too, so nothing was dropped there.
- [x] **Superscripts and subscripts.** None in the docx.
- [x] **Special characters.** Tick, cross, rho, arrows, comparison
      operators are commands. £ and ± are now commands as well after
      the T1/XeTeX finding above. Zero missing glyphs in the build and
      zero wrong-glyph substitutions on the rendered pages.

### Numbering, which auto-numbering silently changes

- [x] **Cross-references.** 199/199 resolve, 0 undefined, 172 unchanged
      against the docx literal, 27 intended renumbers. Re-run at the
      final commit.
- [x] **No `??` anywhere in the PDF.** Re-checked by page inspection
      and text extraction.
- [x] **Heading hierarchy.** Unchanged; six chapters, appendices A to J.
- [x] **Captions.** All present, tables above, figures below, none
      separated from its float. Re-verified on the page.
- [x] **Lists of figures and tables complete.** 38 figures, 26 tables.
      Re-counted on the rendered front matter.

### Layout, which only shows on the page

- [x] **Cover.** Fields aligned. See section 1 for the placeholders.
- [x] **Blank pages.** One, page 3, template-required.
- [x] **Float drift.** Not re-measured numerically this pass; the
      page-by-page sweep saw no float far from its context.
- [fixed] **Orphaned headings.** One found on the page this pass (§4.1,
      above) and fixed. No other heading strands.
- [x] **Table page breaks.** Every multi-page table (2.1, 5.1, 5.2,
      A.1, B.2, C.1, D.1, E.1, G.1, H.2) repeats its header row on
      every continuation page. Verified on the page.
- [x] **Overfull boxes.** 18 over 5pt (was 21; the table fixes removed
      three). Largest remains the class's own 37.9pt cover header. None
      visible at print size except the items now fixed.
- [x] **Figure resolution.** No pixelation at print size on any page.
- [x] **Fonts embedded, no Type 3 bitmaps.** Re-checked with pdffonts.

### Bibliography

- [x] **43 entries, 124 citation instances over 40 keys, zero
      undefined, three deliberate `\nocite`.** Re-run at the final
      commit. References pages inspected. [1] to [43], no gaps, no
      mangled names, URLs wrap inside the measure.

### Known cosmetics, deliberately left

- Figure 3.1's "below 0.65, or inconclusive" annotation touches the
  abstain box border. In the figure asset; no generating script in the
  repo, so an asset edit is needed if it bothers you.
- Figure J.12's title clips its final ")" at the image edge (source
  render defect; same situation, no script).
- Figure J.10 and J.12 point labels crowd; Figure J.13's hatching
  strikes through its in-bar digits.
- Empty running heads on Conclusion and appendix continuation pages
  (section-less chapters under fancyhdr; the template does this).
- A widow "not." tops §5.1's second page.
- Run-in headings in Appendix C ("The completed experiments" with no
  body, the duplicate "Completed experiments:" lead-in) read as
  assembly seams; noted in the port report findings, your prose.
- Figure 4.5's in-figure annotations use em dashes ("ECE 0.089 —
  under-confident", "ECE 0.299 — inverted"). In the asset, both
  builds; against your own style rule, but a re-render decision.
- On the Overleaf build only, the first failure-register table page
  carries a stale "References" running head (its arabic 73). The local
  build's appendix continuation heads are empty as recorded above; the
  difference is mark timing at the engines' different page breaks.
  Cosmetic, not fixable from the sources alone.

## 6. The first Overleaf compile. Now mostly settled by artefact

Third pass. Your Overleaf-compiled PDF of 2026-08-05 01:59 BST
(Producer pdfTeX-1.40.27, 128 pages) was inspected directly, cover,
front matter, every glyph-bearing page class, both big tables, the
references and the J gallery, plus a word-level text diff against the
local build. That closes most of this section.

- [x] **It compiles under pdfLaTeX.** Proven by the artefact. BibTeX
      ran, references numbered [1] to [43], no `[?]`, ToC and lists
      regenerated consistently with its own pagination.
- [x] **Glyphs under pdfLaTeX.** All 21 sterling signs, both
      plus-minus, ticks, crosses, arrows, ≥, ∼, ρ, en dashes and the
      calligra signature render correctly. Zero Type 3 fonts, zero
      missing-glyph boxes, no mojibake in the text layer.
- [x] **Line breaking and page count.** 128 pages against the local
      131; the diff shows the difference is pagination only, no
      content divergence beyond the edits now mirrored into the repo.
- [ ] **Overleaf still ahead or behind on four things.** Its hyperref
      pdftitle still reads "Automating the EU Open Data Maturity Index
      with a Multi-Agent LLM System" while its cover says no "EU" (one
      line in its main.tex, now already fixed in the repo copy); its
      Table 5.1 cell still reads 88/73 where the repo now has 89/79;
      its Table 5.2 carries the bare PT28 swap (section 3); and its
      §4.1/J.6 88/73 state matches the repo's remaining open item. A
      fresh upload of the rebuilt zip resolves the first two and
      reverts the third to P28; either way section 3's decisions
      remain yours.
- [ ] **Compile timeout.** If the free tier times out, use the KCL
      licence.
- [ ] **Final read of the built PDF**, front to back, at 100%. Nothing
      above substitutes for it.

## 7. Note for whoever runs the QA scripts again

`scripts/latex_qa.py` resolves references and citations from the
compiled `.aux` files. Run it against a tree with no `.aux` present and
it silently reports every reference as unresolved: 121 phantom
scaffolding hits and 333 phantom SPaG issues. Compile first, then run
it. The 133-and-rising "outstanding notes" count is `%` source
comments, which do not render; they are port documentation, not TODOs.
