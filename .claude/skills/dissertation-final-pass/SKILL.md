---
name: dissertation-final-pass
description: Benjy's submission-eve final pass over the ODMI dissertation (master is Dissertation/Dissertation.docx). Use when he asks for a final check, a last read, a submission sweep, a pre-hand-in pass, or "is this ready to submit". Runs the deterministic QA scripts, reconciles every outstanding note, verifies the numbers, then reads each chapter for narrative and salience. Reports findings in chat as exact quotes with a burn-down order. Sibling to dissertation-review (argument and insight) and dissertation-sweep (consistency and copyedit); this one is the whole-document pre-submission gate.
---

# Dissertation final pass

The last read before hand-in. Assume hours, not days. The job is to find what an
examiner would catch and to rank it so he can burn it down in one pass through
the document.

Two failure modes matter more than anything you might miss: changing his prose,
and stating a number you have not verified. Both are worse than a missed typo.

## Run the machine first

Deterministic checks come before any reading. They are exhaustive, they cost
nothing, and they never hallucinate.

```bash
python3 scripts/dissertation_qa.py Dissertation/Dissertation.docx --out build/qa
python3 scripts/verify_numbers.py --qa build/qa/report.json --out build/qa
```

`dissertation_qa.py` writes `build/qa/report.json` and splits the document into
`build/qa/chapters/*.txt`. Read those splits for the judgement passes rather than
re-parsing the docx.

What the scripts already cover, so do not spend reading time on it: outstanding
notes, leftover scaffolding, blank and malformed headings, figure and table
cross-references, numbering gaps, duplicate sentences, citation-to-bibliography
agreement in both directions, house-style violations, mechanical SPaG, and the
red-run inventory.

## Passes, in order

**1. Notes reconciliation.** Every note in `report.json["notes"]`, whatever its
colour. For each one, read the surrounding text and return a verdict:

- `ANSWERED` the text now does what the note asked. Say what resolved it.
- `NOT ANSWERED` still owed. Say in one line what is missing.
- `STALE` the note describes a state that no longer exists.

Quote the note and quote the sentence that resolves it. A verdict with no quoted
evidence is a guess. Answered and stale notes are deletion candidates; he
approves the list before anything is removed.

His own notes count. A black bracketed paragraph asking a question is as
load-bearing as a red `[CC]`.

**2. Numbers.** His standing rule, and it overrides the usual thoroughness
instinct:

> A number is a finding only when it contradicts the source, or contradicts
> itself elsewhere in the document.

Never report that a base should be stated. Simplifying 94 to 91 is his editorial
call and is not an error. Precision-shopping between 37% and 37.1% in two places
is, because the document disagrees with itself.

Three sources of truth, strongest first:
1. The arithmetic in the sentence. `verify_numbers.py` checks every percentage
   written next to its fraction. These verdicts are exact.
2. The analysis packs in `evaluation/results/`, above all
   `exp36_headline.json`, which is computed from the canonical DB.
3. `RESULTS.md` and the DB directly, for anything the packs do not carry.

Do not match a number to a source by value alone. With over a thousand ledger
entries every figure finds a spurious neighbour, and the result is confident
nonsense. Match on the named quantity or report it unverified.

**3. Chapters.** One agent per chapter, in parallel, each reading its own split
plus the abstract and the research questions. Looking for: claims set up and
never paid off, findings buried under weaker adjacent points, sentences carrying
two ideas, terms used before they are defined, and any place a stronger argument
is available than the one made. Return at most eight findings per chapter, each
with an exact quote.

**4. Cross-chapter.** After the chapter agents return. Each research question
answered explicitly in the conclusion, one by one. Abstract matching the results
actually obtained. Terminology drift. Contradictions between chapters.

**5. AI prose.** Targeted, not blanket. The red runs are where drafted text
ended up, so that is where the tells cluster. Run the `humaniser` rules over red
runs only. His supervisor flags AI text, which makes this a credibility risk
rather than a style preference.

## Output

Findings in chat. Every one carries:

- the **exact quote**, long enough to search for in Word. He cannot use
  paragraph numbers, so a finding without a quote is unusable.
- what is wrong, one line
- the fix, one line
- severity: `EXAMINER-VISIBLE`, `MARKS-AT-RISK`, or `POLISH`
- minutes to fix

Group by chapter so he works through the document once. Rank within group.

Keep a separate short tail for anything too structural to fix in the time
available. Mixing "move this section" into a midnight fix list wastes his
attention. Say plainly that it is noted and not actionable tonight.

## Editing rules

The red in this document is incorporated prose, not review marking. Roughly 400
red runs are body text and only a handful are notes, so red no longer marks
anything and writing new red notes is invisible ink.

- Never edit black or red body prose.
- The only edit this pass makes is deleting notes he has signed off, in both
  colours.
- Archive to `Dissertation/archive/` with a timestamped name before any write.
  The archive is the only undo he has.
- String surgery on `document.xml` only. Parsing and re-serialising renames
  namespace prefixes and Word rejects the file.

## Voice

UK English. No em dashes. Never the word "genuinely". Lead with the conclusion,
then the reason. Findings are facts and locations, not praise and not
encouragement. If something is fine, say nothing about it.
