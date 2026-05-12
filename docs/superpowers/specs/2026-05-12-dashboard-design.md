# ODMI Swarm Dashboard — Design

Date: 2026-05-12
Status: Approved for implementation
Author: Benjy Bream (with Claude Code)

## 1. Purpose

A Streamlit-based control room for the ODMI Agent Swarm. The dashboard is
the primary interface for releasing subtrios (per-pair Coordinator runs),
watching them progress, browsing results, comparing Verifier strategies,
managing hand-marks, and tracking Claude token usage against the rolling
5-hour subscription window.

The dashboard does not replace the CLI scripts. It wraps them. Every
button in the UI calls into the same atomic Python entry points
(`scripts/run_researcher.py`, `scripts/run_verifier.py`, the upcoming
`scripts/run_coordinator.py`) so the CLI and the UI stay in lock-step.

## 2. Vocabulary

- **Subtrio** — one (question, country) pipeline run. Comprises a
  Researcher, a Verifier, and (when retries exhaust) an Adjudicator. The
  Coordinator (`run_coordinator.py`, per AGENT_DESIGN section 5) is the
  state machine that orchestrates a single subtrio.
- **Batch** — a group of subtrios released together from the Run Console.
  Identified by a `batch_id` UUID.

## 3. Tech stack

- **Streamlit** for the UI. One file per page under `dashboard/pages/`.
  Live widgets use `st.fragment(run_every=1)` to poll SQLite.
- **subprocess.Popen pool** in `scripts/dispatch_subtrios.py` to spawn N
  parallel `run_coordinator.py` processes.
- **SQLite** (existing `data/odmi.db`) as the only state store. WAL mode
  is already enabled.
- No new runtime dependencies beyond `streamlit` itself.

## 4. Architecture

```
Streamlit app (dashboard/Home.py + dashboard/pages/*.py)
        │
        │ "Release N subtrios" button
        ▼
scripts/dispatch_subtrios.py
        │  - holds a semaphore equal to parallel_limit
        │  - re-checks claude_usage_log before each new spawn
        │  - on RateLimitedShutdown: kills children, marks
        │    subtrio_status rows as interrupted_rate_limit
        ▼  subprocess.Popen per subtrio
scripts/run_coordinator.py  Q3 RO --researcher-model sonnet ...
        │  - LangGraph StateGraph (AGENT_DESIGN §5)
        │  - writes one row per stage transition to subtrio_status
        │  - writes phase2_researcher_runs / phase2_verifier_runs /
        │    phase2_adjudications / phase2_final exactly as today
        ▼
agents.researcher, agents.verifier, agents.adjudicator (existing files)
        │  - every LLM call writes claude_usage_log
        ▼
data/odmi.db
```

Polling reads from `subtrio_status` (live state) and the phase2 tables
(historical state). The dispatcher and Streamlit never share memory; the
DB is the only communication channel.

## 5. Database additions

```sql
-- 5.1 Live status of every subtrio currently or recently active.
CREATE TABLE subtrio_status (
    subtrio_id          TEXT PRIMARY KEY,        -- UUID
    batch_id            TEXT NOT NULL,           -- groups a release together
    question_id         TEXT NOT NULL,
    country_code        TEXT NOT NULL,
    stage               TEXT,                    -- queued / researching /
                                                 --   verifying / adjudicating /
                                                 --   done / failed /
                                                 --   interrupted_rate_limit
    substage            TEXT,                    -- query_gen / search /
                                                 --   main_call / validation
    retry_count         INTEGER DEFAULT 0,
    started_at          TEXT,
    updated_at          TEXT,
    ended_at            TEXT,
    final_verdict       TEXT,                    -- pass / fail / human_queue / error
    cumulative_cost_usd REAL,
    last_message        TEXT,                    -- short line for the live widget
    process_pid         INTEGER,
    researcher_model    TEXT,
    verifier_model      TEXT,
    adjudicator_model   TEXT,
    verifier_strategy   TEXT
);
CREATE INDEX idx_subtrio_status_batch ON subtrio_status(batch_id);
CREATE INDEX idx_subtrio_status_stage ON subtrio_status(stage);

-- 5.2 Claude usage log. One row per LLM call. Sidebar reads this.
CREATE TABLE claude_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,           -- when the call returned
    model               TEXT NOT NULL,
    input_tokens        INTEGER NOT NULL,
    output_tokens       INTEGER NOT NULL,
    estimated_cost_usd  REAL,
    rate_limited        INTEGER DEFAULT 0,       -- 1 if this call hit the limit
    context             TEXT,                    -- e.g. "researcher:Q3:RO"
    subtrio_id          TEXT                     -- nullable
);
CREATE INDEX idx_claude_usage_ts ON claude_usage_log(timestamp);

-- 5.3 Default model assignment per agent role. Edited from the Models page.
CREATE TABLE model_defaults (
    agent_role          TEXT PRIMARY KEY,        -- 'researcher' / 'verifier' /
                                                 --   'adjudicator' / 'query_gen'
    model               TEXT NOT NULL,           -- e.g. 'claude-sonnet-4-6'
    updated_at          TEXT NOT NULL,
    updated_by          TEXT
);
```

`agents/tools/llm.py` writes one `claude_usage_log` row per call as part of
its existing instrumentation path. `agents/tools/db.py` gains a
`record_subtrio_status_transition()` helper that the Coordinator calls at
each stage boundary.

## 6. New Python entry points

### 6.1 `scripts/dispatch_subtrios.py`

```
dispatch_subtrios.py
  --questions Q2 Q3 Q4 Q5
  --countries FR RO DE
  --researcher-model claude-sonnet-4-6
  --verifier-model claude-sonnet-4-6
  --verifier-strategy verifier-disprove
  --parallel 4
  --batch-id 0a3f-c2b1                # auto-generated if absent
```

Responsibilities:
1. Pre-flight: estimate cost from the last 50 subtrio averages × N pairs ×
   a retry uplift factor (default 1.2). Compare against the rolling
   5-hour budget. Refuse to start if projected cost exceeds budget. Warn
   if projected cost > 85% of budget.
2. Insert one `subtrio_status` row per pair with `stage="queued"`.
3. Start a semaphore at `parallel_limit`. For each pair, acquire the
   semaphore and spawn `run_coordinator.py` with the right args. Release
   when the subprocess exits.
4. On every subprocess exit, re-check the rolling budget. If below the
   low-water mark (default 5%), stop dispatching and let in-flight
   subtrios drain.
5. On any subtrio raising `RateLimitedShutdown` (propagated via exit code
   42), terminate all running children with SIGTERM, mark their
   `subtrio_status` rows `interrupted_rate_limit`, and exit cleanly with
   a summary written to stderr.

### 6.2 `scripts/run_coordinator.py`

The LangGraph StateGraph implementation from AGENT_DESIGN section 5.
Owns the Researcher → Verifier (→ Adjudicator) loop for one pair. Writes
to `subtrio_status` at each transition. Detailed spec already exists; this
document does not re-specify the Coordinator.

### 6.3 `scripts/cleanup_subtrios.py`

Standalone maintenance script. Finds `subtrio_status` rows where
`stage NOT IN ('done', 'failed', 'interrupted_rate_limit')` and
`updated_at` is older than 10 minutes. Marks them `orphaned`. Reaps PIDs
if they are still alive. Used after an unclean shutdown of the dashboard.

## 7. Pages

The Streamlit app is a multi-page app rooted at `dashboard/Home.py` with
`dashboard/pages/*.py` for the rest. Sidebar shows nine pages plus the
Claude session widget pinned at the bottom.

### 7.1 Home

At-a-glance widgets:
- KPI tiles: active subtrios, total runs (Researcher / Verifier), Verifier
  pass rate, today's spend.
- Recent runs feed (last 10 subtrios across all countries).
- Hand-marks lock status per country.
- Human queue snapshot (CAPTCHA / adjudicator escalations).

Refreshes every 2 seconds via `st.fragment(run_every=2)`.

### 7.2 Run Console

The launcher and the live subtrio cards.

Launcher:
- Multi-select **countries** (chips).
- Multi-select **questions** (chips). Empty by default. The "+ Add from
  Questions" link routes to the Questions page; the table there has a
  "Send N → Run Console" button that stashes the selection in
  `st.session_state["queued_questions"]` and routes back.
- **Researcher model**, **Verifier model**, **Verifier strategy**,
  **Parallel limit** dropdowns. Models default to the values in
  `model_defaults`. Strategy includes a `★ all four` option that fans
  out N × 4 verifier runs per Researcher row (for strategy comparison
  experiments).
- **Pre-flight banner**: warns if projected cost exceeds 85% of the
  remaining 5-hour window; blocks release if it exceeds the window.
- **Hand-mark lock check**: shows how many of the selected (question,
  country) pairs have locked hand-marks. Allows release anyway with a
  flag in `notes`.
- **Save preset** button stores the launcher config to a JSON file under
  `dashboard/presets/`.

Live subtrio cards (one card per running or recently-finished subtrio):
- Header: question_id · country · retry badge · elapsed · tokens · cost.
- Three-stage pipeline visualisation: Researcher → Verifier → Final.
  Active stage highlighted in blue/amber; completed in green; failed in
  red. Sub-stage shown inside the active block.
- One-line status from `subtrio_status.last_message`.
- Cancel button (SIGTERM to the subprocess; row marked `failed`).

Refreshes every 1 second.

### 7.3 Results

Table view of all rows across `phase2_researcher_runs`,
`phase2_verifier_runs`, and `phase2_final`. Filters: country, dimension,
strategy, model, date range, verdict, batch_id. Click a row → side
drawer with the full LLM response, the prompt that produced it, and the
linked Researcher row if it's a Verifier row.

### 7.4 Strategy Lab

For a given (question, country, Researcher row), fire all four Verifier
strategies and show their verdicts side by side. Used for the D15
comparison experiment. Hooks into the existing
`scripts/run_verifier.py --strategy …` path.

### 7.5 Hand-marks

Browse hand-marks by country. Shows lock status (committed SHA or
"unlocked"), composite score, tier. Provides an "edit on disk" link that
opens the CSV in the user's default editor. The dashboard does not write
hand-marks directly; the audit trail rule (D9) requires git commits.

### 7.6 Questions

Browsable table of all 143 ODMI questions. Filter by dimension,
indicator, hand-mark status, country, free-text search. Multi-select rows
with a "Send N → Run Console" action.

### 7.7 Prompts

Table of `prompt_versions`. For each prompt, show the rows that used it
(count of runs by table). Click → side drawer with full prompt text.
Read-only at v1 of the dashboard.

### 7.8 Models

Two halves.

Top — **Defaults**. Editable assignment of agent_role → model. Persists
to `model_defaults`. Used by the Run Console's dropdowns and by any CLI
invocation that does not override.

Bottom — **Analytics**. Pivot tables:
- agent_role × model → row count, mean cost, mean wall-clock, mean
  confidence, pass rate (for Verifier).
- Researcher model × Verifier model → heatmap of pair pass rate. This is
  the D18 cross-product summary.
- Cost per agent role per model over the last 30 days as a line chart.

### 7.9 Costs

The cost surface (D12). Cumulative spend by day, by dimension, by tier,
by strategy. Cost-per-correct-answer once a notion of correctness exists
(needs hand-marks). Token rates over time. The estimated_cost is the
arithmetic-equivalent figure (Q9, footnoted).

## 8. Sidebar — Claude session widget

Pinned at the bottom of the sidebar on every page. Reads
`claude_usage_log`:

- Tokens used in the last 5 hours (sum input + output, all calls).
- Cost equivalent in the last 5 hours.
- Estimated remaining capacity. The 5-hour subscription window does not
  publish an exact cap; the widget estimates capacity from a configurable
  per-window soft limit (default 2M tokens). The user can adjust this in
  a settings JSON.
- Time until the oldest call in the window ages out.

Shown as a small status block with a progress bar. Refreshes every 5
seconds.

## 9. Credit and outage handling

Three layers:

1. **Pre-flight prediction** (in `dispatch_subtrios.py`):
   `projected = n_pairs × avg_cost_last_50 × retry_uplift`. Compare to
   `budget = soft_limit_cost - cost_in_last_5h`. Warn if projected >
   0.85 × budget. Refuse if projected > budget.
2. **Live enforcement** (in `dispatch_subtrios.py`): before spawning each
   new subprocess, re-check the rolling 5-hour cost. If below 5% of the
   soft limit, stop spawning new subtrios. Already-running subtrios
   finish.
3. **Clean shutdown on rate-limit error** (in `agents/tools/llm.py`):
   wrap every call. On `anthropic.RateLimitError`, write a final
   `claude_usage_log` row with `rate_limited=1`, then raise
   `RateLimitedShutdown`. The Coordinator catches it, updates the
   `subtrio_status` row, exits with code 42. The dispatcher catches
   exit code 42 and orchestrates the kill-and-mark cycle.

A `cleanup_subtrios.py` script reaps orphans after any uncontrolled exit.

## 10. Hand-mark lock rule (D9) and the dashboard

The dashboard surfaces the D9 lock check; it does not enforce it. A
release on unlocked hand-marks proceeds anyway, but the resulting
`phase2_final` rows are written with `notes` containing
`"unlocked_handmark_at_release"`. Downstream analysis filters can then
exclude these rows from the headline accuracy figure.

The Hand-marks page is read-only at v1 of the dashboard. Editing happens
in the CSV files and is committed to git, as D9 requires.

## 11. Implementation order

Build in this order so each step is independently usable:

1. **Schema migration**: add the three new tables to
   `scripts/setup_sqlite.py`. Wire `claude_usage_log` into
   `agents/tools/llm.py`.
2. **`scripts/run_coordinator.py`**: per AGENT_DESIGN §5. Standalone CLI
   that can be invoked without the dashboard. Includes the
   `subtrio_status` writes.
3. **`scripts/dispatch_subtrios.py`**: pre-flight + Popen pool + clean
   shutdown.
4. **Streamlit shell**: `dashboard/Home.py`, sidebar, Claude session
   widget, navigation only. Nothing live yet.
5. **Run Console page**: launcher → dispatch_subtrios.py + live subtrio
   cards.
6. **Questions page** with multi-select → Run Console hand-off.
7. **Results page**: table + side drawer.
8. **Hand-marks page**: read-only.
9. **Models page**: defaults + analytics.
10. **Costs page**: aggregate views.
11. **Strategy Lab**: side-by-side strategy comparison.
12. **Prompts page**: prompt_versions browser.

Steps 1-3 are usable from the CLI alone. Step 5 is the first dashboard
milestone with end-to-end utility.

## 12. Testing

- `pytest tests/test_dispatch_subtrios.py` covers the pre-flight
  arithmetic and the semaphore behaviour with mocked subprocesses.
- `pytest tests/test_run_coordinator.py` covers the state-graph
  transitions with mocked agents.
- `pytest tests/test_claude_usage_log.py` checks that every LLM call
  writes one row.
- The Streamlit pages are tested manually. A `dashboard/smoke_test.sh`
  script launches the app, asserts the dashboard returns a 200 on the
  home page, and stops. No headless-browser tests at v1.

## 13. Out of scope (v1)

- Editing hand-marks from the UI. CSV + git remains canonical.
- Editing prompts from the UI. Prompt files in `agents/prompts/` remain
  canonical; new versions land via code commits.
- Authentication. Single-user local app.
- Pause / resume for in-flight subtrios. Cancel-only.
- Multi-machine workers. All subprocesses run on the laptop.
- Cross-day cost rollups beyond the last 30 days.

## 14. Open questions

- **Q-DASH-1**: What is the right soft cap for the rolling 5-hour token
  budget? Set as a config value, default 2,000,000 tokens. Calibrate
  after observing one full day of runs.
- **Q-DASH-2**: Should `dispatch_subtrios.py` use `multiprocessing` or
  raw `subprocess.Popen`? Leaning Popen because each child is its own
  Python process with its own SQLite connection; multiprocessing's
  shared-memory features are not needed.
- **Q-DASH-3**: Streamlit's session_state is per-tab. If the user opens
  two tabs they will not share launcher state. Acceptable at v1.

## 15. Numbered decisions to add to SPEC.md when implementation begins

- **D19** (proposed): Streamlit dashboard as the primary research
  control surface. Subprocess pool model. Live subtrio_status table.
- **D20** (proposed): Rolling-window credit budget enforcement with
  pre-flight prediction, live cap, and clean rate-limit shutdown.
- **D21** (proposed): Two new schema tables (subtrio_status,
  claude_usage_log) and one config table (model_defaults).
