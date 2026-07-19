# ODMI Agent Swarm — Claude Code Context

MSc Advanced Computing dissertation (King's College London, 2026). An LLM-powered
agent swarm that automatically answers EU Open Data Maturity Index (ODMI) questions
across 36 countries in 20+ languages. Validated against 2024 ground truth, targeting
the 2026 assessment cycle.

## How to talk to Benjy (mandatory, every reply)

Benjy runs several Claude instances at once and cannot read long prose. Two layers:

1. **Working-out** — tool calls, tests, reasoning. Unrestricted, but narrate it in
   single short lines, not paragraphs. He skims or skips this.
2. **Final block** — always last, after a `---` divider. This is the only part he
   reads. Every fact he needs goes here. Fields, in order, omit one only if empty:
   - **Context** — the problem, 1-2 short sentences.
   - **Doing** — the fix or action taken.
   - **Results** — commands run, outcomes, numbers. Facts only, no spin.
   - **Analysis** — what the numbers mean. One or two lines.
   - **Next** — the next step, or the decision needed from Benjy.

Style for everything addressed to him:
- Short sentences. Bullets over paragraphs. No essays. Final block under ~150 words
  unless he asks for depth.
- Formal, matter-of-fact, concise. State facts and numbers.
- Banned: agreement and praise openers ("you're right", "great point", "good call",
  "absolutely"), apologies for style, hedging, filler.
- Never state an unverified number. Verify against the DB or code, then state it.

## Read first

At the start of every session, read these in order:

1. `docs/SPEC.md` — the living spec. Numbered decisions, current status, change log,
   open questions. The single source of truth for project state.
2. `docs/METHODOLOGY.md` — the locked methodological choices. Evaluation against
   ODMI ground truth, stratification by ODMI dimension, optimisation experiments.
3. Notion master page (id `331acc75-be02-8163-9169-e327fed97055`) — research
   narrative, supervision log, weekly observations. Fetch via the Notion MCP if
   asked about anything not in the repo.

When the task is hardening the swarm, improving robustness, or "attacking the
failure modes" (anything about false positives, wrong answers slipping through,
or the verification gaps), read `docs/FAILURE_MODES.md` first. It is the 34-mode
register with the structural attack list and a suggested attack order.

## Quality standards

This is a dissertation, not a hackathon. Every artefact must hold up to an
examiner's scrutiny.

- **Receipts everywhere.** Every prompt is versioned in `prompt_versions`. Every
  LLM call writes a row that includes model version, prompt version, full raw
  response, and a timestamp. The git history is the decision history.
- **No hallucination.** If a source does not confirm a claim, the system does
  not pretend it does. All agent outputs trace to a specific URL with a quoted
  passage.
- **Justified decisions.** Every architectural and methodological choice has a
  numbered entry in `docs/SPEC.md` with rationale. "It seemed easiest" is not
  sufficient.
- **Reproducibility.** An examiner with the repo and a copy of the SQLite file
  must be able to replay every evaluation from logs alone.
- **Honest evaluation.** Negative results count. Disagreements between the swarm
  and ODMI ground truth are findings worth reporting, not problems to hide.

## Evaluation (per D22)

The swarm is evaluated by direct comparison against ODMI's published answers
for each (question, country) pair.

- Ground truth lives in the SQLite `ground_truth` table, mirrored from
  the `merged_responses` sheet of `data/questions/2025_odm_questionnaire_data.xlsx`
  by `scripts/load_ground_truth.py`. 5,148 rows: 36 countries × 143 questions.
- Each finalised swarm pair joins to its ground-truth row and is classified
  `match` / `differ` / `no_ground_truth` by the SQL CASE in
  `dashboard/lib/db.py:_MATCH_STATUS_SQL`.
- Stratification axis is the ODMI dimension (Policy / Portal / Quality / Impact)
  plus country, not a custom rubric.
- ODMI's answers can be one cycle old: a swarm-vs-ODMI disagreement is not
  automatically a swarm error. Each disagreement deserves a human glance.
- Data-leakage risk: ODMI publishes its own answers on data.europa.eu, so a
  Researcher's Tavily search could surface the answer page. The mitigation
  is a deny-list on the evaluation-cycle domain (tracked in SPEC).

D6/D8/D9/D10 (the rubric and hand-marking workflow) are superseded by D22.
Hand-mark CSV files and the `hand_marks` SQLite table remain in the repo as
inert audit-trail history only.

## Repo layout

```
agents/             # Researcher, Verifier, Adjudicator, shared tools
dashboard/          # Streamlit dashboard (Home + 7 pages + lib helpers)
data/
  questions/        # ODMI question bank (xlsx + parsed JSON)
  hand_marks/       # Inert. Audit-trail only, superseded by D22.
  odmi.db           # SQLite. Schema in scripts/setup_sqlite.py.
docs/
  SPEC.md           # Living spec. Updated every session.
  FAILURE_MODES.md  # False-positive register (FM-01..FM-34). The attack list.
  METHODOLOGY.md    # Locked methodology: ODMI ground truth, evaluation plan.
  PROJECT_LOG.md    # Session-by-session technical log.
  REPORT_PRELIM.md  # Preliminary report (due 22 May 2026).
  references.bib    # BibTeX bibliography.
  PROGRESS_SLIDES_*.pptx  # Generated by scripts/generate_slides.py.
evaluation/         # Analysis scripts (empty for now).
scripts/            # Setup and runner scripts.
tests/              # pytest
.env                # Never committed. Local API keys.
```

## Writing style (mandatory for any prose, code comments, or commit messages)

- UK English throughout (colour, organisation, specialised, analyse, behaviour).
- No em dashes.
- Never use the word "genuinely".
- No AI tells: no "delve", "underscore", "tapestry", "navigate the landscape",
  "in today's fast-paced world", "it's important to note", "crucial", "testament",
  "landscape".
- Plain academic register. Short sentences. Active voice. Concrete claims.
- For any drafted paragraph destined for the report or dissertation, run the
  humaniser skill before considering it done.

## Tech stack

- Python 3.11+, `uv` for dependency management.
- Researcher / Verifier / Adjudicator built; Coordinator is a plain Python
  state machine, not LangGraph (see `scripts/run_coordinator.py` for why).
- Claude (Sonnet currently) routed through CLIProxyAPI on `localhost:8317`,
  using Benjy's Claude Max subscription. No direct Anthropic API billing.
- Web search auto-fallback is Tavily → DIY (Serper SERP + trafilatura)
  → Brave (D36). Playwright for browser automation; DeepL for
  low-resource language fallback (Phase B onward).
- SQLite at `data/odmi.db` is the primary data store. Schema in
  `scripts/setup_sqlite.py`.
- Streamlit dashboard at `dashboard/Home.py`; deployed publicly to
  Streamlit Cloud (see D23). `ODMI_READ_ONLY=1` disables write buttons there.
- Costs are displayed in pounds via `dashboard/lib/currency.py`
  (`USD_TO_GBP=0.79`). The SQLite column is still named
  `estimated_cost_usd` — only the presentation layer converts.

## Common commands

```bash
# Create or refresh DB
uv run python scripts/setup_sqlite.py
uv run python scripts/load_questions.py
uv run python scripts/load_ground_truth.py

# Launch the dashboard locally
uv run streamlit run dashboard/Home.py

# Dispatch a swarm batch
uv run python scripts/dispatch_subtrios.py --questions P1 --countries FR DE

# Regenerate the slide deck against current DB state
uv run python scripts/generate_slides.py

# Run unit tests
uv run pytest
```

## Working preferences

- Plan with Opus, execute with Sonnet for code.
- When asked for a diagram, prefer SVG so it drops into the manuscript without
  re-rendering.
- Push back on weak decisions. Don't just agree.
- When given a Notion link or page ID, fetch via the Notion MCP before answering.
- Commit small and often. Five weeks without a commit is why we are
  reverse-engineering state today.

## Finished work lands on main (mandatory)

When Benjy says "commit", "push", or "commit and push this work", he means the
change must end up on `origin/main`. A task is not done until its work is merged
into `main` and pushed. Never leave finished work sitting on a worktree branch
and report it complete. That is the failure that left main dozens of commits
behind, with a pile of orphaned branches and worktrees to reverse-engineer.

Worktrees are scaffolding, not a destination. Benjy runs several Claude windows
against this one repo folder at once. If two windows both worked directly on
`main` in the shared folder they would overwrite each other, and a branch switch
in one would drag the others onto it. So each window works in its own worktree to
stay isolated, then lands the result on main. The isolation buys a clean merge;
it is not a place for work to live.

Workflow for any task that changes files:

- If this session is not already in a worktree, call `EnterWorktree` before
  editing. It makes an isolated worktree under `.claude/worktrees/` on a fresh
  branch off `origin/main` (the `worktree.baseRef=fresh` default).
- Do the work there and commit small and often on the branch.
- To finish, land it on `origin/main`: merge the branch (push straight to main,
  or open and merge a PR), then remove the worktree (`ExitWorktree` or
  `git worktree remove`). Only call the task done once the work is on
  `origin/main`.
- Keep local `main` current with `git pull --ff-only` so new worktrees branch
  off the live trunk, and prune stale worktrees and merged branches periodically.
- Read-only work is exempt: questions, reviews, searches, status checks.
- Never run `git checkout -b` for new work in the main checkout. It switches the
  shared folder under other running windows.

## Current status

See `docs/SPEC.md` for the live status block, current decisions and open
questions. It is the single source of truth for project state; do not
duplicate or summarise it here (this section went stale when it tried).
