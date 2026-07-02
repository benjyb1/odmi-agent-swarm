# ODMI Agent Swarm

MSc Advanced Computing dissertation (King's College London, 2026).

A three-agent LLM swarm — Researcher, adversarial Verifier, Adjudicator — that answers EU Open Data Maturity Index (ODMI) questions across 36 European countries by searching the live web, then checks its own answers against the 5,148 ground-truth responses ODMI has already published, with every match/differ classification surfaced on a public dashboard.

Public dashboard: <https://odmi-agent-swarm-f5b4cbeukwunzkuvp2tswn.streamlit.app/>

## Why a swarm instead of one model call

A single LLM asked "does Portugal publish its open data licence in machine-readable form?" will answer confidently whether or not it actually knows. This project treats that as the central risk to design against, not a footnote. The pipeline separates *finding* evidence from *attacking* it:

1. **Researcher** — generates 2–3 search queries, retrieves pages via a Tavily → DIY (Serper + trafilatura + Claude snippet-picker) → Brave fallback chain, and returns a structured answer with a verbatim evidence quote, a source URL, and two separate confidence scores (retrieval confidence, answer confidence).
2. **Verifier** — runs a deterministic substring check that the Researcher's quoted evidence actually appears in the fetched page, then goes looking for disconfirming evidence with its own adversarial search, under one of four prompt strategies (disprove / negate / steelman / blind). It only agrees with the Researcher if the counter-search comes back empty-handed.
3. **Adjudicator** — fires only when Researcher and Verifier fail to converge after three retries. No web search of its own; it reasons over the evidence already gathered and auto-demotes any verdict below 0.6 confidence to "abstain" rather than guessing.

A pair is only committed automatically when the Researcher's answer confidence clears 0.65 *and* the Verifier's verdict is "pass" (0.98 for questions derivable straight from ODMI's own published catalogue). Everything short of that goes to adjudication or abstains — the system is built to say "not sure" rather than fabricate a match.

## What's actually engineered here

- **Reproducible by construction.** Every LLM call — prompt, version number, full raw response, timestamp — is written to `prompt_versions`. You can reconstruct any historical answer from the database alone, no re-running required.
- **Cost control that isn't an afterthought.** A circuit breaker caps any single dispatch at 500 (question, country) pairs after an earlier accidental cross-product run burned through hours of budget. Per-model pricing (Haiku/Sonnet/Opus) is hard-coded for transparent cost estimates, and a three-layer SQLite cache (search results / fetched pages / picked snippets, 30-day TTL) means retries and ablations don't re-pay for the same web calls.
- **Adversarial verification, not self-agreement.** The Verifier is deliberately built to try to break the Researcher's answer rather than rubber-stamp it — four different adversarial framings were pre-registered and compared, not picked after the fact.
- **81 test files, ~13,500 lines of tests**, including a live-vs-mocked split so the core suite runs with zero API calls and a separate `make verify-diy-live` gate exercises the real search pipeline before any change to it ships.
- **Honest failure-mode register.** The methodology doc tracks specific, named ways this can go wrong in production — evidence with no date signal, negation context that falls outside the snippet boundary, third-party republication of ODMI's own answer key bypassing the deny-list — rather than presenting the pipeline as solved.

## Status

Phase A: running end to end on the first four countries (FR, DE, NL, RO). 11 finalised pairs, all matching ODMI's 2025 ground truth on the current Policy-dimension sample. Phase B (harder dimensions, more countries, head-to-head Verifier strategy comparison) is the next push — see `docs/SPEC.md` for the live status block.

## What to read

- `CLAUDE.md` — quality standards and the evaluation contract this project holds itself to.
- `docs/SPEC.md` — living spec: numbered decisions, current status, open questions, change log.
- `docs/METHODOLOGY.md` — locked methodology: ODMI ground truth, stratification by dimension, optimisation experiments.
- `docs/REPORT_PRELIM.md` — preliminary dissertation report draft.

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

The full pipeline lives in `agents/tools/search_diy.py`. The methodologically central Layer-2 quality test reads `tests/fixtures/snippet_quality.jsonl` (regenerated on demand from the DB with `make snippet-fixtures`) and asserts the new Claude snippet-picker overlaps with passages the swarm's Verifier historically accepted. See `docs/superpowers/plans/2026-05-26-diy-tavily.md` for the full plan and Layer 1–9 test strategy.

## Tech stack

Python 3.11+ (`uv`), Anthropic API (Claude Max via CLIProxyAPI), Tavily + Serper + Brave search, trafilatura + Playwright for extraction, Pydantic for structured LLM output, SQLite for the audit trail, Streamlit + Altair + Plotly for the dashboard, `python-pptx` for the supervisor deck, pytest for the test suite.

## Author

Benjamin Bream.
