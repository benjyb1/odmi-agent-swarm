# ODMI Agent Swarm

MSc Advanced Computing dissertation (King's College London, 2026).

An LLM-powered three-agent swarm (Researcher, adversarial Verifier,
Adjudicator) that automatically answers EU Open Data Maturity Index
(ODMI) questions across 36 European countries. Each swarm answer is
compared against ODMI's own published response for the (question,
country) pair, with the match/differ classification surfaced on a
live Streamlit dashboard.

Public dashboard:
<https://odmi-agent-swarm-f5b4cbeukwunzkuvp2tswn.streamlit.app/>

## What to read

- `CLAUDE.md` — Claude Code context. Quality standards and the
  evaluation contract.
- `docs/SPEC.md` — living spec. Numbered decisions, current status,
  open questions, change log.
- `docs/METHODOLOGY.md` — locked methodology. ODMI ground truth,
  stratification by ODMI dimension, optimisation experiments.
- `docs/REPORT_PRELIM.md` — preliminary project report draft.

## Quickstart

```bash
# Install deps
uv sync

# Set up the SQLite database (idempotent)
uv run python scripts/setup_sqlite.py

# Parse the official ODMI questionnaire into structured JSON
uv run python scripts/parse_questions.py

# Load the question catalogue into the SQLite questions table
uv run python scripts/load_questions.py

# Load ODMI's 5,148 ground-truth answers (36 countries × 143 questions)
uv run python scripts/load_ground_truth.py

# Launch the dashboard
uv run streamlit run dashboard/Home.py

# Dispatch a swarm batch
uv run python scripts/dispatch_subtrios.py --questions P1 --countries FR DE NL

# Regenerate the supervisor slide deck against current DB state
uv run python scripts/generate_slides.py

# Run unit tests
uv run pytest
```

## Development

DIY-Tavily test gate (run before any DIY-Tavily commit):

```bash
make verify-diy         # 93 non-live tests across the eight DIY-Tavily modules
make verify-diy-live    # live tests against real Serper + Claude (costs ~30 API calls)
make help               # list all targets
```

The full pipeline lives in `agents/tools/search_diy.py`. The
methodologically central Layer-2 quality test reads
`tests/fixtures/snippet_quality.jsonl` (regenerated on demand from the
DB with `make snippet-fixtures`) and asserts the new Claude
snippet-picker overlaps with passages the swarm's Verifier
historically accepted. See `docs/superpowers/plans/2026-05-26-diy-tavily.md`
for the full plan and Layer 1-9 test strategy.

## Status

Phase A. Swarm running end-to-end on the first four countries
(FR, DE, NL, RO). 11 finalised pairs, all matching ODMI 2025 ground
truth on the current Policy-dimension sample. Phase B expansion
(harder dimensions, more countries, Verifier strategy comparison)
is the next push. See `docs/SPEC.md` for the live status block.
