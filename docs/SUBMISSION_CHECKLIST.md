# Pre-submission checklist, ODMI dissertation

Written 2026-08-05, after the Word to LaTeX migration. Status against the
compiled PDF at commit `6edbd86`, not against the sources: several of the
defects below were invisible in the `.tex` and only showed on the page.

Legend: `[ ]` outstanding, yours. `[x]` checked and clean. `[fixed]` was
broken, fixed in this pass.

---

## 1. Blocking. The document cannot be submitted until these are done

- [ ] **Student number.** Cover prints "Student number goes here" in red,
      on both cover pages. `\studentnumber{}` in `main.tex`.
- [ ] **Release-of-project box.** Prints the red "Check the appropriate box
      below" with both boxes unticked. `\ReleaseProject{1}` to agree,
      `{2}` to refuse. Only you can make this call.
- [ ] **Signature.** `figures/signature.png` is the template's red
      "Signature" placeholder. Replace with an image of your own.
- [ ] **Word count and length limit.** Cover says 25,675 (chapters 1 to 6
      including tables and captions). The template's own guidance says
      "The dissertation should be less than 15000 words". Confirm the real
      7CCSMPRJ limit and the counting basis on KEATS. If the limit binds,
      this is the largest single risk to the mark and nothing else on this
      list matters as much.

## 2. Unaddressed review comments the migration dropped

The frozen docx carried seven comments. Word comments do not survive
conversion, so they are not in the LaTeX and not in the PDF. **All seven
anchor passages still stand verbatim**, so none has been acted on. Five
are from a reader, two are your own.

- [ ] "Not sure these need to be in bold - it's giving written by AI"
      → §2.1, the bold dimension names (**Policy**, **Portal**, ...).
- [ ] "explain" (your own)
      → §2.3, "so the gradient signal rewards predicting the most likely
      next token".
- [ ] "Consider rephrasing this (unless 'load-bearing' is accepted
      terminology in engineering)"
      → Chapter 4, "stance of the Verifier is load-bearing".
- [ ] "Is 'decline' the right word here?"
      → Chapter 4.
- [ ] "Double check the wording in this bit, is this the clearest way you
      can say this?"
      → §5.1, "the accuracy it reaches in normal operation is bought by
      declining the questions whose true answer is no."
- [ ] "What does this mean?" → §5.1, "structurally underserved".
- [ ] "What does this mean, is 'innocent' the right word here?"
      → §5.1, "innocent reading".

## 3. Content contradictions. Your call, examiner-visible

- [ ] **£0.28 against £0.26** for the same per-committed-pair cost, Table
      4.7 against the prose below it. The arithmetic favours £0.26
      (636 × £0.26 + 508 × £0.41 ≈ £374, matching the stated £375).
- [ ] **88/73 against 89/79** for the same sub-floor negative-gold
      population, §4.1 against §4.2. Figure J.6 uses 88/73.
- [ ] **P28 against PT28.** Table 5.2 cites search-term monitoring as a
      Policy question P28; the question bank gives it as PT28.
- [ ] **Appendix B 407-pair overlap** appears to double-count.
- [ ] **Two arithmetic mismatches** flagged by `verify_numbers.py`, both in
      Appendix E and both inside verbatim quotes from Fumega and Gao
      ("19% ... 2 of 12", "69% ... 17 of 25"). Correct as quotations;
      leave them.
- [ ] **Internal identifiers on the page.** Appendix C's run-ID row labels
      render as broken fragments across three lines
      (`exp36_ model_ opus`, `cb_ heldout_ 20260725`,
      `heldout_ fp_ audit_ merged94`), and `data/odmi.db` and
      `exp34_retrieval_strategy_s46` appear in Appendix H and J prose.
      These mean nothing to an examiner and look like leaked scaffolding.

## 4. Fixed in this pass

- [fixed] **Cover fields misaligned.** The class stacks six labels in one
  centred minipage against six values in another. Your title wraps to two
  lines, which pushed the value column out of step: the cover read
  "Supervisor: LLM Agent Swarm" and "Word Count: Dr Johanna Walker". Now a
  two-column tabular.
- [fixed] **Contents had no page numbers for the front matter.** The
  template leaves `\pagenumbering{gobble}` in force across
  Acknowledgements, Abstract and Nomenclature, so all three reached the
  contents list with a blank page number. The rubric requires one. They
  now read i, ii, iii.
- [fixed] **Font encoding.** Added T1 and `lmodern`, so the pdfLaTeX build
  has real glyphs for the accented author names and the plus-minus sign,
  hyphenates those words, and stays vector rather than bitmap.
- [fixed] Contractions, nomenclature completeness, and the appendices and
  floats that were never referred to in the text (previous commit).

## 5. Post-migration checks. What a Word to LaTeX port breaks

This is the section that matters most for this document, because these are
failures a normal proofread does not look for. Each was run against the
frozen docx `Dissertation.20260804-162405.frozen-latex-port.docx`.

### Content that silently vanishes

- [x] **Word count of body text.** Word-multiset parity against the frozen
      docx. Every residual difference is accounted for: generated
      citations, generated cross-references, the regenerated contents and
      reference lists, repeated table headers, and the deliberate
      insertions. No content word lost.
- [x] **Footnotes and endnotes.** The docx has zero of both, so nothing to
      lose. Worth stating because pandoc handles them badly and their
      absence would otherwise look like a loss.
- [ ] **Comments.** Seven existed and are gone. See section 2.
- [x] **Hyperlinks.** 58 in the docx. All 56 in the front matter were the
      generated contents list, regenerated by `\tableofcontents`; the
      other 2 were reference-list URLs, regenerated from the `.bib`. No
      body hyperlink lost.
- [x] **Lists.** Six numbered-list paragraphs in the docx, all empty
      formatting artefacts. Nothing lost.
- [x] **Emphasis.** Bold 356 to 299 and italic 132 to 69, the differences
      being headings (now `\chapter`/`\section`) and the typed reference
      list's italic journal titles (now generated by the `.bst`).
- [x] **Superscripts and subscripts.** None in the docx.
- [x] **Special characters.** Tick, cross, rho, arrows and comparison
      operators became commands; they were missing-character boxes.
      Straight quotes and `´`-as-apostrophe corrected. Zero missing
      glyphs in the build.

### Numbering, which auto-numbering silently changes

- [x] **Every cross-reference resolves to the number it had in Word.**
      199 checked against the docx literal each replaced: 172 unchanged,
      27 renumbered, and every renumber is intended (the docx numbered two
      figures 2.1, chapter 4 floats drop to chapter depth, §8.3 becomes
      Appendix C, and the docx had no J.15). Zero undefined, zero literal
      references left behind.
- [x] **No `??` anywhere in the PDF.**
- [x] **Heading hierarchy.** Six chapters, 38 sections, appendices A to J
      continuous. Four empty headings in the docx removed; two of them
      would have renumbered §1.7 and §2.8.
- [x] **Captions.** All 64 verbatim against the docx. Two the port itself
      truncated were caught and restored.
- [x] **Lists of figures and tables complete.** 38 figures, 26 tables,
      matching the float count exactly.

### Layout, which only shows on the page

- [x] **Cover.** See section 4. This is the one that was actually broken.
- [x] **Blank pages.** One, page 3, which the template asks for.
- [x] **Float drift.** No figure or table lands more than two pages from
      its first mention, apart from appendix floats referenced from the
      body, which is where appendices belong.
- [x] **Orphaned headings.** No section heading is the last line of a page.
- [x] **Table page breaks.** Multi-page tables repeat their header row.
      Verified on the page, not just in the source.
- [x] **Overfull boxes.** 518 down to 21 over 5pt, all table gutters. The
      largest, 37.9pt, is the class's own cover header, where three
      minipages total 1.05 of the text width. It does not show.
- [x] **Figure resolution.** Every raster is 248 dpi or better at its
      printed width. Word export commonly downsamples; this one did not.
- [x] **Fonts embedded, no Type 3 bitmaps.**

### Bibliography, rebuilt from scratch and therefore fully re-checkable

- [x] **All 43 entries present**, read one by one against the typed
      Harvard list in the frozen docx: authors, year, title, venue,
      identifier. One defect found and fixed, BibTeX had lowercased "I'm".
- [x] **Every citation resolves.** 124 instances over 40 keys, zero
      undefined. Three entries are cited nowhere in the docx either and
      are kept with `\nocite` so the list still shows 43.
- [x] **Citation grammar survived Harvard to IEEE.** Zero possessive
      citations, zero year-as-noun constructions, zero literal
      "(Author, 2024)" survivors.
- [x] **No URL lost.** The docx list carried five; the `.bib` has nine,
      the four extra being DOIs now rendered as links.

## 6. Cannot be verified here. Check on the first Overleaf compile

Every local check used tectonic, which is XeTeX. The submission PDF will
be built by Overleaf with pdfLaTeX. These need eyes once, after the first
compile there:

- [ ] **It compiles at all.** Nothing in the source is XeTeX-specific and
      the only non-ASCII characters are `£` and `±`, both covered by T1,
      but this has never actually been run through pdfLaTeX.
- [ ] **Line breaking and page count.** pdfTeX and XeTeX break lines
      differently, so the 132 pages and the 21 overfull boxes are XeTeX
      numbers. Re-measure the overfull list on Overleaf and re-check the
      table gutters.
- [ ] **BibTeX ran.** The reference list should be numbered [1] to [43] in
      citation order, and no `[?]` should appear. Overleaf runs BibTeX
      automatically; if the list is missing, compile twice.
- [ ] **Compile timeout.** 132 pages with 25 vector figures may exceed the
      free-tier limit. If it times out, use the KCL Overleaf licence.
- [ ] **Final read of the built PDF**, front to back, at 100%. Nothing
      above substitutes for it.

## 7. Note for whoever runs the QA scripts again

`scripts/latex_qa.py` resolves references and citations from the compiled
`.aux` files. Run it against a tree with no `.aux` present and it silently
reports every reference as unresolved: 121 phantom scaffolding hits and
333 phantom SPaG issues. Compile first, then run it.
