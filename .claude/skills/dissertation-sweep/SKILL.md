---
name: dissertation-sweep
description: >
  Benjy's mechanical QA sweep for the ODMI agent-swarm MSc dissertation (master
  is Dissertation/Dissertation.docx), sibling to dissertation-review. Use when he
  asks for a consistency, copyedit, proofread, tighten, de-dup, cohesion or
  fact/number pass over the whole doc or a section: "sweep the diss", "check
  every number", "run a consistency pass", "de-dup this chapter", "tighten it",
  "SPaG the whole thing", "make the styling consistent", "nuke mode on the
  results". Two levels: normal (light spot-check) and nuke (exhaustive, every
  number and cite verified against source). Use dissertation-review instead for
  argument, structure, insight and one-off "does this hold up" reactions.
---

# Dissertation sweep

A mechanical quality pass over the dissertation. Where `dissertation-review`
judges the argument, this skill checks that the text is internally consistent,
correct on every number, free of repetition, tight, and uniform in style. It is
the pass you run before submission, not the pass you run while thinking.

**REQUIRED BACKGROUND:** the `dissertation-review` skill's rules apply here in
full and are not restated. In particular: red-only editing (`FF0000`), never
touch black prose or `FF0000`/`C00000` `[CC]` notes except for a direct SPaG or
citation fix, archive the master to `Dissertation/archive/` with a timestamped
name **before any edit**, and never re-add a mark he has cleared. Read that skill
if any of that is not fresh. This skill only adds the sweep itself.

## Two levels

Ask which level if he did not say. Default to **normal** unless he says "nuke",
"deep", "full", "exhaustive", or "before I submit".

**Normal mode** — a light spot-check. Fast, sampled, no exhaustive verification.
Read the target, flag what is obviously wrong or inconsistent, sample a handful
of numbers rather than every one, catch verbatim repeats and glaring style
drift. The goal is a quick reaction that catches the embarrassing stuff, not a
guarantee. Say plainly at the end that it was a light pass and what was sampled
rather than checked.

**Nuke mode** — exhaustive, and slow on purpose. Every number is joined back to a
source. Every citation is primary-source checked. Every cross-reference is
resolved. Every acronym is traced to its definition. Nothing is sampled; if the
axis says "every", it means every one. This is the submission-grade pass. Budget
for it and work section by section rather than pretending the whole doc fits one
sweep.

## The nine axes

Work these in order and report grouped by axis, worst first. Ground every finding
in a location (section name or a quoted phrase), never a general impression.

| # | Axis | Normal | Nuke |
|---|------|--------|------|
| 1 | **Number correctness** | Sample key headline stats; flag any that look off | **Every** number joined to its source (see below); flag each mismatch with both values |
| 2 | **Number self-consistency** | Spot obvious clashes (abstract vs results) | Build a table of every stat and where it appears; flag any figure quoted two ways, percentages that do not sum, restatements that disagree |
| 3 | **Fact correctness** | Sanity-check claims that look shaky | Verify every factual claim against the repo, docs, or primary source; flag unverifiable ones |
| 4 | **Cohesion / de-dup** | Catch verbatim or near-verbatim repeats | Find verbatim **and** conceptual repeats (same point restated in new words); flag fragmented seams where the draft was stitched together and reads as disconnected blocks |
| 5 | **SPaG + clarity** | Obvious typos, agreement, punctuation | Every SPaG error (direct red fix); every sentence carrying two ideas, undefined term, or vague attribution |
| 6 | **Brevity** | Flag visibly bloated passages | Per-section word count reported; flag padding, hedging chains, and sentences that say the same thing twice; never pad |
| 7 | **Style consistency** | Spot obvious drift | Build a house-style register and enforce it: number style (twenty-one vs 21, and where the boundary sits), hyphenation (held-out vs heldout vs held out), UK spelling, capitalisation of key terms, % vs per cent, Oxford comma, tense per section |
| 8 | **Cross-references** | Spot dangling "see Figure X" | **Every** "see Section/Figure/Table X", "as above", "below" resolves; figure and table numbers sequential; each referenced before it appears; captions present and matching content |
| 9 | **Citations / bib** | Spot missing or malformed cites | Every in-text cite has a bib entry and vice versa (flag orphans and uncited entries); plus the full primary-source check from `dissertation-review` |

Two more checks fold in wherever they land, both nuke-weighted:

- **Overclaim / hedge audit.** Flag any sentence that states as settled fact what
  the data supports only weakly. This is examiner-bait and ties to his
  standing rule against pre-results claims. Name the weaker warranted claim.
- **RQ coverage.** Every research question posed in the introduction is answered
  in the conclusion. Flag any promised-then-dropped. Every residue marker
  (TODO, XXX, placeholder text, stray `[CC]` note, tracked-change crumb, empty
  section) is surfaced.

## Verifying numbers against source (axes 1-3, nuke)

Never vouch for a number from the prose alone. Join it back:

- Swarm results, accuracy, match rates, FP counts, per-country and per-dimension
  figures: check against `data/odmi.db` or the relevant file in
  `evaluation/results/`. The DB is the primary store; the results markdown is a
  mirror and can be stale, so prefer the DB and note when the two disagree.
- Costs are notional per his standing preference. Confirm the figure is not
  wildly wrong, then move on; do not rabbit-hole on cost precision.
- Numbers attributed to a cited paper: check the primary text, not an abstract or
  summary. An arXiv id must resolve and the figure must actually be there.
- When you cannot reach a source, flag the number as unverified. Never
  approximate, never infer a plausible value, never state an unverified number.

Watch the worktree trap: `data/odmi.db` is git-tracked and each worktree holds a
diverging copy. Verify against the canonical checkout, not a mutated worktree DB.

## What this skill does not do

- It does not judge the argument, the framing, or whether a finding is the
  strongest available point. That is `dissertation-review` axis 5 (insight).
  If a sweep surfaces a weak argument, note it and hand it back to that skill.
- It does not rewrite black prose to "improve flow". Fragmentation and repetition
  get flagged with a red note and, at most, one drafted replacement paragraph in
  chat for him to react to (per the one-paragraph rule). Cohesion is his to
  restore; you point at the seams.
- It does not move drafted prose into the document. Drafts live in chat.

## Output

Working in short skimmable lines, then the house-style final block after a `---`
divider: Context, Doing, Results, Analysis, Next. Findings are facts and
locations grouped by axis, worst first, no praise. State the mode you ran and, in
normal mode, exactly what was sampled rather than exhaustively checked. Silence
implying full coverage when you sampled is the one thing not allowed.
