# Brief for the agent doing the LaTeX migration

Paste this whole file as the opening prompt. It is written to be
self-contained, but `docs/LATEX_MIGRATION.md` holds the phase-by-phase plan
and should be read before starting.

---

## What you are doing

Port `Dissertation/Dissertation.docx` to LaTeX on the official KCL
`kclthesis` class, without losing a word, a figure, a table, a reference or
a working note. The document is an MSc Advanced Computing dissertation for
King's College London, roughly 27,700 words of body text plus appendices.

You are converting, not editing. Do not improve the prose, do not fix
wording, do not restructure. A port that also edits cannot be verified,
because the checks work by comparing the output against the source.
Anything you think should change, write down and raise at the end.

## Ground truth

The frozen docx in `Dissertation/archive/` is the ground truth for the whole
migration and must not be deleted until the PDF is submitted. If the port
stalls halfway, that file is still a complete submittable document. Protect
that property above everything else.

Archive a timestamped copy before any write to the master. Never write to
the master without re-checking its hash immediately beforehand.

## Hard constraints

1. **Never write black body prose into the docx.** If you edit the docx at
   all, additions go in `C00000` red, which is the agent channel. `FF0000`
   is the author's own channel; do not touch it, and do not touch black
   prose. This rule was set emphatically and is not negotiable.
2. **Edit the docx by string surgery on `word/document.xml` only.** Parsing
   and re-serialising with ElementTree renames namespace prefixes, breaks
   `mc:Ignorable`, and Word then refuses to open the file. Reading with
   ElementTree for analysis is fine. Writing is not.
3. **Two or three windows edit this repo at once.** The master moved four
   times in fifteen minutes on 2026-08-03 and three times in an hour on
   2026-08-04. Hash before, hash after, abort on mismatch. Locate elements
   by unique text, never by index.
4. **Work in a git worktree, never the main checkout.** Land finished work
   on `origin/main`; a task is not done until it is merged and pushed.
5. **Deleting a `.docx` is refused by the tooling.** Build to a fresh
   filename and copy over. Put scripts in files rather than heredocs.
6. **British English, no em dashes, no contractions** in anything you write.

## Environment

- `pandoc 3.10` is installed.
- **There is no LaTeX toolchain on this machine.** No pdflatex, no MacTeX,
  no latexmk. You cannot compile. Every gate you build must therefore work
  on the text, not on a PDF. The author compiles on Overleaf and reports
  errors back.
- `Dissertation/` is in `.gitignore`. To track the LaTeX project you must
  change the rule to `Dissertation/*` and then re-include, because git
  cannot re-include anything inside an excluded directory.

## Measured state

Re-measure before you start, because the document moves. As of 2026-08-04:

| Property | Value |
|---|---|
| Heading1 / Heading2 | 13 / 50, numbered |
| Tables | 26, no merged cells anywhere |
| Images | 40 PNG embedded |
| Figure captions / references | 19 / 27 |
| Table captions | 14 |
| Cross-references in prose | roughly 240, all hand-typed |
| Citations | 101 instances, 49 unique, all plain prose |
| `docs/references.bib` | 11 entries, against roughly 68 typed |
| Coloured runs | C00000 about 2,055, FF0000 755, EE0000 4 |
| Hyperlinks | 57 |
| Comments | 7, five from a reviewer |
| Equations, footnotes, merged cells, SmartArt | 0 |

Already extracted for you, do not redo:
- `docs/REVIEW_COMMENTS.md` the 7 comments with anchor text
- `docs/RED_TRIAGE.md` the coloured regions as 89 decidable blocks
- `docs/LATEX_MIGRATION.md` the twelve-phase plan

## Method

Work phase by phase from `docs/LATEX_MIGRATION.md`. Commit each phase
separately so any one can be reverted alone.

Build a gate for each phase and run it. Do not verify by reading. On this
document the parity gate caught two silent failures that reading would
never have surfaced, and both would have shipped.

The one check that proves the port worked: extract the visible text from
the `.tex` and from the frozen docx, normalise, and compare as a word
multiset. Anything missing is a loss until explained.

---

## Traps, all of them observed on this document

**Pandoc discards character colour with no warning.** The two note channels
live entirely in colour. A plain conversion destroys 2,800 coloured runs and
the output looks perfectly fine. Wrap coloured runs in ASCII sentinels
inside a scratch copy of the docx first, convert, then turn the sentinels
into `\ccnote{}` and `\claudenote{}`. Count sentinels in against macros out,
and assert zero strays.

**Everything before the first `\chapter` lands in the preamble.** If you
split by chapter and discard what precedes the first one, you silently lose
the entire front matter: abstract, acknowledgements, nomenclature. This
happened. Capture it.

**Empty Heading1 paragraphs exist in this docx.** They are stray formatting,
not chapters, and they split the Introduction into six fragments. Fold any
empty-titled chapter back into the one above it.

**Stripping XML tags glues adjacent cells together.** Two table cells
reading "superseded by Table 4.7.1" and "156-pair dev battery" become
"Table 4.7.1156", which looks exactly like a corrupt label. Any text
extraction must be element-aware, inserting a separator at paragraph and
cell boundaries. A defect was reported twice off the back of this.

**A caption regex must require a colon.** Captions here are
`Figure 4.6.2: Outcome agreement...`. Accepting a full stop makes the
sentence "Figure 4.2.1 sweeps the threshold..." parse as a caption for a
figure that does not exist.

**Word's generated contents list is not content.** Its entries will show up
as missing text in a parity check. `\tableofcontents` regenerates them.
Expect and exclude them, but be sure that is what you are excluding.

**Figure numbering mixes depths.** Two-level in Chapters 1, 2, 3 and 5,
three-level in Chapter 4. Renumbering is therefore unavoidable, so accept
auto-numbering, put a `\label` on everything, make every mention a `\ref`,
and never type a number again.

**Cross-references fail silently.** A `\ref` resolving to the wrong section
reads as a perfectly plausible number in the PDF. The only thing that
catches it is comparing each resolved number against the literal string it
replaced in the frozen docx. Build that comparison.

**The figure PDFs do not map onto the figure numbers.** There are 23 PDFs in
`Dissertation/figures_new/` and 19 figure captions, and the names do not
align. `fig_2_4_verification_lineage.pdf` exists with no Figure 2.4 in the
text. Reconcile them one by one against `docs/RESULTS.md`, which is the
canonical register, and confirm each by looking at it. A wrong image under a
right caption passes every automated check ever written.

**Do not reuse the 40 PNGs embedded in the docx.** Word may have
downsampled them on paste. Use the vector PDFs.

**Two tables exist only as images.** `tab_4_1_1_baselines.pdf` and
`tab_4_1_2_three_readings.pdf`. Rebuild them as real tables so they use the
document font and can be selected.

**Auto-generated BibTeX gets authors, years and venues subtly wrong.** The
bibliography is roughly 57 entries short. Parsing the typed reference list
is the sensible way to draft them, but every entry must then be checked
against its actual source. This is the route by which fabricated references
enter a dissertation, and it is the single worst thing that could happen to
this document.

**Long URLs run off the page.** 57 hyperlinks, invisible as a problem in
Word. Load `xurl`.

**Appendices currently render as "8.5 E. Prior Work Scored Against…".** Use
`\appendix` and drop the manual letters.

**Do not resume from `Dissertation/overleaf-github/`.** It is a hand-rolled
`\documentclass{report}` from 16 July, it is not the official class, and it
predates weeks of edits.

---

## Definition of done

- Text parity against the frozen docx reports no unexplained differences
- Zero undefined references, zero multiply-defined labels
- Every citation key resolves, no `??` in the output
- Every figure and table has a label, a caption and at least one reference
- Every figure confirmed by eye against its caption
- Front matter present and correct
- `docs/REVIEW_COMMENTS.md` and `docs/RED_TRIAGE.md` fully worked through
- The frozen docx still sits untouched in `archive/`

Report honestly. If a phase is incomplete, say which and why. Negative
results and unresolved problems are worth more here than a clean-sounding
summary.
