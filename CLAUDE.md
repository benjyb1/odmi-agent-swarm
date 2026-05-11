# ODMI Agent Swarm — Claude Code Context

MSc Advanced Computing dissertation (King's College London, 2026). An LLM-powered
agent swarm that automatically answers EU Open Data Maturity Index (ODMI) questions
across 36 countries in 20+ languages. Validated against 2024 ground truth, targeting
the 2026 assessment cycle.

## Read first

At the start of every session, read these in order:

1. `docs/SPEC.md` — the living spec. Numbered decisions, current status, change log,
   open questions. The single source of truth for project state.
2. `docs/METHODOLOGY.md` — the locked methodological choices. Rubric definitions,
   hand-marking protocol, evaluation plan. This is what an examiner needs to
   understand the methodology.
3. Notion master page (id `331acc75-be02-8163-9169-e327fed97055`) — research
   narrative, supervision log, weekly observations. Fetch via the Notion MCP if
   asked about anything not in the repo.

## Quality standards

This is a dissertation, not a hackathon. Every artefact must hold up to an
examiner's scrutiny.

- **Receipts everywhere.** Every prompt is versioned in `prompt_versions`. Every
  LLM call writes a row that includes model version, prompt version, full raw
  response, and a timestamp. Every hand-mark is dated and committed to git before
  any automated run touches the same question. The git history is the decision
  history.
- **No hallucination.** If a source does not confirm a claim, the system does
  not pretend it does. All agent outputs trace to a specific URL with a quoted
  passage.
- **Justified decisions.** Every architectural and methodological choice has a
  numbered entry in `docs/SPEC.md` with rationale. "It seemed easiest" is not
  sufficient.
- **Reproducibility.** An examiner with the repo and a copy of the SQLite file
  must be able to replay every evaluation from logs alone.
- **Honest evaluation.** Negative results count. If the rubric fails to predict
  difficulty, that is a finding worth reporting, not a problem to hide.

## Audit-trail rule (Option 3 specific)

The three-dimension rubric is no longer a runtime classifier. It is an
analytical lens for stratifying swarm results. To avoid evaluator bias, hand-marks
must be locked before swarm runs.

- Hand-marks live in `data/hand_marks/` as CSV.
- A hand-mark is "locked" when it has been committed to git.
- No swarm result may reference a hand-mark that was not committed before the
  swarm run started.
- The mirror table `hand_marks` in SQLite records the git commit SHA that locked
  each row.

If you are about to run the swarm and the relevant hand-marks are uncommitted,
stop and commit first.

## Repo layout

```
agents/             # Agent code (only classifier.py exists)
data/
  questions/        # Parsed ODMI question bank (JSON + xlsx)
  hand_marks/       # Hand-marked rubric scores (the audit-trail evidence)
  odmi.db           # SQLite — every classification, every run, every prompt
docs/
  SPEC.md           # Living spec. Updated every session.
  METHODOLOGY.md    # Locked methodology. Rubric + hand-marking + evaluation.
  PROJECT_LOG.md    # Session-by-session technical log.
  REPORT_PRELIM.md  # Preliminary project report (due 22 May 2026).
  references.bib    # BibTeX bibliography for the report and dissertation.
evaluation/         # Analysis scripts (empty for now)
scripts/            # Setup and runner scripts
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
- LangGraph for the Phase 2 agent swarm (Coordinator, Researcher, Adversarial
  Verifier). Not built yet.
- Claude (Sonnet currently) routed through CLIProxyAPI on `localhost:8317`, using
  Benjy's Claude Max subscription. No direct Anthropic API billing.
- Tavily for web search; Playwright for browser automation; DeepL for
  low-resource language fallback (Phase B onward).
- SQLite at `data/odmi.db` is the primary data store. Schema in
  `scripts/setup_sqlite.py`.

## Common commands

```bash
# Activate env
source .venv/bin/activate

# Create or refresh DB
uv run python scripts/setup_sqlite.py

# Parse the official questionnaire xlsx into JSON
uv run python scripts/parse_questions.py

# Run unit tests
uv run pytest

# (Phase 1 runner exists but is not wired for option 3 — see SPEC D8.)
```

## Working preferences

- Plan with Opus, execute with Sonnet for code.
- When asked for a diagram, prefer SVG so it drops into the manuscript without
  re-rendering.
- Push back on weak decisions. Don't just agree.
- When given a Notion link or page ID, fetch via the Notion MCP before answering.
- Commit small and often. Five weeks without a commit is why we are
  reverse-engineering state today.

## What's actually built

See `docs/SPEC.md` for the current status block. As of 2026-05-11: repo
scaffolded, SQLite schema deployed (empty), questions parsed (143 questions),
no LLM calls executed yet, no swarm code, partial hand-marks (two questions).
