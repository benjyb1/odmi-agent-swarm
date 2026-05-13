# Project Log

Session-by-session technical log. Decisions go in `SPEC.md`. Narrative for the
dissertation goes in Notion. This file is what was tried, what was learned,
and what comes next, written from the perspective of the work as it happens.

Entries newest first.

---

## 2026-05-13 — Session 7: ODMI ground truth supersedes hand-marking

The hand-mark workflow has been the dangling tail of D8 for weeks. This
session it got removed.

**The trigger.** Realising that `2025_odm_questionnaire_data.xlsx` ships
the `merged_responses` sheet: 5,148 (question, country) rows with the
country's actual answer, ODMI's accepted decision, awarded score, and
the rationale text. Every pair already has ground truth. The custom
three-dimension rubric and the hand-mark CSV workflow were both
constructed before this fact was used.

**The pivot.** Added a new SQLite `ground_truth` table and
`scripts/load_ground_truth.py`. Loaded all 5,148 rows for cycle 2025.
Replaced the rubric stratification axis with the ODMI dimension axis
(Policy / Portal / Quality / Impact) which is already in the data.

**Match logic.** `dashboard/lib/db.py:_MATCH_STATUS_SQL` does
case-insensitive trimmed comparison of `final_answer` against
`response`, with a `yes`-prefix special case so swarm `yes` matches
ODMI multi-tier responses (`yes, 3-5`, `yes, >9`, etc.).

**Dashboard.** Home KPI strip now shows Accuracy vs ODMI; country chart
splits bars into Matches / Differs from ODMI rather than Verifier
success / failure. Results Cards view shows ODMI's recorded answer
next to the swarm's with a match badge and an expandable ODMI
explanation. Hand-marks page removed from the sidebar.

**Numbers at the moment of the cut-over.** 11 finalised swarm pairs
across FR / DE / NL / RO, all matching ODMI 2025 (Policy dimension,
high-resource countries). Total spend around $1.02. The 100% will not
survive the move to harder dimensions, which is the point.

**Spec.** D22 added (ground truth supersedes hand-marks; D6/D8/D9/D10
no longer operational; data-leakage deny-list flagged). D23 added
(Streamlit Cloud auto-deploys on push to `main`, verify the URL after
every dashboard-touching push). RQ2 reframed in METHODOLOGY.md.
Sections 3 and 4 of METHODOLOGY retained as historical record with a
header note.

**Slide deck.** Regenerated against the new schema. KPI strip now
reads Pairs finalised / Accuracy vs ODMI / Ground-truth coverage /
Total LLM spend. Country chart legend reads Matches / Differs from
ODMI 2025. Caveat strip explains that ODMI assessments are one cycle
old, so a disagreement is not automatically a swarm error.

**Doc sweep.** CLAUDE.md, README.md, SPEC.md, METHODOLOGY.md, and the
read-only-mode copy on the dashboard all rewritten to match.

**What is next.** Verifier strategy comparison (D15/Q12), scale-out
to harder ODMI dimensions, add Hungary and Estonia. Then the deny-list
mitigation for data.europa.eu in `agents/tools/search.py` before the
first big saturated run.

---

## 2026-05-13 — Session 6: Coordinator follow-ups

Short session. Two patches on top of the day-5 coordinator.

**`--dry-run` and `--walkthrough` flags on `run_coordinator.py`.**
- `--dry-run` short-circuits the five DB-write helpers
  (`subtrio_status`, `phase2_researcher_runs`, `phase2_verifier_runs`,
  `phase2_adjudications`, `phase2_final`). `claude_usage_log` is
  deliberately not gated: the tokens are real even when the "run" is
  fake, and suppressing the usage log would let the rolling 5-hour
  budget under-count actual Anthropic spend.
- `--walkthrough` prints every Researcher / Verifier / Adjudicator
  stage event to stdout. Off by default so dashboard-spawned
  subprocesses don't flood their per-batch log file.
- Implementation: two module-level booleans (`_dry_run`,
  `_walkthrough`) set at `coordinate()` entry. The five DB helpers
  short-circuit when `_dry_run` is True. The two `on_step` lambdas
  passed to Researcher and Verifier now chain through a verbose
  printer.
- Smoke test (P1/FR, `--max-retries 0 --dry-run --walkthrough`):
  R1: yes (0.88) $0.021. V1: fail (0.72) $0.035 (substring check
  correctly caught a stale guides.data.gouv.fr quote). Adjudicator:
  researcher_correct (0.82). Terminal: `accepted_by_adjudicator`.
  Five gated tables: zero new rows. Six `claude_usage_log` rows
  captured with subtrio_id and context labels intact.

**`docs/KNOWN_GAPS.md` written.** Forward-looking note documenting the
three deferred failure modes from the day-5 contract audit:
resume from interruption (D22-D25), CAPTCHA / 403 detection, human-queue
CSV writer. Each entry covers trigger condition, observable symptom,
current workaround, rough cost-to-build. Indexed from SPEC.md's
"Where to look for what" table. The idea is that when something
unexpected happens during a real run, the symptom-to-triage path is
short.

### Open at end of session

Same as session 5. The two patches don't change the "next session"
priority list:
1. Drive a real multi-question batch through the dashboard.
2. Migrate hand-marks from the Word doc to CSV + git commit (unlocks D9).
3. Carry the three KNOWN_GAPS items until a real trigger appears.

---

## 2026-05-12 — Session 5: Dashboard end-to-end + coordinator built

### Morning: failure-scenario probes and Verifier build

Ran the three probe questions through the Researcher to populate the DB
with realistic rows before building the Verifier:

| Q | Country | Answer | Conf | Notable |
|---|---|---|---|---|
| P1 | FR | yes | 0.75 | Researcher cited a data.gouv.fr blog post, not the actual law |
| I1 | FR | yes | 0.65 | Quote literally says *"Il n'existe pas de définition stricte"* — the model still answered yes |
| Q1 | FR | other | 0.20 | Correctly bailed with low confidence |
| P10-a | FR | no | 0.45 | Same Etalab URL as P10-b — citation drift |
| P10-b | FR | no | 0.35 | Same Etalab URL as P10-a — citation drift |

Built the Verifier (`agents/verifier.py` + `agents/prompts/verifier.py`)
with four strategy prompts: disprove, negation, steelman, blind. Smoke
tested with the default `disprove` strategy:

- **P1/FR**: Verifier failed, found the actual transposition ordonnance
  (`Ordonnance 2021-442` on Légifrance) and suggested it as the correct
  query. System worked as designed — Researcher's weak source was
  rejected, real legal text surfaced.
- **I1/FR**: Verifier failed and explicitly cited that the quoted text
  contradicts the yes answer. Pointed to the Code des relations entre
  le public et l'administration as the right place to look for a formal
  definition.

This established Phase 2 (Verifier) as functionally working before
moving to the dashboard.

### Afternoon: dashboard design and build

**Brainstorming and spec.** Worked through dashboard scope via the
visual companion. Settled on Streamlit + subprocess pool over
FastAPI+React (robustness vs build chain, the spec calls this a YAGNI
win). User added three requirements mid-design: per-model logging and
analytics, multi-country / multi-question selection through a browsable
Questions page, and Claude credit-fallback handling. Spec written to
`docs/superpowers/specs/2026-05-12-dashboard-design.md` and passed two
rounds of spec review (one round of fixes for: Adjudicator file did
not yet exist, RateLimitedShutdown contract undefined, model_defaults
included a query_gen role with no surface, pre-flight cost arithmetic
underspecified across model conditions, three minor enum mismatches).

**Phase 1 — agent infrastructure built.**
- `agents/errors.py`: `RateLimitedShutdown` exception and
  `EXIT_CODE_RATE_LIMITED = 42` constant. One source of truth for the
  rate-limit contract used by `llm.py`, the Coordinator, and the
  dispatcher.
- `agents/adjudicator.py` + `agents/prompts/adjudicator.py`: tiebreaker
  for retries-exhausted cases. Single LLM call, no web search. Auto-
  promotes to `escalate_human` if confidence drops below 0.6 (per
  AGENT_DESIGN §5.11.5).
- `scripts/run_coordinator.py`: per-pair state machine. Researcher →
  Verifier → (Adjudicator on retry exhaustion). Writes
  `subtrio_status` at every stage transition. **Plain Python rather
  than LangGraph** (deviation from AGENT_DESIGN §5 noted in the file
  header — the retry loop is linear; the graph runtime adds debugging
  overhead with no behavioural benefit at this scale).
- `scripts/dispatch_subtrios.py`: parallel pool. Pre-flight cost check
  with a three-level fallback (model-tuple → triple → pair → cold-start
  default of $0.10), live budget enforcement at the 5% low-water mark,
  and clean shutdown on exit code 42 from any child.
- `scripts/cleanup_subtrios.py`: orphan reaper. Finds
  `subtrio_status` rows stale > 10 minutes in active stages and marks
  them `orphaned`.
- `scripts/migrate_dashboard_tables.py`: idempotent ALTER for the
  three new tables (`subtrio_status`, `claude_usage_log`,
  `model_defaults`) so the existing DB didn't have to be wiped.
- `agents/tools/llm.py` instrumented: every LLM call now writes one
  `claude_usage_log` row, and `anthropic.RateLimitError` is caught and
  re-raised as `RateLimitedShutdown`. Added `usage_context` and
  `subtrio_id` kwargs to `call_for_structured` and threaded them
  through Researcher and Verifier so every usage log row carries the
  originating subtrio.

**Phase 2 — Streamlit dashboard built.** Nine pages plus the pinned
Claude-session widget in the sidebar.

- Home: KPI tiles + recent runs feed + hand-mark lock status + human
  queue snapshot. Live refresh every 2 seconds.
- Run Console: launcher (multi-country chips, multi-question chips
  from the Questions page, per-agent model dropdowns, strategy,
  parallel limit) with the pre-flight credit banner. Below: live
  subtrio cards showing the three-stage pipeline (Researcher → Verifier
  → Final) with stage-specific colour-coding.
- Results: three tabs (Researcher / Verifier / Final) with column
  filters and a JSON drawer for row inspection.
- Strategy Lab: pick a Researcher row, run all four Verifier
  strategies, see verdicts side by side (the D15 comparison).
- Hand-marks: read-only mirror of the CSV workspace. Reminds the user
  that editing happens in CSV + git.
- Questions: full filterable table of all 143 questions with
  hand-mark status badge and a "Send N → Run Console" hand-off.
- Prompts: versioned prompt browser with full prompt text.
- Models: defaults editor + per-model analytics + the D18 R×V
  pass-rate cross-product heatmap.
- Costs: rolling-window KPI tiles, daily cost chart, dimension/country
  breakdown, recent usage log.

### Evening: testing

**End-to-end coordinator smoke (P1/FR, max-retries=0):**
Researcher answered yes(0.72) → Verifier rejected → Adjudicator picked
researcher_correct (0.72) → `phase2_final` row written with
`terminal_status=accepted_by_adjudicator`. All six LLM calls wrote
`claude_usage_log` rows carrying the subtrio_id and a `context` label
identifying which agent made the call.

**Front-end tests (Playwright headless on Streamlit at :8520):**
9/9 pages clean. Found two real bugs during the run: pandas 3.0
rejected writing strings into a float column in the Models heatmap
(fixed by building it as `dtype=object` from the start); and
`st.data_editor` checkboxes can't be driven from Playwright in headless
mode (replaced with `st.multiselect` which is both more reliable for
the user and trivially testable).

**Streamlit AppTest cases:** 4/4 (Questions → Run Console hand-off via
session_state, Models / Costs / Strategy Lab page loads).

**Release smoke test:** opened the Run Console via AppTest, clicked
the Release button. A real `dispatch_subtrios.py` subprocess was
spawned (PID captured), the `subtrio_status` row was inserted, and
the log file was written under `dashboard/logs/`. SIGTERM cleanup
confirmed the subprocess responds.

### Contract audit

User flagged 32 questions about the contracts between
`run_coordinator.py` and the other agents. Audited the actual code
against each item. Most were correctly aligned; one real gap found and
fixed (subtrio_id wasn't being threaded through from Researcher /
Verifier to the LLM wrapper, so usage rows from those agents had NULL
subtrio_id). Five non-blocking deferrals identified:

- D22-D25 (resume semantics): no auto-resume from interrupted state.
  A rate-limited subtrio sits with `stage=interrupted_rate_limit` until
  manually re-released. Acceptable v1 because pre-flight is conservative.
- A7 (CAPTCHA detection): the Researcher does not detect CAPTCHA / 403
  pages and so the coordinator can't route them to a human queue.
- B10 (human queue CSV): `terminal_status=escalated_*` writes to
  `phase2_final` but no CSV at `data/human_queue/<batch_id>.csv` is
  produced.
- E26 / E27 (`run_coordinator.py` `--dry-run` / `--walkthrough`):
  runner is silent-mode only. The older `run_researcher.py` has
  `--walkthrough` for in-line stage inspection.
- Question-bank → SQLite import is empty. The Questions page falls
  back to the JSON file.

### Open at end of session

- D19 (Streamlit + subprocess pool), D20 (rolling-window credit
  enforcement), D21 (three new schema tables) need formal entries in
  `docs/SPEC.md` change log.
- User has not yet driven the live dashboard at scale (only single-pair
  smoke tests have run through it). A multi-pair batch through the UI
  is the next confidence-building step.
- Hand-marks are still in the Word document, not the CSV format. D9
  cannot be enforced until the migration happens. Until then, swarm
  rows are valid as exploratory output but not as evidence.

### Next session

1. Drive a real multi-question batch through the dashboard (suggest:
   Q1-Q5 for France, sonnet on all three roles, parallel=3) and watch
   the live cards. Confirm KPIs update in real time. Confirm Costs
   page reflects the new spend.
2. Migrate hand-marks from `data/ODMI_2025_Questions.docx` to
   `data/hand_marks/france_handmarks.csv` and commit (locks the lock).
3. Decide whether to tackle the five deferred items now (resume,
   CAPTCHA, human-queue CSV, --dry-run, questions DB import) or carry
   them as known gaps until a real workflow hits one.

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
