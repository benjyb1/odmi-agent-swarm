# LaTeX port and publication-hygiene sweep, 2026-08-04

The dissertation is ported from `Dissertation/Dissertation.docx` to
LaTeX on the KCL `kclthesis` class under `Dissertation/latex/`, the
post-migration sweep of `docs/LATEX_REVIEW_BRIEF.md` has run over the
result, and the whole thing has since been aligned with the supplied
KCL Final Report LaTeX Template (7CCSMPRJ), IEEE citations included.
This file is the consolidated report: what was done, what every gate
showed, and every finding of the sweep, ranked.

Frozen ground truth: `Dissertation/archive/Dissertation.20260804-162405.frozen-latex-port.docx`
(sha1 `6ea6c759`). The master's hash was identical at freeze and at the
end of the sweep, so no concurrent edit was lost. The frozen docx stays
in `archive/` until the PDF is submitted.

## What an Overleaf upload needs

`Dissertation/odmi-dissertation-latex.zip` (also in the repo as the
tracked `Dissertation/latex/` directory) contains the whole project:
`main.tex`, `kclthesis.cls`, `references.bib`, `kcl.png`,
`chapters/*.tex`, `figures/*`. Compiler: pdfLaTeX (the template's own
engine) or XeLaTeX, with BibTeX for the bibliography. Overleaf's
default toolchain runs it as shipped. The whole document, citations
and reference list included, also compiles locally under tectonic, so
every claim below was checked against a compiled PDF rather than
inferred from source.

## Template conformance

Built against the KCL Final Report LaTeX Template (7CCSMPRJ), the zip
Benjy supplied. Its `kclthesis.cls` and the one here are the same file
apart from a single patch, noted below. `main.tex` follows the
template's `Thesis.tex`: the same cover-field block in the same order,
the same package set plus the ones this document needs, the same body
sequence (cover, blank page, front matter, contents, figures and
tables, fancyhdr block, chapters, references, appendix), the same
`tocdepth`/`secnumdepth`, and `\linespread{1}`.

**Citations are IEEE**, as the template specifies. The template writes
`\bibliographystyle{ieeetr}`; this document uses `IEEEtranN`, the
natbib-compatible build of the official IEEE style. Same numbered
`[n]` output, numbered in order of first citation, but `ieeetr` prints
neither URLs, DOIs nor arXiv identifiers, and 26 of the 43 entries
carry one. `IEEEtranN` also supports `\citet`, which keeps the
narrative citations the prose is written around: "Cohen et al. [15]
found that opposition surfaces errors...". The 110 in-text commands
became 56 `\citet` and 54 `\citep`.

`references.bib` was rewritten from biblatex fields to BibTeX ones by
`scripts/latex_port/bib_to_ieee.py`, which reports every rule it
applies. BibTeX ignores fields it does not know without a word of
complaint, so a bare style swap would have dropped all ten journal
names, all seventeen arXiv identifiers and all four DOIs. It also
sentence-cases titles, which is correct IEEE style but flattens proper
nouns: ten brace protections are listed in the script, one of them
found by reading the compiled list ("Trust me, i'm wrong").

### Deviations from the template, each deliberate

| Deviation | Why | To undo |
| --- | --- | --- |
| `kclthesis.cls` loads `report`, not `article` | six numbered chapters and appendices A to J; `article` has no `\chapter`. Section numbering is identical either way. The template's own appendix guidance asks for "Appendix A, Appendix A.1", which `\appendix` gives only under `report` | revert the one line marked "ODMI patch 1" |
| `IEEEtranN` rather than `ieeetr` | `ieeetr` silently drops URL, DOI and arXiv identifiers, and cannot do narrative citations | `\bibliographystyle{ieeetr}`, and expect 26 entries to lose their identifier |
| Front matter is acknowledgements, abstract, nomenclature | the template's order. The docx had the abstract first | swap the two `\chapter*` blocks in `chapters/00-front-matter.tex` |
| `nomencl`, `glossaries`, `makeindex`, the theorem environments and the maths macros are not loaded | nothing in the document uses them | copy the lines back from `Thesis.tex` |
| `contents/figures_tables.tex` is inlined in `main.tex` rather than a separate include | three lines | no effect either way |
| Chapter sources live in `chapters/`, not `contents/` | the port's naming | rename the directory and the `\include` paths |

`\linespread{1}` is the template's, and it overrides the
`\onehalfspacing` the class ends with, so the document is
single-spaced: 132 pages rather than the 145 it ran to before. If KEATS
asks for 1.5 spacing, delete that one line in `main.tex`.

`figures/signature.png` is the template's own red "Signature"
placeholder, shipped so the cover compiles as the template intends.
Replace it with an image of your signature.

One thing the template says that this document does not meet: its
`contents/introduction.tex` states "The dissertation should be less
than 15000 words". The cover word count is 25,675. Check the length
limit for 7CCSMPRJ on KEATS.

## Rubric pass (2026-08-04, after the template work)

The KEATS report rubric audited point by point. Already met: cover
fields, one-page abstract covering objectives, work and findings,
acknowledgements, ToC with page numbers, lists of figures and tables,
consecutive page numbering, captions on all 64 floats, numbered
headings on one system, IEEE references applied consistently, a
structure section closing the introduction, and an LSEP chapter that
names and applies the BCS Code of Conduct and IET Rules of Conduct
(§5.5). No equations in the document, so the equation rules are moot.

Fixed in this pass, all mechanical:

- **Contractions** (rubric: not to be used): the four in body prose
  expanded (were not, is not, did not, does not; §2.2, §2.3, §4.6,
  Conclusion). The two "I don't know" instances stay: both are
  verbatim quotations from national-team responses. "Don't
  Hallucinate, Abstain" stays: a paper title.
- **Nomenclature completeness** (rubric: all abbreviations and symbols,
  alphabetical): added AI, BCS, DIY, DNS, EU, IET, MMLU, SHA-256, URL
  and the symbol rho; list re-checked alphabetical.
- **Every appendix now referred to in the text** (rubric requirement).
  Body parentheticals added for the five that had none: F baselines
  (§4.1), G question bank (§3.4), H catalogue recompute (§3.5), I
  development-set results (§3.7); the appendix opener's "Sections A to
  F" prose became real "Appendices A to F" ranges, which also covers J.
- **Every float now referred to in the text** (rubric requirement).
  Figure 2.1 gets its reference from §2.1; the eight appendix tables
  and one appendix figure that had none are now referenced from their
  chapters' opening sentences. The sixteen Appendix J figures are
  covered by an explicit "Figures J.1 to J.16" range in the J opener;
  per-figure references would be circular for a gallery whose whole
  point is that the body does not use it.

Deliberately not applied: "numerical values should be in 4 decimal
places". The report's values carry the precision of their sources
(published percentages to one decimal, counts exact); padding them to
four decimals would manufacture precision the data does not have.

Residual: the country-code row labels in Table 3.2 (AL, HU, RO...)
are ISO codes with no legend; a one-line caption note would close the
letter of the abbreviation rule if wanted.

## How the port ran

Pipeline in `scripts/latex_port/`, one commit per phase:

1. **Freeze and measure** (`4707bf9` and before): timestamped frozen
   copy archived; 12 Heading1 (4 empty strays), 50 Heading2, 26 tables,
   39 images, 2,613 coloured runs, 7 comments, 0 tracked changes.
2. **Mechanical conversion** (`4707bf9`): sentinel pre-pass wraps all
   1,549 coloured runs so pandoc cannot silently drop the colour
   channel; pandoc 3.10; post-pass merges sentinel spans, folds the
   empty-heading strays, cuts Word's generated contents list, splits by
   chapter, captures the front matter. Parity gate: 4 tokens lost of
   39,710, all explained.
3. **Red triage** (`3759946`): all 1,454 coloured spans read in full.
   Every one is content (abstract, appendix tables, captions,
   cross-reference fragments, reference entries). No instruction-note
   survived to be quarantined; the note-clearing had been done in Word.
4. **Headings, front matter, figures, tables** (`9b03008`): systematic
   `ch:/sec:/app:/fig:/tab:` labels; appendices restructured from
   "8.5 E. Prior Work" sections into lettered chapters; every one of
   the 39 embedded images reconciled by eye against
   `Dissertation/figures_new/` and `evaluation/figures/`; all 26
   longtables get generated captions above the table.
5. **Cross-references** (`5a317ca`): 195 literal references become
   `\ref` with a non-breaking space. `check_refs.py` compares every
   resolved number against the literal it replaced: 168 unchanged, 27
   renumbered, and the renumbers are exactly the intended set (chapter
   2 figures shift one because the docx numbered two figures 2.1;
   chapter 4 floats drop to chapter depth; §8.3 resolves to Appendix
   C). Zero undefined, zero multiply defined, zero literals surviving.
6. **Bibliography** (`736a2fa`): all 43 typed references converted
   field-for-field into `references.bib`; 110 in-text citations
   rewritten. `check_cites.py`: every key resolves; 40 of 43 entries
   cited. Later moved from biblatex author-year to BibTeX and IEEE
   numbering, per the template.
7. **Build clean-up** (`5ace59f`): overfull >5pt from 518 to 24, zero
   missing glyphs, zero undefined references.
8. **Template conformance**: preamble, front matter, spacing and
   citation style aligned with the supplied 7CCSMPRJ template; see the
   section above.

### On the class-assumption note in the migration brief

While this port ran, the brief gained a section saying kclthesis is
article-based, has no `\chapter`, and the conversion should demote
every heading one level. The first half is right: the class as shipped
does load `article`. This port took the other route and patched it to
`\LoadClass{report}` (the change and its reason are in the class
header), so the document keeps real chapters, "Chapter 4" in the prose
points at an actual chapter, floats number 4.1, 4.2 without extra
machinery, and `\appendix` letters the appendix chapters A to J, which
is the form the template's own appendix guidance asks for. Section
numbering is the same under either base class. The whole thing
compiles, and the compiled PDF is what the sweep below verified. The
cover pages are unchanged by the swap. This is now the only edit to
the shipped class: the two other patches this port had made were
reverted once the template's `signature.png` and its `\red`
definition were carried across.

### Deviations from a pure conversion, all deliberate and logged

- **Stale replicate figure replaced.** The docx embed of the §4.6
  figure was an old revision (53 all-abstained / 44 mixed, implying
  67.6% unanimity). The vector `fig_4_7_1_runtorun.pdf` (57/40, 70.3%)
  matches the prose and the EXP-41 register, and ships instead.
- **Stale baselines image dropped.** Appendix F carried an image
  render of a four-row baselines table directly above the real
  five-row longtable that superseded it. The image is gone; the
  Table F.1 caption attaches to the real table. The other image-table,
  "the same run read four ways", survives deliberately as appendix
  Figure J.3, captioned as an alternative rendering of Table 4.1.1.
- **One glued cell repaired.** Table 4.1.1's closed-book coverage cell
  reads `75.6%865/1,144` in the docx itself (a lost line break in the
  source). The port restores the rate-over-fraction stack every
  sibling cell has.
- **Front-matter title block not repeated.** The kclthesis cover
  carries title, author, programme, department, supervisor and word
  count, so the docx's typed title page is not duplicated.
- **Empty headings removed.** Four empty Heading1 and two empty
  Heading2 paragraphs were stray formatting; the two Heading2 strays
  would have renumbered §1.7 and §2.8 had they survived.
- **Figures 4.2.1 and 4.2.2 rebuilt from their SVGs** with the
  `exp36_frozen_headline` source footers and the "(EXP-36)" title
  suffix stripped, which is exactly what the docx's cropped PNG
  exports showed. Vector output, same content.

### Figure reconciliation

All 38 figure sites confirmed by eye against caption and source. 25
carry vector PDFs; 13 keep the docx PNG because no clean vector
exists: the ODMI overview (the only decorative raster in the body),
4.1.1, 4.1.3, 4.5.2, 4.9.1, B.1, and seven appendix J panels. The
docx's figure numbering had four defects that auto-numbering heals:
two figures captioned 2.1, no 4.6.1, no J.15, and one caption typed
with a leading tilde.

## Deterministic gates at the end

- **Text parity** (`check_text_parity.py`): word-multiset comparison
  against the frozen docx. Every residual difference is a generated
  class: citations (rendered from the .bib), cross-references
  (rendered from labels), the regenerated contents and References
  lists, repeated longtable heads, the cover fields, and the repaired
  glued cell. No content word lost.
- **References** (`check_refs.py`): 199/199 resolve; target identity
  verified against the docx literal for each.
- **Citations** (`check_cites.py`): 43 entries, every cited key
  resolves, no key missing. Three entries are cited nowhere in the
  docx either (`anthropic2026`, `edp2024`, `wei2022`); kept via
  `\nocite` so the rendered list matches the typed 43 — author to
  decide whether to prune them instead.
- **Reference list, read against the docx** : all 43 rendered IEEE
  entries matched one for one against the typed Harvard list in the
  frozen docx, on authors, year, title, venue and identifier. One
  defect found and fixed (BibTeX had lowercased "I'm"); nothing else
  differs beyond the expected Harvard-to-IEEE reformatting.
- **Build**: 132 pages, zero undefined citations, zero undefined
  references, zero multiply-defined labels, zero missing glyphs, zero
  LaTeX warnings, 21 overfull boxes over 5pt (all table gutters).
- **Numbers** (`verify_numbers.py` over the `latex_qa.py` manifest):
  96 of 98 self-checking sentences agree; the two mismatches are the
  known Fumega and Gao verbatim quotes, correct as they stand.
- **Word count**: 25,675 on the cover (chapters 1-6 including tables
  and captions). Confirm the required basis on KEATS.

## Fixed during the sweep

Source defects the sweep surfaced whose fix was mechanical and in the
port's domain; each is in the git history:

- Two captions the port itself had truncated while disambiguating the
  duplicate "Figure 2.1" markers: restored to "The Open Data Maturity
  Index" and "Why the objective produces hallucination."
- A stray Word manual line break (`\\` plus an empty struck line) after
  "evidence the agent did not reach." in §2.3.
- Spurious bold on two figure-reference phrases (", in the right-hand
  panel of Figure 1.1," and ", as the loop traced in Figure 2.3 shows,
  since") and three empty `\textbf{ }` fragments: bold cruft left from
  the coloured-run era of the docx.
- 31 pairs of straight ASCII quotes set as proper LaTeX quotes; 4
  U+00B4 acute accents standing in for apostrophes (users´, society´s)
  replaced. Both classes came over from the docx.
- The tick, cross, rho, arrows and comparison glyphs Latin Modern
  lacks became commands; they were missing-character boxes in the PDF.
- Cover word count filled at 25,675 (basis in a main.tex comment).

## FINDINGS

Grouped by chapter, ranked. QUOTEs are Ctrl-F findable in the .tex or
the PDF. The sweep is read-only on prose: everything below is the
author's decision.

### Must not ship

**Cover**

- QUOTE: `\studentnumber{\red{Student number goes here}}`
  PROBLEM: prints "Student number goes here" in red on both cover
  pages.
  FIX: fill in the student number. SEVERITY: MUST-NOT-SHIP
- QUOTE: `figures/signature.png`
  PROBLEM: the cover carries the template's red "Signature"
  placeholder image.
  FIX: replace the file with an image of your signature.
  SEVERITY: MUST-NOT-SHIP
- QUOTE: `\ReleaseProject{0}`
  PROBLEM: prints, in red, "Check the appropriate box below" with two
  unticked release-consent boxes.
  FIX: set `\ReleaseProject{1}` (agree to release) or `{2}` (do not).
  Only the author can make this call. SEVERITY: MUST-NOT-SHIP

**Results (Chapter 4)**

- QUOTE: "A pair it committed to" (Table 4.7) against "A pair that the
  system committed to cost £0.26" (prose below it)
  PROBLEM: the table says £0.28, the prose £0.26 for the same metric;
  636×£0.26 + 508×£0.41 ≈ £374 matches the stated £375 total, the
  £0.28 version does not.
  FIX: reconcile against the cost ledger; the arithmetic favours
  £0.26. SEVERITY: MUST-NOT-SHIP
- QUOTE: "Of the 88 withheld answers sitting below the floor on a
  negative gold, 73 were correct." (§4.1) against "against 79 of the
  89 no answers" (§4.2)
  PROBLEM: the same sub-floor negative-gold population is 88/73 in one
  section and 89/79 in the other; Figure J.6's annotation uses 88/73.
  FIX: verify against the register (docs/RESULTS.md) and align all
  three. SEVERITY: MUST-NOT-SHIP

**Discussion (Chapter 5)**

- QUOTE: "as P28 asks for search-term monitoring" (Table 5.2) against
  "as PT28 invites" (§5.3 prose)
  PROBLEM: the question bank gives search-term monitoring as PT28 (a
  Portal question); the Table 5.2 Policy row cites it as P28.
  FIX: change the Table 5.2 mention to PT28, or reword the row.
  SEVERITY: MUST-NOT-SHIP

**Appendix A**

- QUOTE: "Severity is the product of likelihood and how silently a
  mode commits. `Caught' modes are stopped by a deterministic gate..."
  PROBLEM: restates the Class-column explanation given one paragraph
  earlier almost verbatim.
  FIX: keep only the first sentence of the second paragraph.
  SEVERITY: MUST-NOT-SHIP

**Appendix B**

- QUOTE: "Of the 407 pairs they cover between them, 172 failed both,
  36 the Verifier test alone and 199 the floor test alone."
  PROBLEM: double-counts the overlap its own previous sentence states
  ("Of the 208, 172 also sit below the floor"); consistent figures
  would be 235 = 172 + 36 + 27.
  FIX: verify against the DB and restate. SEVERITY: MUST-NOT-SHIP
- QUOTE: "The remaining 47 sit outside that."
  PROBLEM: the total this remainder depends on (461 of 508) is only
  established in the following paragraph.
  FIX: reorder the two paragraphs. SEVERITY: MUST-NOT-SHIP
- QUOTE: "the advocate pass returns "no" case at all where the gold is
  wrong and the swarm right"
  PROBLEM: garbled; quotation marks read as the verdict label where
  the quantifier is meant, and "case" should be plural.
  FIX: "the advocate pass returns no cases at all where the gold is
  wrong and the swarm right". SEVERITY: MUST-NOT-SHIP

**Appendix C**

- QUOTE: "The completed experiments"
  PROBLEM: heading with no content under it; "Model choice" and its
  paragraph intervene before the register table, then a duplicate
  "Completed experiments:" lead-in appears, contradicting the intro's
  own stated order.
  FIX: move the model-choice paragraph after Table C.1 and drop the
  duplicate heading. SEVERITY: MUST-NOT-SHIP

**Appendix I**

- QUOTE: "The body says that happened but never shows what the swarm
  scored there, so the tuning battery is reported here."
  PROBLEM: informal register, reads as a note about the document
  rather than dissertation prose.
  FIX: e.g. "Chapter 4 states the configuration was tuned on this
  development set but does not report the scores achieved there; this
  appendix reports them." SEVERITY: MUST-NOT-SHIP

**Appendix J**

- QUOTE: "Two carry a note where their numbers do not line up with the
  body, which is exactly why they were left out."
  PROBLEM: only one such note exists (under Figure J.16). The
  candidates for the second are J.3 (closed-book 42.9% over "1,144
  pairs" against the body's 43.0% over 907) and J.4 (0.503/0.701 on a
  different base than the body's binary numbers), neither annotated.
  FIX: add the second note or change "Two" to "One".
  SEVERITY: MUST-NOT-SHIP

**Internal identifiers in reader-facing text** (one decision across
all of them: reword for an outside reader, or keep deliberately as the
receipts trail and say so)

- `data/odmi.db`, `catalogue_snapshots`, `catalogue_metrics`
  (Appendix H provenance note)
- `exp34_retrieval_strategy_s46`, `wide_only`, `data/odmi.db`
  (Appendix I provenance note; also the one remaining prose overfull)
- Table C.1 row labels `exp36_model_opus`, `cb_heldout_20260725`,
  `heldout_fp_audit_merged94` against the "EXP-N" style of the other
  rows
- `claude-opus-4-6` as the reviewer name in Appendix B, where
  neighbouring text writes "Opus 4.8" and "Sonnet 4.6"
- "EXP-36" inside the rendered titles of Figures J.7 and J.9 (a
  re-render with neutral titles needs their generating scripts)

### Should fix

**Front matter** — "Accuracy divided noticeably by answer class"
(divided → varied); "the full three agent swarm" (hyphenate
three-agent).

**Introduction** — "Early work on assessments of this kind use" (uses);
"to both be answerable from the web, whilst also becoming" (drop
"both"); "under the UNECE (2025)" reads awkwardly as a citation
object; RQ2 "sole agents" and capitalised "Adversarial Verification"
against usage elsewhere.

**Background** — comma splice "85.8% against 81.7%, however the same
single model argued"; "and they argue that" with no plural antecedent
(name Yung et al.); the §2 roadmap promises "why LLMs are a sensible
starting point and how they become agentic" which the chapter never
delivers; comma before "than" in "supports the claim, than it is";
tense shift "They also identified... was"; scare-quote scope for
`reasonable reader' varies across three mentions.

**Methodology** — the chapter roadmap's "first four sections... next
three... last two" does not match the real section order (the
deterministic tool is §3.5, after Ground Truth); "two or three brief
search queries, one in English and, if the national language differs,
one in that language" describes two components (and omits the portal
query §3.3 adds); "A Verifier finalises" (the Verifier); "a policy
decision, between balancing accuracy and coverage" (malformed);
"confounds whether... or whether" (confounds X with Y); "an necessary
step"; "balanced cases no-share" (missing word); comma splice "for its
own portal, that band carries a score"; "Do you monitor portal
traffic?'(Appendix D" missing space; Table 3.2's France "partial"
prose never reconciles Estonia's also-"partial" row.

**Results** — caption says "the forced and closed-book rows" but no
row is labelled Forced (rows read Aggregate Accuracy / Commit
Accuracy); "The 50% accuracy of the nine questions pull down" (pulls);
comma splices "Policy is the revealing case, it answers" and "share a
property, both hold" and "past thirty minutes, the longest at
forty-nine, each stalled"; "the recompute points the same ways" (way);
"stratum A holding the four lower-resource languages (Bosnia and
Herzegovina...)" calls countries languages; Table 4.6 caption "Four
arms" over a five-row table (the closed-book row is uncounted and
unintroduced); Table 4.2 "retrieved pages" vs Table 4.3 "retrieved
text" for the same 24-count category; "0.5 is the floor" for balanced
accuracy (a chance baseline, not a floor - the metric goes below it in
the same table); "Tyen et al.'s finding" without a year.

**Discussion** — "the Quality dimension has a commitment rate of
42.7%, at an 18.8% false-positive rate against Policy's 74.2% and
50.0%" leaves the pairing to be inferred; "whose nonexistence can be
proved" attaches to the questions rather than the practice; "Yet, this
does not yet preserve"; "This extends to the poor performance on all
non-binary questions" bridges two different mechanisms; scorecard and
reformulation table cells drop the final full stop in a listable
pattern (about 19 cells); comma splice "92% agreement rate on labels
it committed to, however answers near the threshold".

**Conclusion and small appendices** — "always-yes, evaluation eight:
the same, once negative golds are oversampled" implies the evaluation
set was deliberately rebalanced where the negative-gold share is a
natural property (the deliberate oversampling belongs to the 156-pair
development battery); missing comma "Of the 143 ODMI questions about
20%"; missing comma before "and the `black-box' opacity".

**Appendix C** — "EXP-17" labels two different comparisons two rows
apart while the orchestrator section forbids shared identifiers
(disambiguate or explain); Table C.1's Opus row "worse than Sonnet 4.6
(p < 0.001) and Haiku 4.5 (p = 0.035)" is fine in source - flagged in
extraction only.

**Question bank (Appendix G)** — `("access-URL in the DCAT-AP
specification)?` lacks the closing quote its sibling Q21 has; verbatim
source text, so correct it only if the original questionnaire does.

### Cosmetic

Cover-page overfulls are inherited from the kclthesis class's own
minipage row (1.05 text widths) and are KCL's template as shipped.
todonotes loads in the class with no uses; fancyhdr carries dead
even-page options; two rebuilt figure PDFs are version 1.7 against 1.4
elsewhere; Figure J.12's title is clipped in its source render; the
Table 3.2 missing-value marker renders as two hyphens as it did in
Word; several ch2/ch3 captions are terse ("Prior-steered retrieval.")
next to the sentence-length captions of ch4/ch5; "+ adversarial
Verifier" row label lowercase against "Corroborative Verifier";
Oxford comma in "to identify areas for improvement, and to benchmark"
against the list style elsewhere.

### Raised by a unit and verified fine, no action

- "scored 17 points lower than if it arbitrarily answered yes": 42.4%
  aggregate against the 59.4% always-yes baseline - correct as
  written (the unit compared against commit accuracy).
- "13 of 31 (P1 to P12)" and "9 of 31 (P22 to P29)": correct - P10
  and P26 each split into -a and -b sub-questions.
- "declines... 37.1% of those whose answer is yes": 200 of 539 yes
  golds - correct (the unit divided by the wrong population).
- "(p 0.001)": the source reads p < 0.001; the operator was lost only
  in the sweep's text extraction.
- A family of extraction-only artefacts reported by units
  (`chapterAbstract`, `tabular` colspec fragments, `$rho$`, `\-`,
  `Multi\-SpanQA`, "al_ dcat_ api" underscore spaces, "3pt",
  backtick quotes, "(Anthropic et al., 2024)"): all render correctly
  in the PDF; the extractor has been fixed for the ones that mattered.

### The NUMBERING unit's verdict

- Sequences from the compiled aux: figures 1.1; 2.1-2.4; 3.1-3.3;
  4.1-4.10; 5.1-5.3; B.1; J.1-J.16, and tables 2.1-2.2; 3.1-3.3;
  4.1-4.7; 5.1-5.2; A.1-I.2 - ascending, no gaps, no duplicates,
  uniform chapter depth.
- All 64 captions match the docx verbatim under the stated
  normalisations (number prefixes generated, escaping, the two
  repaired truncations).
- Ten target-identity spot checks, sentence against resolved float:
  ten passes.
- Four literal appendix references had survived at sentence-final
  position ("Appendix E." and kin), masked by a lookahead meant for
  "Appendix E.1" forms; all four now rewritten as \ref and added to
  the manifest, which stands at 199 entries, all resolving.
- fig:odmi-overview (Figure 2.1) is cited nowhere - inherited from
  the docx, which never referenced it either. Add one
  Figure~\ref{fig:odmi-overview} mention in §2.1 or cut the figure.
- Docx figures J.16 and J.17 render as J.15 and J.16: the docx had no
  J.15, auto-numbering closes the gap. Recorded so nobody "fixes" it
  back.
- Appendices G to J and their 21 floats are reachable only through
  the Appendices preamble, never \ref'd from the body - exactly as in
  the docx. Optional pointers: §3.4 to G, §3.5 to H, §3.7 to I,
  §4.1 to J.
- The docx's §N house style renders as the word ("Section 2.2")
  per the migration brief's default; four captions carry it. Say the
  word if § should come back: every one is a \ref either way.

### Could not verify

- Citation and bibliography rendering, and post-biber table-cell
  widths: the local tectonic bundle's biblatex predates the installed
  biber, so the first Overleaf compile is the check. Expect the
  Appendix E first-column overfulls to change size there.
- The KEATS word-count basis for the cover figure.
- Whether the U+00B4 apostrophes and the Q22 missing quote are
  verbatim in the ODMI questionnaire source (the xlsx was not
  opened).
- The second appendix-J "note" the intro promises: which figure the
  author intended.
- `figures/signature.png` does not exist, so the declaration's
  signature line renders blank; supply one if the submission wants it.
