# Progress Slide Deck — 22 May 2026

Results-focused slide deck for the KCL MSc preliminary submission. Per D14,
this replaces the 10-page written report. The deck reports concrete progress
on hand-marking and the tech prototype, plus a sketch of the optimisation
work programmed in (per D12).

Working file: this Markdown outlines content slide by slide. Final export is
PDF (or PPTX) produced once the underlying results are in. Aim for 8 slides,
no more. Cite figures inline.

## Slide-by-slide outline

### Slide 1 — Title and framing

- Title: *Agentic AI for the EU Open Data Maturity Index: pipeline, evaluation,
  and an accuracy-cost surface.*
- Subtitle: MSc Advanced Computing — Preliminary Submission, May 2026.
- Author, programme, supervisor (TBC).
- One sentence positioning: "Automating a manual policy-evaluation workflow
  with verified multi-agent retrieval, evaluated on the EU Open Data Maturity
  Index."

### Slide 2 — Problem and project framing

- ODMI in one paragraph. 36 countries, 143 questions, four dimensions
  (Policy / Portal / Quality / Impact), 17 indicators, scored manually by
  Capgemini.
- Bottleneck: manual, slow, inconsistent across reviewers, limited budget
  for smaller countries.
- The project: an agent swarm that automates the assessment, with results
  reported both by accuracy and by computational cost.

### Slide 3 — Architecture in one diagram

- Figure 1 (SVG): the agent swarm pipeline.
  - Coordinator dispatches (question, country) pairs.
  - Researcher: Tavily search, Playwright fetch, returns answer + source URL +
    evidence quote + retrieval confidence.
  - Adversarial Verifier: independent search, prompted to disprove, returns
    pass/fail + answer confidence.
  - Output: Yes / No / Other plus dual confidences and a verifiable source.
- Stack: LangGraph, Claude via CLIProxyAPI, Tavily, Playwright, SQLite, DeepL
  for low-resource languages.

### Slide 4 — Methodology: the rubric as analytical lens

- Three a priori dimensions: Evidence Accessibility, Answer Determinism,
  Source Complexity. Each scored 0-3. Composite 0-9 maps to four tiers.
- Important framing: the rubric is not a runtime classifier; it stratifies
  swarm results. Hand-marked by the researcher, locked to git before any
  related swarm run.
- This sidesteps the "the classifier didn't predict" failure mode while
  preserving the analytical power of the dimensions.

### Slide 5 — Progress: hand-marking pilot

- N questions hand-marked for France across the four rubric tiers as of
  YYYY-MM-DD.
- Mini-table: tier distribution, dimension distribution, mean composite
  score.
- Example hand-marks (1-2 rows) with the justification text shown.
- Note on the lock rule: each mark is committed to git before any swarm
  run; commit SHAs visible in the audit trail.

### Slide 6 — Progress: tech prototype, first end-to-end result

The Researcher is built and running. First real walkthrough on
**P1 / France**, the question "is there a national open data policy
that includes legislation transposing the Open Data Directive?".

**Pipeline executed in four steps:**

1. Query generation: a small Claude call produced three queries (one
   English, one French, one with a `site:data.gouv.fr` filter).
   438 input + 69 output tokens, 2.6 seconds.
2. Tavily search across the three queries: 15 unique results
   covering data.gouv.fr, the European Commission digital-strategy
   portal, CNIL, and Wikipedia.
3. Main Claude call with the snippets pasted in. Returned a
   structured answer matching the Pydantic contract on the first
   attempt. 6,905 input + 1,170 output tokens, 20.5 seconds.
4. Post-call validation: cited URL returned HTTP 200; domain trust
   score 1.0 (data.gouv.fr is on the trusted list).

**Result:**

- Answer: `yes` (confidence 0.78).
- Cited source: a data.gouv.fr article on high-value datasets that
  references Directive 2019/1024.
- Cumulative cost receipts (per D12): 7,343 input tokens, 1,239
  output tokens, 23 seconds wall-clock, $0.041 estimated cost.
- Outcome matches the hand-mark locked in commit `96dad99`.

**One pattern already visible:** the Researcher's answer is correct
but the chosen source is not the strongest available. A
legifrance.gouv.fr citation or the EC digital-strategy page would be
stronger primary evidence than a data.gouv.fr article. Exactly the
kind of weakness the Adversarial Verifier should push back on,
making it useful data for the strategy comparison later.

### Slide 7 — The accuracy-cost surface (preview)

Existing agentic benchmarks (GAIA, AgentBench, WebArena) report
accuracy almost exclusively. For a system meant to replace a manual
annual workflow at scale, the operational question is also: what
does the answer cost?

The project measures and reports across three optimisation families:

**Family 1: prompt and retrieval.** baseline, prompt-compressed,
retrieval-tight, cache-hot, model-fallback. Tests where token
compression and retrieval trimming hurt accuracy.

**Family 2: Verifier prompt strategy.** disprove (default),
negation, steelman, blind. Tests which adversarial framing best
catches Researcher hallucinations.

**Family 3: model variants.** Haiku-4.5, Sonnet-4.6 (baseline),
Opus-4.6, plus a tiered combination (cheap Researcher, mid-tier
Verifier, premium Adjudicator). Anthropic's tiers span roughly 15x
in price; we expect this to be the single biggest cost lever.

**Headline figure:** accuracy on one axis, cumulative cost per
question on the other. One marker per experimental condition,
coloured by rubric tier. The shape of that surface is the main
RQ5 output.

**P1/France baseline data point** (added 2026-05-11):
- Condition: `model-sonnet` + `verifier-disprove` (not yet run; Researcher only).
- Cost: $0.041 per question on Sonnet-4.6.
- At Haiku-4.5 we would expect roughly $0.015; at Opus-4.6, roughly $0.20.

### Slide 8 — Schedule and next steps

- Phases (Gantt mini-figure):
  - Phase 0 (now): foundation, hand-mark pilot, tech prototype, optimisation
    measurement plumbed.
  - Phase A (mid-May to mid-June): France full run. Coordinator-Researcher-
    Verifier swarm built end-to-end. Hand-marks expanded to 30-50 questions.
  - Phase B (mid-June to mid-July): six-country 2×3 wealth × maturity matrix.
    Same questions re-marked per country. Full retrospective benchmark on
    2025.
  - Phase C (mid-July to early August): held-out test on 2024.
    Failure-mode taxonomy and accuracy-cost surface finalised. Dissertation
    written.
- Final submission: 2026-08-02.

## Production checklist

- [x] Researcher built and running end-to-end (P1/FR, 2026-05-11).
- [ ] At least 10 France hand-marks committed (currently 2: P1, PT4).
- [ ] At least 5 Researcher outputs in `phase2_researcher_runs` with
      real source URLs (currently 0; first row pending the move from
      `--dry-run` to a real save).
- [ ] Three failure-scenario probes run: I1 (subjective Impact),
      Q1 (quality), P10-a/b (multi-part).
- [ ] Verifier built and tested on at least one probe.
- [ ] Draft Figure 1 (architecture) as SVG under
      `docs/figures/architecture.svg`.
- [ ] Draft Figure 2 (mini Gantt) as SVG under
      `docs/figures/gantt_v1.svg`.
- [ ] Draft Figure 3 (placeholder accuracy-cost scatter) with axes,
      experimental-condition legend, and the P1/FR baseline marker.
- [ ] Export the deck to PDF or PPTX, add to the repo.

## Production notes

- Voice on slides: short headlines, bullets ≤ 8 words, full prose only in
  the speaker notes.
- One graphic per content slide, minimum.
- UK English throughout. The writing rules in `CLAUDE.md` apply to speaker
  notes and any prose on slides.
- Numbers must come from real runs. No mockups or placeholder data on
  results slides. If something is not measured yet, mark the slide TBD
  rather than fabricating.
