# LaTeX migration runbook

Moving `Dissertation/Dissertation.docx` to LaTeX on the official KCL
`kclthesis` class. Written 2026-08-03 against the master at that date.

The port earns no marks by itself. It is worth doing because plain text in
git removes the concurrent-editing problem that currently forces a
shasum-and-wait ritual every time two windows touch the master, and because
`\ref` maintains the 240 cross-references that are hand-typed today.

Read this whole file before starting. The order matters, and two of the
phases are one-way.

---

## 0. Measured state of the source

Taken from the master on 2026-08-03. Re-measure before starting if the
document has moved on.

| Property | Count | Bearing on the port |
|---|---|---|
| Body words | ~27,700 | 38,698 including tables, TOC and appendices |
| Heading1 / Heading2 | 13 / 50 | Numbered, so anything added shifts them |
| Tables | 26 | No merged cells anywhere, which is the good news |
| Embedded images | 40 PNG | Do not reuse these, see phase 6 |
| Figure PDFs available | 23 | In `Dissertation/figures_new/`, vector |
| Figure labels in text | 22 | Names do not map to the PDFs, see phase 6 |
| Cross-references | 240 | 140 section, 7 chapter, 10 appendix, 48 figure, 35 table |
| Citations in text | 101 instances, 49 unique | 63 narrative, 38 parenthetical |
| Entries in `docs/references.bib` | 11 | Against ~68 in the typed reference list |
| Coloured runs | 2,831 | C00000 2,076, FF0000 755, EE0000 4 |
| Hyperlinks | 57 | Will overflow the margin without url breaking |
| Comments | 7 | 5 from a reviewer, unactioned, pandoc drops them |
| Tracked insertions | 4 | Resolve before converting |
| Equations, footnotes, merged cells, SmartArt | 0 | Nothing to do |

Nothing in the list above is fatal. The two that do silent damage are the
coloured runs and the cross-references, because a plain conversion destroys
both without reporting anything.

---

## 1. Decisions needed before anything starts

These change the work, so settle them first.

1. **Bibliography style.** Author-year via biblatex, or numeric via the
   template's default `ieeetr`. The prose is written as narrative citations
   ("Chowdhury et al. assign a different model"), which reads naturally with
   author-year and awkwardly with numbers. Recommend biblatex authoryear.
2. **Figure and table numbering depth.** The source mixes depth-2 (Figure
   3.1) and depth-3 (Figure 4.1.1), so one group must renumber whatever you
   choose. Recommend chapter-level (Figure 3.1, 3.2) throughout, which is
   the LaTeX default and what the brief's consistency rule wants.
3. **Decimal places.** The brief asks for four. The document reports three
   (0.701). Four decimal places on a rate over 1,144 pairs is false
   precision. Either comply, or state the convention explicitly in the
   methodology and report three. Pick one and apply it everywhere.
4. **Compile environment.** Overleaf or local. Pin it, so the submission PDF
   comes from one reproducible place.
5. **Word count basis.** Not stated in `docs/MSc_Brief.docx`. Confirm on
   KEATS what counts before filling `\wordcount`.

---

## 2. Preconditions

- **Freeze the docx.** Tell every other window. From the freeze onward the
  master is read-only. This is the single most important step, because a
  half-ported document with live content in two places is how work is lost.
  The master changed four times in fifteen minutes on the afternoon of
  2026-08-03.
- **Archive the frozen master** to `Dissertation/archive/` with a timestamp
  and `.frozen` in the name.
- **Land everything outstanding on main first**, so the port starts from a
  known commit.
- **Work in a worktree**, not the main checkout.

---

## 3. Phase 1: rescue what pandoc will discard

Do this before any conversion. Each item is destroyed by the conversion and
cannot be recovered from the output.

1. **Extract the 7 comments** with their anchor text into
   `docs/REVIEW_COMMENTS.md` as a checklist. Five are from Miriam Bream and
   are unactioned, including "Not sure these need to be in bold, it's giving
   written by AI", "Consider rephrasing this", and "Is 'decline' the right
   word here?".
2. **Resolve the 4 tracked insertions.** Accept or reject in Word. Do not
   let pandoc's default decide.
3. **Inventory the red passages.** Not the 2,831 runs, the contiguous
   passages. Produce a table of every red passage with its colour, its first
   40 characters and its section, into `docs/RED_TRIAGE.md`.

**Risk.** Skipping this loses reviewer feedback silently. There is no
warning in the output and no way to tell afterwards.

---

## 4. Phase 2: red triage

Red is two different things and a blanket rule damages the document either
way. Blanket red-to-black promotes to-do notes into submitted body prose.
Blanket delete removes the abstract, nomenclature and future-work paragraph.

Sort every passage from `docs/RED_TRIAGE.md` into three buckets.

- **Adopt.** Draft prose that belongs in the dissertation. Rewrite it in
  your own words, then it becomes black body text. This covers the front
  matter inserted on 2026-08-03, which is Claude's wording, not yours.
- **Action then delete.** Instructions to yourself. Do the thing, remove the
  note.
- **Delete.** Stale or superseded.

Nothing may reach the conversion still red unless you have decided which
bucket it is in.

**Risk.** This is the phase where an unnoticed note becomes a sentence in
the submitted document. Treat the triage table as the gate: no unclassified
passage, no conversion.

---

## 5. Phase 3: mechanical conversion

Change no prose during this phase. Improvements come later. A port that
also edits is a port you cannot verify.

1. Pre-pass over `word/document.xml` wrapping any surviving coloured run in
   a sentinel, so the channel survives pandoc.
2. `pandoc --from docx --to latex --extract-media` to a single `.tex`.
3. Post-pass turning sentinels into `\ccnote{}` and `\claudenote{}`.
4. Split into `chapters/*.tex` by Heading1.
5. Wire `main.tex` to the `kclthesis` class with the cover fields.
6. **Get it compiling before anything else.** A skeleton that builds is
   worth more than one perfect chapter that does not.

**Gate.** `check_text_parity.py`: extract the visible text from the `.tex`
and from the frozen docx, normalise whitespace, diff at word level. Every
difference must be explained by a known transformation. This is the check
that proves nothing was lost, and it is the only one that does.

---

## 6. Phase 4: cross-references

240 of them, all literal text today, all of which lie silently the moment
anything renumbers.

1. Put a `\label` on every chapter, section, figure and table.
2. Rewrite every mention. `§2.2` becomes `Section~\ref{sec:criteria}`, per
   the house style decided for this document. Keep the non-breaking space.
3. Same for `Chapter N`, `Appendix X`, `Figure N`, `Table N`.
4. Use `\appendix` so appendices become A, B, C. They currently render as
   "8.5 E. Prior Work Scored Against the Six Criteria", which doubles the
   label.

**Gate.** `check_refs.py`: zero undefined references, zero multiply-defined
labels, and every resolved number compared against the literal string it
replaced in the frozen docx. A reference that resolves to a different number
than the original is either a real renumber you intended or a mistake, and
the script must list both for review.

**Risk.** A `\ref` that resolves to the wrong section is invisible in the
PDF. It reads as a plausible number. Only the comparison against the
original catches it.

---

## 7. Phase 5: bibliography

The largest hidden job. `docs/references.bib` holds 11 entries against
roughly 68 in the typed reference list, and 49 unique citations appear in
the prose.

1. Parse the typed References section into BibTeX candidates.
2. Verify every generated entry against its actual source. A parsed entry
   is a draft, not a reference.
3. Map each of the 49 unique in-text citations to a key.
4. Replace narrative citations with `\textcite` and parenthetical with
   `\parencite`.
5. Delete the typed References section and use `\printbibliography`.

**Gate.** `check_cites.py`: every `\cite*` key exists in the `.bib`, every
`.bib` entry is cited or deliberately retained, no `??` in the output, and
the rendered reference count matches the typed list.

**Risk.** Auto-generated BibTeX from a prose list gets authors, years and
venues subtly wrong. Do not trust a single entry you have not checked
against the source. This is where fabricated references enter a document.

---

## 8. Phase 6: figures

`Dissertation/figures_new/` already holds 23 vector PDFs. Use those.

Do not reuse the 40 PNGs embedded in the docx. Word may have downsampled on
paste, and they are raster in a print document.

**The names do not map to the text.** There are 22 figure labels in the
prose and 21 figure PDFs, and the sets do not align. `fig_2_4_verification_lineage.pdf`
exists with no Figure 2.4 in the text. Figure 1.1 has no PDF. This
reconciliation must be done explicitly, figure by figure, against
`docs/RESULTS.md`, which is the canonical register.

1. Build a mapping table: caption text, PDF file, label, sections that cite it.
2. Confirm each PDF matches its caption by looking at it. A wrong image
   under a right caption is invisible to every automated check.
3. `tab_4_1_1_baselines.pdf` and `tab_4_1_2_three_readings.pdf` are tables
   rendered as images. Rebuild them as real LaTeX tables so they use the
   document font and can be selected.
4. Regenerate anything missing from the 16 `.py` sources.

**Gate.** `check_figures.py`: every figure has a label, a caption and at
least one in-text reference; every referenced figure exists; no figure file
is unused; no figure exceeds `\textwidth`.

**Risk.** This is the phase most likely to produce a confidently wrong
document, because a mismatched figure looks completely normal. The visual
confirmation in step 2 cannot be automated away.

---

## 9. Phase 7: tables

26 tables, none with merged cells, which removes the worst of it.

1. Wide tables will overflow. Table 3.2 carries ten columns and the
   Appendix G question bank runs for pages. Use `longtable` for anything
   crossing a page and `tabularx` or `adjustbox` for anything crossing the
   margin.
2. `booktabs` rules throughout, no vertical lines.
3. Captions above tables, below figures, consistently.
4. Check every table against the docx for lost cells after conversion.

**Gate.** Zero overfull hboxes wider than a set threshold on table pages,
and a cell-count comparison against the source for each table.

---

## 10. Phase 8: compliance sweep

All grep-able once the text is plain.

- No contractions. Three are present today.
- Decimal places per the decision in section 1.
- Units on all variables.
- Every figure and table referenced in the text at least once.
- Consistent variable fonts if any appear.
- Page numbers consecutive, roman front matter then arabic body.
- URLs breaking properly. 57 hyperlinks, and long ones run off the page
  without `xurl`.

**Known defects to fix in flight.** Figure 4.6.1 does not exist, the
sequence jumps 4.5.2 to 4.6.2. "Table 4.7.1156" is a corrupt label. Both
found on 2026-08-03.

---

## 11. Definition of done

The port is complete when all of these pass, not when it looks right.

- [ ] `check_text_parity.py` reports no unexplained differences
- [ ] `check_refs.py` reports zero undefined and zero multiply-defined
- [ ] `check_cites.py` reports zero missing keys and no `??`
- [ ] `check_figures.py` reports every figure labelled, captioned, cited
- [ ] Every figure visually confirmed against its caption, by eye
- [ ] Compile is clean at the agreed overfull threshold
- [ ] Front matter present: cover, abstract, acknowledgements, nomenclature,
      contents, list of figures, list of tables
- [ ] `docs/REVIEW_COMMENTS.md` fully actioned
- [ ] `docs/RED_TRIAGE.md` fully classified and cleared
- [ ] Word count recorded on the cover
- [ ] The frozen docx is in `archive/` and nobody is editing it

---

## 12. Rollback

Every phase commits separately, so any phase can be reverted on its own.
The frozen docx in `archive/` is the ground truth for the whole migration
and must not be deleted until the PDF is submitted.

If the port stalls halfway, the frozen docx is still a complete, submittable
document. That is the property worth protecting, and it is the reason the
freeze in section 2 matters more than anything else in this file.
