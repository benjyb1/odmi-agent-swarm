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

### Slide 6 — Progress: tech prototype, early results

- The minimal answering agent: one (question, country) end-to-end through
  search and structured output, writing to SQLite.
- Example output for question P1 / France: actual answer string, source URL,
  evidence quote, retrieval and answer confidences.
- Numbers from the pilot run: N questions answered, accuracy against the
  2025 ground truth, mean input tokens, mean output tokens, mean wall-clock
  ms per question.

### Slide 7 — The accuracy-cost surface (preview)

- Why this matters: existing agentic benchmarks (GAIA, AgentBench,
  WebArena) report accuracy only. Operational deployment cares about
  cost-per-correct-answer.
- The optimisation variants we will test (per D12): baseline,
  prompt-compressed, retrieval-tight, cache-hot, model-fallback.
- A placeholder scatter plot: accuracy on the y-axis, cost (input + output
  tokens) on the x-axis, with each rubric tier as a different marker. The
  shape of this surface is one of the main outputs.

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

- [ ] Have at least 10 France hand-marks committed (the lock chain visible
      in `git log`).
- [ ] Have at least 5 prototype outputs in SQLite with real source URLs.
- [ ] Computed real numbers: pilot accuracy on the 5 answers vs the 2025
      ground truth, mean tokens per call, mean wall-clock latency.
- [ ] Drawn Figure 1 (architecture) as SVG and committed under
      `docs/figures/architecture.svg`.
- [ ] Drawn Figure 2 (mini Gantt) as SVG and committed under
      `docs/figures/gantt_v1.svg`.
- [ ] Drawn Figure 3 (placeholder accuracy-cost scatter) — does not need
      real data yet, but the axes and the variant legend should be present.
- [ ] Exported the deck to PDF or PPTX and added to the repo.

## Production notes

- Voice on slides: short headlines, bullets ≤ 8 words, full prose only in
  the speaker notes.
- One graphic per content slide, minimum.
- UK English throughout. The writing rules in `CLAUDE.md` apply to speaker
  notes and any prose on slides.
- Numbers must come from real runs. No mockups or placeholder data on
  results slides. If something is not measured yet, mark the slide TBD
  rather than fabricating.
