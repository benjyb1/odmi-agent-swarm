# ODMI Agent Swarm — Living Spec

Last updated: 2026-05-11

Single source of truth for project state. Updated every session. All numbered
decisions go in here so they can be referenced as "per D7" elsewhere in the
repo, in the dissertation, and in supervision discussions.

---

## Project summary

MSc Advanced Computing dissertation (King's College London, 2026). An LLM-powered
agent swarm that automatically answers EU Open Data Maturity Index (ODMI)
questions across 36 countries in 20+ languages. Validated against 2024 ground
truth and deployed against the 2026 cycle.

**Supervisor:** TBC (see Notion supervision log).
**Repo:** `/Users/benjyb/Desktop/Msc Project`.
**Notion master page:** `331acc75-be02-8163-9169-e327fed97055`.

---

## Deadlines

| Deliverable | Due | Format |
|---|---|---|
| Preliminary project report | 2026-05-22 (self-imposed cut-off 2026-05-16) | 10 pages A4, 11pt min, single spacing, 1.5cm margins. Intro / Background / Schedule. |
| Final dissertation | 2026-08-02 | Full thesis. |

Body page count for the prelim excludes the cover and references. Citations and
the Gantt chart sit outside the page limit.

---

## Key decisions

Decisions are numbered for cross-reference. New decisions go at the bottom.
Decisions are not deleted when superseded. They get a "Superseded by Dx"
annotation so the audit trail stays intact.

### D1: LLM access via CLIProxyAPI, not the Anthropic API

All LLM calls are routed through **CLIProxyAPI** running locally on
`localhost:8317`. This piggybacks on Benjy's Claude Max subscription.

- No separate Anthropic API key or billing.
- The model used is whatever Claude Code exposes (currently Claude Sonnet 4 at
  the time of writing; previously Claude Opus 4.6 had been targeted).
- Trade-off: coupled to the Max plan and to CLIProxyAPI's interface. If the
  subscription changes or the proxy breaks, we swap in a direct API client.
  Acceptable for a dissertation.

### D2: SQLite as the primary data store, not Supabase

`data/odmi.db` is the single evaluation dataset. The original Supabase schema
(`scripts/setup_supabase.sql`) was never applied and may be dropped.

Rationale: SQLite keeps everything local and reproducible. No cloud dependency,
no credentials, a single `.db` file can be handed to an examiner alongside the
code. Reproducibility outweighs the convenience of a hosted store at this scale.

### D3: LangGraph for the Phase 2 agent swarm

Explicit state machines map cleanly to the Coordinator → Researcher → Verifier
pattern. Conditional edges express accept/reject/retry logic that plain
LangChain chains cannot handle neatly.

### D4: France-first baseline

Phase A runs against France only. France scored 100% on the 2024 ODMI, speaks
a high-resource language, and has a mature open data portal (data.gouv.fr).
If the pipeline fails on France, the problem is in the pipeline, not in the
country's data infrastructure.

### D5: Prompt versioning in the database

Every classification and every agent response links to the exact prompt version
that produced it via `prompt_versions.id`. Without this, score changes cannot
be attributed to prompt changes versus model behaviour.

### D6: Three-dimension answerability rubric (definition)

The rubric measures a question against:
- **Evidence Accessibility** (0-3): how findable is the evidence?
- **Answer Determinism** (0-3): is the answer objective or subjective?
- **Source Complexity** (0-3): how many sources need cross-referencing?

Composite 0-9 maps to four tiers: Highly Likely (7-9), Likely (5-6), Unlikely
(3-4), Very Unlikely (0-2). Definitions and scoring guidance are in
`docs/METHODOLOGY.md`.

### D7: Phased country rollout

- **Phase A:** France only (controlled baseline).
- **Phase B:** Six countries across a 2×3 wealth × maturity matrix: France,
  Germany, Netherlands, Romania, Hungary, Estonia.
- **Phase C:** All 36 EU countries (stretch goal).

### D8: Rubric is an analytical lens, not a runtime classifier

**Date:** 2026-05-11.

The rubric (D6) is used to stratify swarm results, not to predict them. There
is no Phase 1 classifier as a pipeline stage. The hand-marked rubric scores
are an evaluation framework, not a piece of automation.

Rationale: an LLM classifier whose role is to predict answerability would need
to be validated against swarm outcomes. Validation requires the swarm to exist
first. If the correlation turned out to be weak, the classifier would look like
wasted scaffolding. Option 3 from the May 2026 review removes this risk. The
methodological contribution shifts from "we built a two-phase pipeline" to "we
built an agentic pipeline and developed a structured framework for analysing
where it fails."

Consequences:
- `agents/classifier.py` and `scripts/run_phase1.py` are kept in the repo but
  not on the critical path. The classifier may later be run post hoc to test
  whether the rubric can be automated. That experiment, if done, is a
  secondary finding.
- Hand-marks replace LLM-produced classifications as the authoritative rubric
  scores.

Supersedes the previous treatment of the classifier as Phase 1.

### D9: Hand-marks must be locked before any swarm run touches the same question

**Date:** 2026-05-11.

To prevent evaluator bias, every hand-mark must be committed to git before any
automated run on the same (question, country) pair. The commit SHA is recorded
in the `hand_marks.locked_by_commit` column in SQLite.

If hand-marks for a target pair are uncommitted at the moment a swarm run
starts, the run does not proceed.

Rationale: the same researcher hand-marks questions and analyses swarm
behaviour. Without a temporal lock, rubric scores could drift to align with
swarm outcomes. The git history is the evidence that scores were set first.

### D10: Hand-mark sample size and stratification

**Date:** 2026-05-11.

Initial sample: 30-50 questions, hand-marked for France first (Phase A).
Selection is stratified across:
- The four ODMI dimensions (Policy, Portal, Quality, Impact) in roughly the
  proportions they appear in the question bank.
- The expected difficulty range. Aim to populate all four tiers of the rubric.

For Phase B, the same questions are re-marked for the other five countries,
giving roughly 180-300 hand-marks in total. Country-dependent dimensions
(Evidence Accessibility most of all) shift between countries; Answer
Determinism does not.

Open: final sample size and per-tier counts to be set after a first pilot
of 10 hand-marks. Logged here once locked.

### D11: Living writing pipeline

**Date:** 2026-05-11.

Drafts of the preliminary report and the dissertation are written in
`docs/REPORT_PRELIM.md` and (later) `docs/REPORT_DISSERTATION.md`. Bibliography
in `docs/references.bib`. Final PDFs are typeset from these sources. Notion is
the place for narrative observations and supervision notes, not for the
report itself.

Rationale: keeping prose in the repo gives version control, citation
management, and reproducibility. An examiner who clones the repo can rebuild
the report from source.

---

## Current status

**Phase:** Phase A setup. Preliminary report writing week.

### Built (verified)

- Repo structure with `agents/`, `data/`, `docs/`, `scripts/`, `tests/`,
  `evaluation/`.
- `pyproject.toml`, `.env.example`, `.gitignore`, `uv.lock`. Dependency tree
  installed.
- SQLite schema at `data/odmi.db` (five tables: `prompt_versions`, `questions`,
  `phase1_classifications`, `phase2_runs`, `language_confidence`). All empty.
- `scripts/parse_questions.py` parses the official 2025 ODMI questionnaire
  spreadsheet into structured JSON. Output: 143 questions across 4 dimensions
  and 17 indicators, at `data/questions/odmi_2025_questions.json`.
- `agents/classifier.py` with Pydantic models and a v1 rubric prompt template.
  No LLM call wired in this file.
- `scripts/run_phase1.py` has a working LLM call but has never been executed.
  Under D8 this script is off the critical path.
- `tests/test_classifier.py` covers Pydantic model logic.
- Two hand-marked France questions (P1 and PT4), both 9/9 Highly Likely.
  Stored as a Word document at `data/ODMI_2025_Questions.docx`. To be migrated
  to the CSV format defined in `data/hand_marks/PROTOCOL.md` and re-locked.

### Not yet built

- LangGraph agent swarm (Coordinator, Researcher, Verifier). No code exists.
- Hand-mark migration from the Word document to the CSV workspace.
- Hand-mark schema in SQLite (table to be added).
- Pilot batch of 10 hand-marks for France across the difficulty range.
- Preliminary report (drafting in progress as of 2026-05-11).
- `evaluation/` analysis scripts.
- Notion master page sync with the new state (still says Supabase + Opus).

### Open questions

- **Q1:** Final per-tier sample size for hand-marking. Resolve after the
  10-question pilot.
- **Q2:** Should we keep the `phase1_classifications` table for the optional
  post-hoc classifier experiment, or drop it and add only `hand_marks`?
  Leaning towards keeping both.
- **Q3:** Supervisor identity and meeting cadence. Log in Notion once set.
- **Q4:** Language confidence table — how to populate it for Phase B without
  blowing time on a 24-language benchmark we may not need.
- **Q5:** Do we evaluate against the 2024 cycle, the 2025 cycle, or both?
  The repo has the 2025 questionnaire and France's 2025 response sheet. The
  2024 reports exist in PDF and would need re-extracting. Decide before
  finalising evaluation methodology in `docs/METHODOLOGY.md`.

---

## Change log

| Date | Change |
|---|---|
| 2026-05-11 | Project state reverse-engineered after five-week dormancy. Stale ODMI_Project_Knowledge.md / ODMI_Project_Setup.md deleted. CLAUDE.md, SPEC.md, METHODOLOGY.md, PROJECT_LOG.md rewritten. D8, D9, D10, D11 added. Option 3 (rubric as analytical lens) locked in. Hand-marks workspace created. First git commit on `main`. |
| 2026-04-01 | SPEC.md first created (now superseded). Confirmed CLIProxyAPI (D1) and SQLite (D2). Project moved from `~/Projects` to `~/Desktop/Msc Project`. |
| 2026-03-27 | Session 1: repo scaffolding, classifier v1, Supabase schema (since dropped). |

---

## Where to look for what

| Question | Where |
|---|---|
| What is the rubric? | `docs/METHODOLOGY.md`. |
| What is the hand-marking protocol? | `data/hand_marks/PROTOCOL.md`. |
| Why did we make decision X? | This file (`docs/SPEC.md`), search for "Dx". |
| What did I do last session? | `docs/PROJECT_LOG.md`. |
| What did the supervisor say? | Notion supervision log. |
| Where are the parsed questions? | `data/questions/odmi_2025_questions.json`. |
| Where are the hand-marks? | `data/hand_marks/france_handmarks.csv`. |
| Where is the prelim draft? | `docs/REPORT_PRELIM.md`. |
| Where are citations? | `docs/references.bib`. |
