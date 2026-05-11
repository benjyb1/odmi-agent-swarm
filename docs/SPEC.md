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

Drafts of the final dissertation are written in `docs/REPORT_PRELIM.md`
(which evolves into `docs/REPORT_DISSERTATION.md`). Bibliography in
`docs/references.bib`. Final PDFs are typeset from these sources. Notion
is the place for narrative observations and supervision notes, not for
the report itself.

Rationale: keeping prose in the repo gives version control, citation
management, and reproducibility. An examiner who clones the repo can rebuild
the report from source.

### D12: Token-efficiency and latency as first-class research dimensions

**Date:** 2026-05-11.

Beyond answer accuracy, the project measures and reports computational
cost per question: input tokens, output tokens, and wall-clock latency.
Cost-per-correct-answer becomes a headline metric alongside accuracy.

Rationale: existing agentic-LLM benchmarks (GAIA, AgentBench, WebArena)
report accuracy almost exclusively. For a system intended to replace a
manual annual workflow at scale, the operational question is not only
"is the answer correct" but "what does the answer cost." Stratifying
both accuracy and cost by the rubric dimensions (D6) reveals which
question types are cheap-and-correct, expensive-but-correct,
cheap-but-wrong, and expensive-and-wrong. The cost surface is itself a
finding.

A new research question is added in METHODOLOGY.md:

> **RQ5.** What is the trade-off between answer quality and computational
> cost (tokens, latency) for ODMI questions of different rubric profiles?

Implications:
- Every LLM call records `input_tokens`, `output_tokens`,
  `wall_clock_ms`, and an estimated cost figure (or a flat marker since
  the project routes through CLIProxyAPI on a fixed subscription).
- The `phase2_runs` and (if used) `phase1_classifications` schemas need
  these columns added before the first real run. Logged as Q6 below.
- Optimisation strategies tried (prompt compression, retrieval scope
  tightening, caching, smaller model fallback) are themselves
  experimental conditions to report on.

### D13: 2025 ODMI cycle as primary ground truth, 2024 as held-out test set

**Date:** 2026-05-11. Resolves Q5.

The 2025 ODMI cycle is the primary evaluation ground truth. The repo
already contains the parsed 2025 questionnaire and France's 2025 response
sheet (which includes the 2024 answer as a baseline column). The 2024
cycle data is held back as an independent external-validity test set,
extracted from the original 2024 PDFs only after the pipeline is finalised
on 2025.

Rationale: 2025 data is parsed and ready; 2024 needs re-extraction. The
held-back design also gives a cleaner external-validity check, because
prompt and rubric tuning never touch the 2024 evidence.

### D14: 22 May deliverable is a results-focused slide deck, not a written report

**Date:** 2026-05-11.

The 22 May submission is repositioned as a short slide deck reporting
real progress (hand-mark pilot results plus tech-prototype outputs), not
the 10-page written report originally scoped. Per Benjy's read of the KCL
programme, the preliminary submission is non-examinable and acts as a
gateway; with a tight time budget, real results demonstrate capability
more efficiently than a planning document.

Consequences:
- `docs/REPORT_PRELIM.md` is no longer the 22 May deliverable. It is
  retained as scaffolding that will evolve into the final dissertation
  draft (which is examined).
- A new `docs/PROGRESS_SLIDES.md` holds the slide outline and content for
  the 22 May submission.
- This week's effort focuses on hand-marks (Benjy), a minimal tech
  prototype (Claude Code), and a small set of real results to put on
  slides.

---

## Current status

**Phase:** Phase A foundation. Results-and-slides sprint week (per D14).

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
- Minimal answering-agent prototype: one question end-to-end on France
  through CLIProxyAPI, written to SQLite with source URL and evidence
  quote. Pre-cursor to the full Coordinator-Researcher-Verifier swarm.
- 22 May slide deck (`docs/PROGRESS_SLIDES.md`).
- Schema additions for D12: `input_tokens`, `output_tokens`,
  `wall_clock_ms` on the run tables.
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
- **Q5:** Resolved by D13. 2025 cycle is primary; 2024 is held back as
  external-validity test set.
- **Q6:** Schema additions for the optimisation columns (per D12). Add
  `input_tokens`, `output_tokens`, `wall_clock_ms`, `estimated_cost_usd`
  (nullable) to `phase1_classifications` and `phase2_runs`. Migrate the
  empty DB before the first real run lands.
- **Q7:** One `phase2_runs` table with a `final` boolean, or split into
  `phase2_researcher_runs`, `phase2_verifier_runs`, and `phase2_final`?
  Leaning split-table for query simplicity. Decide before the schema
  migration. See AGENT_DESIGN.md section 5 for the writes that the
  Coordinator must support.
- **Q8:** Tavily `topic` parameter default for the Researcher's
  `web_search` tool. `general` to start; revisit if ODMI policy
  questions need a `news`-style retrieval.
- **Q9:** How to compute `estimated_cost_usd` under the CLIProxyAPI
  flat-rate subscription. Use published Anthropic rates as the
  arithmetic equivalent. Footnote in the dissertation.
- **Q10:** Trusted-domain list for the Researcher's source validator.
  Per-country JSON files under `data/trusted_domains/<country>.json`.
  Populate during Phase A.
- **Q11:** Substring check tolerance in the Verifier. Strict literal
  match is brittle; normalised match (collapse whitespace, lowercase,
  strip punctuation) is probably right. Decide before building the
  Verifier.

---

## Change log

| Date | Change |
|---|---|
| 2026-05-11 (pm) | D12 (optimisation as first-class dimension), D13 (2025 ground truth, 2024 held-out), D14 (22 May = slide deck not report). Q5 resolved. Q6 opened. RQ5 added to METHODOLOGY. |
| 2026-05-11 (am) | Project state reverse-engineered after five-week dormancy. Stale ODMI_Project_Knowledge.md / ODMI_Project_Setup.md deleted. CLAUDE.md, SPEC.md, METHODOLOGY.md, PROJECT_LOG.md rewritten. D8, D9, D10, D11 added. Option 3 (rubric as analytical lens) locked in. Hand-marks workspace created. First git commit on `main`. |
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
