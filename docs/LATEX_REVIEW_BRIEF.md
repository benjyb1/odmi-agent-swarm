# Publication-hygiene sweep, LaTeX edition

Run this **after** the migration in `docs/LATEX_MIGRATION_BRIEF.md` is
finished and the document compiles. It is the LaTeX successor to the Word
sweep, and it assumes the port is done, not in progress.

The document is about to be published. The author will not read it in full
again. Assume anything you miss ships.

SOURCE: `Dissertation/latex/` plus the compiled PDF
FROZEN COMPARATOR: the pre-migration docx in `Dissertation/archive/`
About 27,700 words of body text, 6 chapters, appendices A to J.

---

## Orchestration

Do not read this end to end in one pass, you will miss things. Fan out using
the harness already in the repo.

`scripts/overnight_review.py` splits the document into units of roughly
3,500 words on paragraph boundaries, runs three at a time with retries,
keeps state so a crash resumes rather than restarts, and has a watchdog in
`scripts/overnight_watchdog.py`. `scripts/launch_overnight.sh` daemonises it
and holds a caffeinate assertion.

It is coupled to the docx in two shallow places only. `MASTER` is hardcoded
at line 41, and it snapshots to `snapshot.docx`. `scripts/dissertation_qa.py`
is the piece that actually reads the docx and emits a JSON manifest plus
per-chapter text. `verify_numbers.py` and `ai_prose_scan.py` read that
manifest rather than the document, so they need no changes at all.

So: write `scripts/latex_qa.py` emitting the **same manifest shape** from the
`.tex` sources, point the supervisor at it, and the rest of the harness works
unchanged. Split units on `\section` boundaries within chapters, because the
appendix chapter alone runs to about 14,900 words and must not be one unit.

Run the deterministic sweep first, once, over everything. It is free and it
catches most of this:

```
python3 scripts/latex_qa.py Dissertation/latex --out build/pub
python3 scripts/verify_numbers.py --qa build/pub/report.json --out build/pub
python3 scripts/ai_prose_scan.py --qa build/pub/report.json
```

Then fan the reading passes out over `build/pub/chapters/`. Add the three
extra units described under BUILD, NUMBERING and FIGURES below. Those catch
things no prose pass will.

---

## What every unit agent looks for

**1. Editorial and personal notes.** Any bracketed aside, any `[CC:...]`, any
note to self, any instruction left in the body. Anything in an informal or
exasperated register that was clearly a note rather than prose. A real
example that survived a long time in the Word master: "[TABLE IS MISSING] AND
IVE MESSED WITH THES SECTION ORDERING".

Two LaTeX-specific places these hide. **`%` comments** are invisible in the
PDF but ship in the source and are read by anyone given the project.
**`\ccnote{}` and `\claudenote{}`** should not exist at all after the
migration; every one is a defect. Report every bracketed fragment you find
and let the author decide, rather than filtering to the ones you judge
important.

**2. Internal identifiers that mean nothing to a reader.** Database paths,
file paths, experiment ids, branch or worktree names, script names, localhost
addresses. Confirmed present in the Word master and likely carried over:
`data/odmi.db`, `exp34_retrieval_strategy_s46`, `exp36_model_opus`. There
will be more. Either the sentence needs rewording for an outside reader or
the identifier belongs in a footnote.

**3. Placeholders and scaffolding.** TODO, TBC, TBD, XXX, FIXME, `[REF]`,
FIGURE X, TABLE X, "STILL NEEDS DOING", lorem, empty brackets. Specific to
this port: `main.tex` ships with `\studentnumber{\red{student number}}` and
`\wordcount{\red{word count}}` as deliberate placeholders. Both must be
filled before submission and both will print in red on the cover if they are
not.

**4. Colour.** There must be none. The migration renders everything black.
Any surviving `\color`, `\textcolor`, `\ccnote`, `\claudenote`, or `@@CL@@`
and `@@CC@@` sentinel from the conversion is a defect. Report the location,
change no wording.

**5. SPaG.** Spelling, agreement, tense, punctuation, doubled words, double
spaces, missing terminal punctuation, unbalanced brackets and braces, stray
single characters alone on a line. The deterministic script finds most of
these. Your job is the ones it cannot, such as a wrong word that is spelled
correctly.

**6. House style.** UK English throughout. No em dashes. Never the word
"genuinely". No AI-tell vocabulary: delve, crucial, landscape, testament,
underscore, tapestry, navigate. No "it is important to note".

**7. Anything else you would be embarrassed to see in print.** Sentences that
trail off, a heading with no section under it, a figure referenced but
absent, a sentence that contradicts the one before it, a claim with an
obvious hole. Use judgement and report it.

---

## BUILD

One agent, against the `.log`, the `.aux` and the compiled PDF rather than
the prose. This replaces the Word package check and none of it is visible in
the text.

- **Every LaTeX warning.** Undefined references, multiply-defined labels,
  missing citations, `??` anywhere in the PDF. All must be zero.
- **Overfull and underfull boxes.** Report anything overfull by more than
  5pt, which is where text starts visibly entering the margin. Table and
  URL-heavy pages are the usual offenders.
- **Leftover pandoc artefacts.** `\tightlist`, `\real{}`, `\pandocbounded`,
  `\hypertarget` wrappers, empty `\label{}`, stray `\protect`. They compile
  silently and mark the document as machine-converted.
- **Font and encoding.** Missing glyph warnings, mojibake, any character that
  renders as a box. The source carries `§`, curly quotes and en dashes.
- **PDF metadata**, which is the equivalent of the Word `docProps` check.
  `hyperref` writes pdfauthor, pdftitle, pdfsubject and pdfkeywords into the
  file. Report what is there and flag anything the author would not want
  attached to a published document.
- **Commented-out blocks.** Any `%`-commented region longer than a line,
  which usually means abandoned prose rather than a real comment.

## NUMBERING

One agent, and this one matters most, because a wrong number reads as a
perfectly plausible right one.

- **Zero literal numbers in the prose.** Grep for `§` followed by a digit,
  and for Figure, Table, Chapter or Appendix followed by a number, anywhere
  outside a caption. Every one should be a `\ref`. The count must be zero.
- **Every `\ref` resolves to the same target the docx pointed at.** Take the
  frozen docx, build the mapping of every reference to its target, then check
  each resolved number in the compiled PDF against it. Renumbering was
  intended, so numbers will differ; what must not differ is which figure,
  table or section the sentence ends up pointing at. Report every mismatch.
- **Figures and tables ascend in document order**, with no gaps and no
  duplicates, at one consistent depth.
- **Every figure and table is cited at least once**, and every citation
  resolves to something that exists. In the Word master, Table 4.4.1 was
  captioned but never cited while a nearby sentence referenced a
  non-existent Figure 4.4.1. Check for that pattern specifically.
- **Captions match the frozen docx verbatim**, allowing for the number.

## FIGURES

One agent, and part of this cannot be automated.

- Every figure is the **vector PDF** from `Dissertation/figures_new/`, not a
  PNG extracted from Word.
- Every figure sits in the **same position in the reading order** and the
  same section as it did in the docx, near the paragraph discussing it.
  Check nothing has floated a page away from its reference.
- **Confirm every figure by eye against its caption.** A wrong image under a
  right caption passes every automated check ever written. Open them and
  look. This is the single most likely way this document ends up confidently
  wrong.
- Two tables existed only as images in the Word master,
  `tab_4_1_1_baselines` and `tab_4_1_2_three_readings`. Confirm they are now
  real tables.

---

## Already verified, do not re-raise

The numbers have had a full pass. 101 of 103 self-checking sentences are
correct and the two exceptions are right as they stand, being verbatim quotes
from Fumega and Gao (2026) whose own arithmetic does not reconcile. Opus 4.6
is the audit judge and Opus 4.8 is the cost-comparison model; both are
correct. The false-positive convention is 91, with 94 used only where the
distinction is stated. The all-36 always-yes baseline is 81.8% over 4,146
binary golds.

## Rules

- **Read-only** unless the author says otherwise. Report, do not edit.
- If told to edit: commit before and after, one change per commit, and never
  edit a `.tex` file another unit is reading.
- **Never state a number you have not seen in a source.**
- Quote verbatim so a finding can be found with Ctrl-F.

## Output

One consolidated report, deduplicated across units, grouped by chapter,
ranked with anything that would embarrass the author in print at the top.

Per finding:

```
QUOTE:    exact verbatim text
PROBLEM:  one line
FIX:      the exact replacement where there is one right answer,
          otherwise the decision the author has to make
SEVERITY: MUST-NOT-SHIP | SHOULD-FIX | COSMETIC
```

No paragraph numbers, they are useless to the reader. Add a final section
listing anything you could not verify. Do not praise anything. Do not
summarise the document.
