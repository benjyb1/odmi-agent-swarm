# ODMI Agent Swarm

MSc Advanced Computing dissertation, King's College London, 2026. Author: Benjamin Bream.

An LLM agent swarm answers the EU Open Data Maturity Index (ODMI) questionnaire
from the open web, and its answers are scored against the assessments ODMI
published for the 2025 cycle.

The questionnaire has 143 questions and is answered by 36 countries, giving
5,148 published answers. Those answers are the ground truth. The swarm never
reads them while working; they are joined in afterwards to classify each pair as
a match or a difference.

Public dashboard: <https://odmi-agent-swarm-f5b4cbeukwunzkuvp2tswn.streamlit.app/>

## The three agents

A single model asked "does Croatia publish its open data licence in
machine-readable form?" will answer with the same confidence whether or not it
knows. The pipeline is built around that risk. Finding evidence and attacking
evidence are separate jobs held by separate agents.

**Researcher** (`agents/researcher.py`) writes 2 to 3 search queries, retrieves
pages, and returns a structured answer carrying a verbatim quote, the URL it
came from, and two confidence scores. Retrieval confidence and answer confidence
are recorded separately, because a well-sourced page and a well-supported claim
fail in different ways.

**Verifier** (`agents/verifier.py`) first runs a deterministic substring check
that the quoted evidence appears on the page that was fetched. No LLM is
involved in that step. It then runs its own search looking for evidence against
the Researcher's answer, under one of four adversarial framings (disprove,
negate, steelman, blind). It agrees only when the counter-search finds nothing.

**Adjudicator** (`agents/adjudicator.py`) runs when the two fail to converge
after three retries. It performs no search of its own and reasons over the
evidence already gathered. Any verdict it reaches below 0.6 confidence is
demoted to an abstention.

The Coordinator (`scripts/run_coordinator.py`) is a plain Python state machine.
The original spec called for a graph-orchestration framework; the retry loop
turned out to be linear and a graph runtime added debugging cost with no change
in behaviour. That deviation is recorded as D3 in `docs/SPEC.md`.

A pair commits automatically when the Researcher's answer confidence reaches
0.65 (`COMMIT_CONFIDENCE_FLOOR`, D37) and the Verifier passes. Questions
answered by a deterministic recompute over the country's own data catalogue
commit at 0.98 (D30). Anything else goes to adjudication or abstains. The system
is built to return "not sure".

Search runs through one pipeline: Serper for the result list, trafilatura for
extraction, and a Claude call to pick the relevant snippet from the extracted
text. Tavily and Brave were retired in D43 and their code paths remain only so
historical rows stay readable. The production model is `claude-sonnet-4-6`,
routed through a local CLIProxyAPI instance.

## What was measured

The headline evaluation is EXP-36, 1,144 pairs across eight countries held out
from all development: Bosnia and Herzegovina, North Macedonia, Montenegro,
Bulgaria, Finland, Croatia, Sweden and Belgium. Of those pairs, 909 have a
binary gold answer and 370 have a negative gold.

EXP-42 replays that run as a four-rung architecture ladder. Each rung adds one
component, so the contribution of each is visible:

| Arm | Coverage | Commit accuracy | Negative-gold FPR |
|---|---|---|---|
| Researcher alone | 0.266 | 0.767 | 0.124 (46/370) |
| Researcher + Verifier | 0.460 | 0.740 | 0.232 (86/370) |
| Full trio (production) | 0.556 | 0.735 | 0.246 (91/370) |
| Cooperative verifier | 0.476 | 0.727 | 0.270 (100/370) |

The adversarial Verifier roughly doubles coverage and roughly doubles the
false-positive rate on negative golds. It is not acting as a precision filter,
which is the opposite of what the design predicted. That result is reported as
it stands. `docs/RESULTS.md` carries the full read with confidence intervals and
paired significance tests.

## Requirements

- Python 3.11 or newer. The lockfile resolves cleanly on 3.14, which is what
  this repository was last verified against.
- [uv](https://docs.astral.sh/uv/) for dependency management. Every command
  below is a `uv run`, so no manual virtualenv activation is needed.
- A copy of `data/odmi.db`. It is tracked through Git LFS and is about 375 MB.
  Reading results, replaying evaluations and running the dashboard need nothing
  else.

API keys are needed only to dispatch a new swarm run. Copy `.env.example` to
`.env` and fill in:

| Variable | Needed for |
|---|---|
| `ANTHROPIC_BASE_URL` | LLM calls. Points at the local CLIProxyAPI, `http://localhost:8317`. |
| `ANTHROPIC_API_KEY` | LLM calls. A placeholder when routed through the proxy. |
| `SERPER_API_KEY` | Web search. The only search key the current pipeline uses. |
| `DEEPL_API_KEY` | Translation fallback for low-resource languages. |
| `TAVILY_API_KEY`, `BRAVE_SEARCH_API_KEY` | Retired search providers (D43). Unset unless replaying a pre-D43 run. |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY` | Cross-family search adjudicator variants used in one experiment arm. |
| `ODMI_READ_ONLY` | Set to `1` to disable every write button in the dashboard. Set on the public deployment. |
| `ODMI_SKIP_AUTO_PUBLISH` | Set to `1` to stop a dispatch auto-publishing its results. |

`.env` is in `.gitignore` and must stay there.

## Install

```bash
uv sync
```

That installs the runtime dependencies and the `dev` group, which carries
pytest, ruff and matplotlib. Nothing further is needed to run the figure
scripts.

## Build the database

Skip this if you already have `data/odmi.db`. The four commands build a fresh
database holding the schema, the question catalogue and ODMI's published
answers. They do not run the swarm, so the result contains no swarm rows.

```bash
uv run python scripts/setup_sqlite.py
```

```bash
uv run python scripts/parse_questions.py
```

```bash
uv run python scripts/load_questions.py
```

```bash
uv run python scripts/load_ground_truth.py
```

`setup_sqlite.py` refuses to overwrite an existing database unless passed
`--force`, so running it against a populated file is safe. The last two print
their row counts: 143 questions and 5,148 ground-truth rows.

## Launch the dashboard

```bash
uv run streamlit run dashboard/Home.py
```

It serves on <http://localhost:8501> and reads `data/odmi.db` directly. The home
page carries the headline accuracy against ODMI, per-country coverage and live
dispatch state. The pages under `dashboard/pages/` hold per-pair results with
full evidence trails, the question catalogue, the Verifier strategy comparison,
a raw table browser, model defaults, the cost surface, prompt versions and the
analytics views.

## Replay an evaluation

Every published number is arithmetic over rows already in the database. No LLM
calls are made and no network access is needed.

```bash
uv run python evaluation/exp42_ladder.py --json /tmp/exp42.json
```

This reprints the ladder table above from the stored EXP-36 rows, with Wilson
intervals and paired McNemar tests, and writes the machine-readable result to
the path given. Passing `--json` keeps the committed copy in
`evaluation/results/` untouched.

```bash
uv run python evaluation/exp36_analysis.py --out /tmp/exp36.json
```

This recomputes the pre-registered EXP-36 endpoints: per-class recall with
Wilson intervals, balanced accuracy and Youden's J against a majority-class
baseline. Both scripts accept `--db` if the database sits elsewhere.

`evaluation/results/` holds the committed result JSON for every experiment.
Those files are the audit trail. Write replays to a scratch path and leave the
committed copies alone.

## Tracing a figure or a number

`docs/figures/README.md` maps every figure in the write-up to the script that
produced it, and records which figures are written directly and which are copied
from `evaluation/figures/`. The CSV receipts beside each graphic in
`evaluation/figures/` state what that graphic was drawn from.

For numbers in the text, `docs/RESULTS.md` names the reproducing script and the
result JSON at the end of each experiment section. `docs/SPEC.md` carries the
numbered decisions (D1, D22, D37 and so on) that comments throughout the code
cite.

## Run the tests

```bash
uv run pytest
```

917 pass and 13 skip. The skips need live network access or a database state
that a fresh checkout does not have. The suite makes no API calls: live tests
are marked and excluded by default.

```bash
make verify-diy
```

103 tests over the eight modules of the search pipeline. This is the gate to run
before changing anything under `agents/tools/search*`.

```bash
make verify-diy-live
```

The live counterpart, which calls real Serper and Claude endpoints and costs
roughly 30 API calls. `make help` lists the remaining targets.

`conftest.py` at the repository root stops the suite touching `data/odmi.db`. It
redirects every module constant that names the canonical file to a scratch copy,
and wraps `sqlite3.connect` so that anything the redirect misses raises instead
of writing. The database is git-tracked and holds frozen experiment rows, so a
test that dirties it would be committed by accident.

## Dispatch a swarm run

This costs money and makes live API calls.

```bash
uv run python scripts/dispatch_subtrios.py --questions P1 --countries FR DE
```

A circuit breaker caps any single dispatch at 500 pairs. Search results, fetched
pages and picked snippets are cached in SQLite for 30 days, so a retry or an
ablation does not re-pay for the same web calls.

## Directory map

| Path | Contents |
|---|---|
| `agents/` | The three agents, their prompt modules, and the shared tools for search, extraction, caching, the LLM wrapper and the deterministic catalogue route. |
| `dashboard/` | Streamlit app. `Home.py` plus nine pages and the helpers in `lib/`. |
| `data/` | `odmi.db`, the ODMI question bank, per-country trusted-domain lists, and the inert hand-mark CSVs kept as audit history. |
| `docs/` | The living spec, the locked methodology, the failure-mode register, experiment pre-registrations and results, and the figure provenance index. |
| `evaluation/` | Analysis and replay scripts. One script per experiment or per figure, all read-only over the database. |
| `evaluation/results/` | Committed result JSON. The audit trail behind every published number. |
| `evaluation/specs/` | Experiment pre-registrations, written before each run. |
| `scripts/` | The Coordinator, the dispatcher, database setup and loaders, schema migrations and the experiment orchestrator. |
| `tests/` | 97 test files, about 16,500 lines. Live tests are marked and excluded by default. |
| `who_speech/` | A separate side project that reuses the swarm against the WHO Europe document set. Not part of the dissertation. |
| `conftest.py` | The two-layer guard that keeps pytest away from the canonical database. |
| `Makefile` | The search-pipeline test gates and the fixture regeneration targets. |

## Reading order

1. `docs/SPEC.md` for project state and the numbered decisions.
2. `docs/METHODOLOGY.md` for how the evaluation is set up and why.
3. `docs/RESULTS.md` for the experiments and what they found.
4. `docs/FAILURE_MODES.md` for the 34 registered ways this can produce a wrong
   answer, and which of them are mitigated.
