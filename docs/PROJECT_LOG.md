# Project Log

Session-by-session technical log. Decisions go in `SPEC.md`. Narrative for the
dissertation goes in Notion. This file is what was tried, what was learned,
and what comes next, written from the perspective of the work as it happens.

Entries newest first.

---

## 2026-05-11 — Session 3: Reset and re-foundation

**What happened.** Five-week dormancy ended with an audit. The previous
`ODMI_Project_Knowledge.md` and `ODMI_Project_Setup.md` had drifted out of
sync with the repo (still claiming Supabase, Opus, and a built Phase 1
classifier). Both files removed by Benjy before this session.

**What got reverse-engineered.** The repo has the original scaffolding from
late March. SQLite schema present, zero rows. `agents/classifier.py` with
Pydantic models but no LLM call. `scripts/run_phase1.py` has the API call
plumbing but was never invoked. Two hand-marked France questions sit in the
Word document `data/ODMI_2025_Questions.docx` (P1 and PT4, both 9/9). No
LangGraph code anywhere.

**Decision made.** Option 3 confirmed (see D8 in SPEC.md). The rubric becomes
an analytical lens for stratifying swarm results, not a runtime classifier.
This removes the validation burden that was the main defensibility risk in
the original two-phase design.

**What was set up.**
- `CLAUDE.md` rewritten with audit-trail rules and the hand-mark lock policy.
- `docs/SPEC.md` rewritten. D8 (analytical-lens rubric), D9 (lock hand-marks
  before swarm runs), D10 (sample size and stratification), D11 (writing
  pipeline in the repo) added.
- `docs/METHODOLOGY.md` written. The rubric is now defined precisely with
  dimension-by-dimension scoring guidance. The hand-marking protocol is
  written so another evaluator could reproduce it.
- `data/hand_marks/` created with `PROTOCOL.md` and an empty CSV template
  for France.
- `docs/REPORT_PRELIM.md` scaffolded against the brief structure
  (Introduction, Background, Schedule).
- `docs/references.bib` skeleton.
- First git commit on `main`.

**Open at end of session.**
- Q5 (cycle for evaluation: 2024 vs 2025 vs both) still unresolved.
- Supervisor identity and meeting cadence still unset.
- 10-question pilot hand-mark set not yet selected.
- Notion master page still says Supabase + Opus. Needs sync.

**Next session.**
- Select the 10-question pilot sample for France hand-marking.
- Start the Introduction section of the preliminary report.
- Begin literature review for the Background section. Suggested seeds:
  ODMI methodology papers, agentic LLM evaluation benchmarks
  (GAIA, ToolBench, AgentBench), automated policy analysis (CivicBench,
  AI4Gov), hallucination mitigation in retrieval-augmented agents.

---

## 2026-04-01 — Session 2: Living spec set up, repo relocated

(Inferred from previous SPEC.md, now superseded.)

- Created the first version of SPEC.md.
- Confirmed CLIProxyAPI over the Anthropic API (D1).
- Confirmed SQLite over Supabase (D2).
- Moved repo from `~/Projects/odmi-agent-swarm` to `~/Desktop/Msc Project`.
- Identified that the LLM call in `run_phase1.py` is unwired and that
  Questions.xlsx had not yet been parsed into the workspace.

---

## 2026-03-27 — Session 1: Initial scaffolding

(Inferred from the original PROJECT_LOG.md, now superseded.)

- Created the repo structure: `agents/`, `data/`, `evaluation/`, `scripts/`,
  `docs/`, `tests/`.
- Wrote `pyproject.toml` with the Phase 1 dependency set.
- Wrote `scripts/setup_supabase.sql` (never applied, since dropped in D2).
- Wrote `agents/classifier.py` with the v1 rubric prompt and Pydantic models.
- Wrote `scripts/run_phase1.py` with dry-run support.
- Wrote `tests/test_classifier.py` unit tests for the Pydantic models.
- Identified that the Questions.xlsx needed to be obtained from
  data.europa.eu.
- Decided on dual tracking: markdown in repo (technical) plus Notion
  (research narrative).
