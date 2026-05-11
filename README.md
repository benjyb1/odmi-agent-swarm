# ODMI Agent Swarm

MSc Advanced Computing dissertation (King's College London, 2026).

An LLM-powered agent swarm that automatically answers EU Open Data Maturity
Index (ODMI) questions across 36 European countries. Validated against
existing ground truth and deployed against the live 2026 reporting cycle.

## What to read

- `CLAUDE.md` — Claude Code context. Working preferences, quality standards,
  audit-trail rules.
- `docs/SPEC.md` — living spec. Numbered decisions, current status, open
  questions, change log.
- `docs/METHODOLOGY.md` — locked methodology. Rubric, hand-marking protocol,
  evaluation plan.
- `docs/REPORT_PRELIM.md` — preliminary project report draft (due
  2026-05-22).
- `data/hand_marks/PROTOCOL.md` — how to hand-mark questions reproducibly.

## Quickstart

```bash
# Install deps
uv sync

# Set up the SQLite database (idempotent)
uv run python scripts/setup_sqlite.py

# Parse the official ODMI questionnaire into structured JSON
uv run python scripts/parse_questions.py

# Run unit tests
uv run pytest
```

## Status

Phase A setup. Foundation in place; agent swarm not yet built. See
`docs/SPEC.md` for the live status block.
