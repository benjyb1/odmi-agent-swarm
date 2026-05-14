# ODMI Agent Swarm — Living Spec

Last updated: 2026-05-14

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

### D15: Verifier prompt strategies as an experimental condition

**Date:** 2026-05-11.

The Verifier's prompt is itself an experimental variable. Four
strategies are defined in `docs/AGENT_DESIGN.md` Section 4.10:
`verifier-disprove` (default), `verifier-negation`, `verifier-steelman`,
`verifier-blind`. They are compared on the same hand-marked set.
Reporting: hallucination catch rate, false rejection rate, tokens per
run.

The Verifier may reuse the Researcher's URLs and search queries. Many
ODMI questions ("does the portal expose an API?") have a single
authoritative source that both agents will find. The Verifier's value
is cognitive (the LLM's optimism bias used in reverse), not source
independence. The previously-noted deny-list constraint is dropped.

Substring check on the cited URL is the only structural mitigation
against pure fabrication; everything else is the Verifier's reasoning
under different prompt regimes.

### D16: Adjudicator path at max retries

**Date:** 2026-05-11.

When the Researcher and Verifier disagree across all three retries, the
Coordinator hands the case to an Adjudicator instead of marking the
pair as rejected. The Adjudicator does not run new searches; it weighs
the evidence already collected and either picks a winner or escalates
to a human queue.

Implementation: a Coordinator-internal LLM call, not a separately
versioned agent file. Lives in the Coordinator module. Uses the same
prompt versioning and cost logging. Full spec in
`docs/AGENT_DESIGN.md` Section 5.11.

Confidence threshold for picking a winner is 0.6 (below that, escalate
to human). This threshold is provisional; see Q13 below.

### D18: Model variants as a third family of optimisation experiments

**Date:** 2026-05-11.

Beyond prompt and retrieval optimisations (Family 1) and Verifier
prompt strategies (Family 2), the model itself is an experimental
variable. The Anthropic catalogue spans roughly 15x in price between
Haiku and Opus. The same accuracy result at one-fifth the cost is a
real finding; the same cost at meaningfully higher accuracy is also a
real finding.

Three model conditions for the Researcher (the same applies to the
Verifier and Adjudicator separately):

| Condition | Model | Approx price |
|---|---|---|
| `model-haiku` | claude-haiku-4-5-20251001 | $1/$5 per M tokens |
| `model-sonnet` (baseline) | claude-sonnet-4-6 | $3/$15 per M tokens |
| `model-opus` | claude-opus-4-6 | $15/$75 per M tokens |

Reporting: for each (Researcher model × Verifier model × Adjudicator
model) combination on the hand-marked sample, report accuracy, cost,
and latency. The full cross-product is 3 × 3 × 3 = 27 combinations,
which is too many. Run a reduced design: three "pure" combinations
(all-Haiku, all-Sonnet, all-Opus) plus a "tiered" combination
(Researcher=Haiku, Verifier=Sonnet, Adjudicator=Opus). Four conditions
total.

Open: Q15 below: which models for which agent. The tiered combination
might be the most interesting practical finding (cheap Researcher,
expensive Verifier to catch errors, premium Adjudicator only when
needed).

### D19: Streamlit dashboard as the primary research control surface

**Date:** 2026-05-12.

A multi-page Streamlit app at `dashboard/Home.py` becomes the
day-to-day interface for releasing subtrios, watching them progress,
browsing results, and comparing Verifier strategies. The CLI scripts
(`run_coordinator.py`, `dispatch_subtrios.py`, `run_researcher.py`,
`run_verifier.py`) remain canonical and usable standalone. The
dashboard is a viewer and a launcher; it never writes to the result
tables directly.

Rationale: a Streamlit app gets to first useful working state in hours,
not days. The agent-as-subprocess model with SQLite as the only
inter-process channel scales well enough for one user on one laptop.
Spec at `docs/superpowers/specs/2026-05-12-dashboard-design.md`.

Trade-off: Streamlit's session-state is per-tab. The Questions →
Run Console hand-off only works inside a single tab. Documented in
Q-DASH-3.

### D20: Rolling-window credit budget enforcement

**Date:** 2026-05-12.

The dispatcher (`scripts/dispatch_subtrios.py`) enforces a three-layer
credit policy against the rolling 5-hour Claude Max window:

1. **Pre-flight prediction.** Estimate per-pair cost from the last 50
   subtrios matching the exact `(researcher_model, verifier_model,
   adjudicator_model, verifier_strategy)` tuple. Three fallback levels
   if no exact match: ignore strategy, ignore adjudicator, cold-start
   default $0.10/pair. Refuse to launch if projected cost exceeds
   remaining budget; warn at 85%.
2. **Live enforcement.** Re-check the rolling-window cost before each
   new spawn. Stop dispatching when below the 5% low-water mark.
3. **Clean shutdown.** `agents/tools/llm.py` catches
   `anthropic.RateLimitError`, writes a final `claude_usage_log` row,
   and raises `RateLimitedShutdown`. The Coordinator catches that and
   exits with `EXIT_CODE_RATE_LIMITED = 42`. The dispatcher treats
   that exit code as a global stop signal: SIGTERM all children, mark
   their `subtrio_status` rows `interrupted_rate_limit`, exit cleanly.

The arithmetic-equivalent cost figure (per Q9 — flat CLIProxyAPI
subscription) is the input. Soft limit defaults to $5.00 per window,
tunable in the dashboard sidebar.

### D21: Three new schema tables for dashboard-era state

**Date:** 2026-05-12.

Added to `scripts/setup_sqlite.py` and via the idempotent
`scripts/migrate_dashboard_tables.py` for the live DB:

- `subtrio_status` — one row per subtrio. Stage, substage, retry,
  cumulative cost, last message, process PID. `final_verdict` mirrors
  `phase2_final.terminal_status` plus two dashboard-only values
  (`interrupted_rate_limit`, `orphaned`).
- `claude_usage_log` — one row per LLM call. Powers the rolling
  5-hour budget widget. Tracks `context` (e.g. `researcher:Q3:RO`),
  `subtrio_id`, `rate_limited` flag.
- `model_defaults` — per-role default model (researcher / verifier /
  adjudicator). Editable from the Models page.

All three migrate idempotently. Seeded with Sonnet defaults.

### D17: Decisions are revisited once we have real data

**Date:** 2026-05-11.

Standing principle. Decisions and open questions in this document are
treated as best guesses until the swarm has actually run on real
questions. Many design choices (Verifier strategy default, adjudicator
threshold, retry count, language routing) cannot be settled in the
abstract. We commit to revisit the open questions explicitly after:

- the first 10 hand-marked France questions have been run through the
  Researcher;
- the four Verifier strategies have been compared on at least 20
  pairs;
- the Adjudicator has fired at least 5 times.

Each revisit is logged as a change in the change log.

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

### D22: Ground truth from `merged_responses` is the evaluation set; hand-marks are dropped

**Date:** 2026-05-13.

The 2025 ODMI questionnaire xlsx ships a `merged_responses` sheet
with 5,148 rows: every (question_id, country_code) pair across 36
countries and 143 questions, with `response` (the country's actual
answer), `decision` (whether ODMI accepted it), `awarded_score`,
`max_score`, and `explanation`. This is the ground truth.

Hand-marking was the dangling remnant of the Phase 1 classifier that
D8 already removed from the critical path. With ODMI's own per-pair
answers available, the rubric stratification is no longer load-bearing
on evaluation. The dissertation evaluates by comparing each swarm
`final_answer` against the matching `response` row from
`merged_responses`, then stratifies accuracy and cost by ODMI
dimension (Policy / Portal / Quality / Impact), country, and indicator
rather than by custom rubric tier.

Supersedes the operational role of:
- **D6** (rubric definition) – kept as reference, not used at runtime.
- **D8** (rubric as analytical lens) – analytical lens role taken
  over by ODMI dimension.
- **D9** (hand-mark lock rule) – no longer relevant; ground truth
  is loaded from the xlsx and immutable per cycle.
- **D10** (hand-mark sample size and stratification) – moot.

Consequences:
- New SQLite table `ground_truth` mirrors `merged_responses` and is
  loaded by `scripts/load_ground_truth.py`. The xlsx is canonical;
  the DB is the join surface for swarm-vs-truth analysis.
- The Hand-marks page is removed from the dashboard sidebar. The
  `hand_marks` SQLite table and the two existing locked rows stay
  in the schema as inert audit-trail history; they're not consulted
  during evaluation.
- The country chart on the Home page and the Results page Cards
  view will surface the match / mismatch against ground truth.
- RQ2 (rubric stratification) is dropped or reframed as "accuracy
  varies across ODMI dimensions." RQ5 still stands but the cost
  surface is stratified by ODMI dimension rather than rubric tier.
- The dissertation's contribution shifts from "novel rubric +
  benchmark" to "country-scale agentic-LLM benchmark with cost
  surface and failure-mode taxonomy." Less methodological novelty,
  more empirical depth, more defensible against the available
  timeline.

Data-leakage caveat: ODMI publishes the `merged_responses` answers
on data.europa.eu, so the Researcher's Tavily search could in
principle find ODMI's own answer page mid-run. The mitigation is to
add the data.europa.eu Open Data Maturity sub-domain to a
deny-list during evaluation runs, and to record any swarm pair whose
source URL came from there. Tracked as Q-DASH-LEAK below.

### D23: Streamlit Cloud auto-deploys on push to `main`

**Date:** 2026-05-13.

The public dashboard at
`https://odmi-agent-swarm-f5b4cbeukwunzkuvp2tswn.streamlit.app/`
redeploys automatically whenever the `main` branch advances.
`ODMI_READ_ONLY=1` is set in the app's secrets so the Run Console,
Verifier Strategies, and Hand-marks buttons (where present) short-
circuit with a toast. Every commit to `main` that touches the
dashboard must be followed by a `git push origin main`; the deploy
takes 3–5 minutes for a full rebuild, ~30 s for an incremental
one. Verification: open the URL after a push and confirm the new
content is live before claiming the change is done.

### D24: Hard ban on ODMI publications and the EU Data Portal as evidence

**Date:** 2026-05-14.

The swarm is validated against ODMI's published `merged_responses`
(per D22). Any URL that quotes, hosts, mirrors, or summarises ODMI's
own answers therefore leaks the very signal we are trying to
predict. Eliminating this leakage is a hard requirement, not a
heuristic.

A single deny-list module (`agents/tools/blocked_domains.py`) is the
source of truth. It is enforced at five layers, defence in depth:

1. **Search.** `agents/tools/search.py` passes
   `exclude_domains=list(BLOCKED_DOMAINS)` to Tavily and appends
   `-site:<d>` clauses to every Brave query. A `_scrub_blocked()`
   pass drops any result whose URL hits the deny-list before
   returning, regardless of provider. `session_usage()` counts
   scrubbed results so dashboard observability stays honest.
2. **Fetch.** `agents/tools/fetch.py` short-circuits `fetch_text`,
   `fetch_rendered_text`, and `head_ok` for blocked URLs with
   `failure_mode="blocked_data_leakage:<reason>"`. No browser
   launch, no network call.
3. **Validator.** `agents/tools/validator.py` force-returns 0.0 for
   any blocked URL. `data.europa.eu` is removed from the default
   FR / EU trusted lists; `_looks_authoritative` no longer treats
   `*.europa.eu` as trustworthy by pattern.
4. **Prompts.** Researcher (v2) and all four Verifier strategies
   (disprove / negation / steelman / blind, all bumped to v2) carry
   an explicit hard rule: forbidden sources are `data.europa.eu`,
   `publications.europa.eu`, `op.europa.eu`, `europeandataportal.eu`,
   archive mirrors of those, and any URL containing
   `open-data-maturity`, `odmi`, `merged_responses`, or
   `odm-questionnaire`. The Researcher prompt also bans relying on
   memorised ODMI rankings or prior-year answers. Verifiers reject
   any Researcher claim citing a forbidden source with
   `rejection_reason="forbidden_odmi_source"`.
5. **Audit.** `scripts/check_data_leakage.py` scans `source_url`,
   `counter_source_url`, and `final_source_url` columns across the
   swarm tables. Exits 0 clean, 1 on any violation. Optional
   `--purge` flag deletes every pair_run row that produced a
   violation across all six swarm tables.

The blocked-path-fragment list is narrow on purpose: catching
`open-data-maturity-report` on a third-party domain is desirable;
catching every "open data" page would be over-broad. Domain
blocking is the primary defence; path fragments are a secondary
guard.

Update policy. New entries to `BLOCKED_DOMAINS` or
`BLOCKED_PATH_FRAGMENTS` require a numbered SPEC.md decision. The
list should grow as new mirrors surface; it should never shrink
without a written rationale here.

Historical contamination. The audit script flagged 30 violations on
existing rows before this decision landed (8 Researcher source_urls,
18 Verifier counter_source_urls, 4 phase2_final final_source_urls,
all pointing at `data.europa.eu`). Those rows pre-date D24 and are
not retro-active proof of a bug in the new code; they are evidence
that the leakage problem was real. The user runs
`uv run python scripts/check_data_leakage.py --purge` after
reviewing the list.

---

## Current status

**Phase:** Phase A. Swarm running end-to-end; dashboard live (local + Streamlit Cloud); ODMI ground truth loaded; ready to scale to harder questions and more countries.

### Built (verified)

- Repo structure with `agents/`, `data/`, `dashboard/`, `docs/`,
  `scripts/`, `tests/`, `evaluation/`.
- `pyproject.toml`, `.env.example`, `.gitignore`, `uv.lock`. Streamlit
  + pandas + plotly added.
- SQLite schema at `data/odmi.db` — twelve tables now: `prompt_versions`,
  `questions`, `hand_marks`, `phase1_classifications`,
  `phase2_researcher_runs`, `phase2_verifier_runs`, `phase2_adjudications`,
  `phase2_final`, `subtrio_status`, `claude_usage_log`, `model_defaults`,
  `language_confidence`. Idempotent migration via
  `scripts/migrate_dashboard_tables.py`.
- `scripts/parse_questions.py` parses the official 2025 questionnaire
  into 143 JSON records at `data/questions/odmi_2025_questions.json`.
- `agents/` — Pydantic contracts (`models.py`), shared tools
  (`tools/{db,fetch,llm,search,substring,validator}.py`), Researcher,
  Verifier (four strategies: disprove, negation, steelman, blind),
  Adjudicator, and the errors module (`RateLimitedShutdown`).
- `scripts/run_researcher.py`, `scripts/run_verifier.py`,
  `scripts/run_coordinator.py`, `scripts/dispatch_subtrios.py`,
  `scripts/cleanup_subtrios.py`. All CLI-usable standalone.
- Streamlit dashboard at `dashboard/Home.py` plus eight pages under
  `dashboard/pages/`: Run Console, Results, Questions, Strategy Lab,
  Hand-marks, Models, Costs, Prompts. Live polling via
  `st.fragment(run_every=...)`. Tested: 9/9 Playwright page loads,
  4/4 AppTest cases, end-to-end Release smoke from the UI.
- `agents/tools/llm.py` writes one `claude_usage_log` row per call
  with `context` and `subtrio_id` threaded through.
- End-to-end coordinator run on P1/FR completed: Researcher
  yes(0.72) → Verifier rejected → Adjudicator accepted_researcher.
- `tests/test_classifier.py` covers the Pydantic models for the
  legacy classifier path (kept as inert audit-trail history).
- `ground_truth` table loaded: 5,148 ODMI 2025 answers across all 36
  countries × 143 questions. Joined to every finalised pair via
  `_MATCH_STATUS_SQL` in `dashboard/lib/db.py`.
- 11 finalised swarm pairs across FR / DE / NL / RO, all matching
  ODMI 2025. Total spend ~$1.02.
- Streamlit Cloud public deploy at
  `https://odmi-agent-swarm-f5b4cbeukwunzkuvp2tswn.streamlit.app/`
  (set to public viewer access, `ODMI_READ_ONLY=1` in secrets).
- Slide deck `docs/PROGRESS_SLIDES_2026-05-13.pptx` regenerated against
  the ground-truth schema, costs in £.
- `dashboard/pages/5_Database.py` — the 5,148-pair coverage grid with
  filters and a "delete a pair's swarm rows" form.
- `db.delete_pair`, `db.pair_row_counts`, `db.coverage_grid`,
  `db.already_finalised` helpers.
- Run Console: progress strip at the top (5 metrics + a live progress
  bar for the latest batch), pre-flight duplicate detection, opt-in
  re-run-anyway checkbox.
- `scripts/dispatch_subtrios.py` accepts `--pairs QID:CC` for sparse
  dispatches; the dashboard always uses it.
- `dashboard/lib/currency.py` — USD→GBP display layer (`USD_TO_GBP=0.79`).
  Every cost display in the dashboard, the slide deck, and the runner
  CLI prints uses it.

### Not yet built

- Scale-out beyond Policy: Portal, Quality, and Impact dimensions on
  the current four-country set.
- Add Hungary and Estonia to the regular sweep (Phase B saturation).
- Verifier strategy comparison (D15/Q12): only `verifier-disprove`
  has run so far; negation, steelman, blind still to compare.
- Family-1 cost-side experiments (prompt-compressed, retrieval-tight,
  cache-hot, model-fallback). Family-3 model variants
  (Haiku / Sonnet / Opus / tiered).
- The three deliberate deferrals from the day-5 contract audit:
  resume-from-interruption, Researcher CAPTCHA / 403 detection, and
  the human-queue CSV writer (`docs/KNOWN_GAPS.md`).
- Data-leakage deny-list inside `agents/tools/search.py` for the
  evaluation cycle's data.europa.eu sub-domain (per D22).
- External-validity test against the 2024 cycle.
- `evaluation/` analysis scripts.
- Notion master page sync with the new state.

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
- **Q11:** Resolved. Substring check uses normalised match: lowercase,
  collapse whitespace, strip punctuation. Strict literal match was
  considered and rejected as brittle.
- **Q12:** Which Verifier prompt strategy do we run by default in the
  swarm? Empirical question, answered by the comparison experiment in
  D15. Default to `verifier-disprove` until measurement shows otherwise.
- **Q13:** Adjudicator confidence threshold for picking a winner vs
  escalating to human. Provisional value 0.6 (per D16). Re-calibrate
  after the Adjudicator has fired on at least 5 real cases.
- **Q14:** Verifier prompt strategy comparison needs an "injected
  hallucination" arm. We need cases where the Researcher is known to
  be wrong, to measure the catch rate honestly. Either deliberately
  feed the Verifier a fabricated Researcher claim, or hand-mark known
  bad answers from a pilot. Decide before the comparison runs.
- **Q15:** Model assignment in the tiered condition (per D18). First
  candidate: Researcher=Haiku-4.5 (cheap retrieval and drafting),
  Verifier=Sonnet-4.6 (adversarial reasoning where the marginal cost
  matters most), Adjudicator=Opus-4.6 (premium reasoning, fires
  rarely). Validate after the pure-tier conditions run.

---

## Change log

| Date | Change |
|---|---|
| 2026-05-14 (evening) | D24 added: hard ban on ODMI publications and the EU Data Portal as evidence. New `agents/tools/blocked_domains.py` deny-list (12 domains, 7 path fragments). Enforced at five layers: Tavily `exclude_domains` + Brave `-site:` + post-filter scrub in `search.py`; refusal in `fetch_text`/`fetch_rendered_text`/`head_ok`; 0.0 score in `validator.trust_score`; explicit forbidden-sources rule baked into Researcher v2 prompt and all four Verifier v2 prompts (disprove / negation / steelman / blind); audit script `scripts/check_data_leakage.py` with `--purge`. New `tests/test_blocked_domains.py` (30 cases, passing). `data.europa.eu` removed from `_DEFAULT_TRUSTED` and from the `_looks_authoritative` pattern. Audit on existing DB flagged 30 historical violations (8 Researcher source_urls, 18 Verifier counter_source_urls, 4 phase2_final), all pointing at `data.europa.eu`; user runs `--purge` after review. |
| 2026-05-14 (afternoon) | Coordinator resume-on-partial. Since CLIProxyAPI strips Anthropic's rate-limit headers, batches dying mid-flight is unavoidable when the Claude Max wall hits. The Coordinator now: at start of each pair, looks for a prior subtrio_status row that has a `phase2_researcher_runs` entry (retry_count=0) but no `phase2_final`, and is either orphaned, interrupted_rate_limit, failed, or older than the resume freshness window (default 60 minutes). If one exists, marks the prior subtrio_status as `stage='superseded'`, loads the prior Researcher output back into a ResearcherOutput, and skips the Researcher call on the new attempt's first iteration — going straight to the Verifier. Retries 1+ run Researcher normally. New helper functions: `_find_resumable_researcher`, `_mark_superseded`, `_researcher_output_from_row`. Partial rows in the three phase2_* tables remain in place but are not visible as completed because the Results/Database/Home surfaces all key off `phase2_final` (only written on completion). Cost / audit semantics: the resumed Researcher's cost stays in claude_usage_log under the prior subtrio_id; the new subtrio only spends on Verifier and Adjudicator. |
| 2026-05-14 (am) | Search-side resilience pass. `scripts/probe_ratelimit.py` confirms CLIProxyAPI strips `anthropic-ratelimit-*` headers, so Claude Max remaining-capacity is not readable through the proxy; the dashboard's £ soft limit stays as a guessed-equivalent figure for now (revisit if we bypass the proxy). `agents/tools/search.py` rewritten with a Tavily → Brave Search fallback that triggers on `UsageLimitExceededError` and sticks to Brave for the rest of the session; `session_usage()` exposes the per-provider counts. `agents/tools/trusted_domains.py` + JSON files for FR / DE / NL / RO / HU / EE list the per-country authoritative domains (national portal + key government sites, deliberately excluding data.europa.eu per D22's leakage mitigation). Researcher now searches narrowed to those domains first and widens automatically when the narrow search returns zero results. `.env.example` adds `BRAVE_SEARCH_API_KEY`. |
| 2026-05-13 (late evening) | Follow-ups after D22. New `dashboard/pages/5_Database.py` shows all 5,148 ODMI ground-truth pairs joined with the latest swarm answer; filters by country / dimension / coverage state / free-text; deletes one pair's swarm rows from the UI. New `db.delete_pair` / `pair_row_counts` / `coverage_grid` helpers. Each Results card grew a `🗑 Delete all swarm rows for this pair` expander with confirmation. Run Console launcher now refuses duplicates by default (with a checkbox to opt-in), and the dispatcher gained a `--pairs QID:CC` CLI argument so sparse sets flow through. Run Console gained a top-of-page progress strip (5 metrics + an `st.progress` bar tracking the latest batch). Currency switched to GBP everywhere it's displayed (dashboard, slides, CLI prints): new `dashboard/lib/currency.py` with `USD_TO_GBP=0.79` and `format_gbp()`. Soft-limit slider accepts £ in; converts to USD for the dispatcher under the hood. `estimated_cost_usd` column name unchanged (the underlying unit is still USD). |
| 2026-05-13 (evening) | D22 added: ODMI ground truth supersedes hand-marks. New `ground_truth` SQLite table loaded from `merged_responses` (5,148 rows, 36 countries × 143 questions) via `scripts/load_ground_truth.py`. `dashboard/lib/db.py:_MATCH_STATUS_SQL` classifies each finalised pair against ODMI's recorded answer; Results Cards now show ODMI's answer next to the swarm's with a match badge; Home page KPI strip and country chart rebuild on accuracy vs ODMI rather than terminal_status; Hand-marks page removed from sidebar; slide deck regenerated against the new schema. D23 added: Streamlit Cloud auto-deploys on push to `main`, dashboard verifier needed after every dashboard-touching push. METHODOLOGY.md Section 6 rewritten; Sections 3 and 4 retained as historical record with a header note. RQ2 reframed to ODMI dimensions. Sample sizes for hand-marking (D10) are no longer load-bearing. |
| 2026-05-13 | Coordinator follow-ups. `run_coordinator.py --dry-run` and `--walkthrough` flags added. Dry-run gates the five `phase2_*` and `subtrio_status` writes; `claude_usage_log` deliberately stays on so real token spend keeps counting toward the rolling 5-h budget. Smoke test on P1/FR passed: zero new rows in gated tables, six usage-log rows recorded. `docs/KNOWN_GAPS.md` added: documents the three deferred failure modes (resume / D22-D25, CAPTCHA detection, human-queue CSV) with trigger conditions and build sketches; indexed from SPEC.md's "Where to look for what" table. |
| 2026-05-12 | D19 (Streamlit dashboard), D20 (rolling-window credit policy), D21 (three new schema tables: subtrio_status, claude_usage_log, model_defaults) added. Q-DASH-1..4 opened. Phase 2 complete: Verifier with four strategies built and smoke-tested. Phase 3 complete: Coordinator (run_coordinator.py), Adjudicator (agents/adjudicator.py), dispatcher (dispatch_subtrios.py), and cleanup_subtrios.py written. End-to-end P1/FR coordinator pass succeeded with all six LLM calls writing claude_usage_log rows carrying subtrio_id. Streamlit dashboard built (9 pages) and tested: 9/9 Playwright page loads clean, 4/4 AppTest cases pass, end-to-end Release from the UI spawns a real dispatcher subprocess and writes the subtrio_status row. |
| 2026-05-11 (late evening) | D18 (model variants Haiku / Sonnet / Opus as a third optimisation family). Q15 opened (model assignment in the tiered combination). Foundation code landed: SQLite migrated to nine tables, Pydantic contracts, shared tools (search, fetch, substring, validator, LLM wrapper), Researcher v1 prompt and orchestration, run_researcher.py with --walkthrough. First end-to-end dry run on P1/FR succeeded: answer "yes" matching the hand-mark, $0.041 cost, 23s wall-clock, source on data.gouv.fr (domain trust 1.0). |
| 2026-05-11 (evening) | D15 (Verifier prompt strategies as experimental condition), D16 (Adjudicator path at max retries), D17 (decisions revisited with real data). Q11 resolved (normalised substring match). Q12 (which Verifier strategy by default), Q13 (Adjudicator threshold), Q14 (injected-hallucination arm) opened. AGENT_DESIGN.md updated: Verifier reframed as cognitive flip, deny-list dropped, Section 4.10 added with four prompt strategies; Coordinator Section 5.11 adds the Adjudicator. METHODOLOGY.md updated with Verifier strategy comparison as Family 2 of optimisation experiments. |
| 2026-05-11 (pm) | D12 (optimisation as first-class dimension), D13 (2025 ground truth, 2024 held-out), D14 (22 May = slide deck not report). Q5 resolved. Q6 opened. RQ5 added to METHODOLOGY. |
| 2026-05-11 (am) | Project state reverse-engineered after five-week dormancy. Stale ODMI_Project_Knowledge.md / ODMI_Project_Setup.md deleted. CLAUDE.md, SPEC.md, METHODOLOGY.md, PROJECT_LOG.md rewritten. D8, D9, D10, D11 added. Option 3 (rubric as analytical lens) locked in. Hand-marks workspace created. First git commit on `main`. |
| 2026-04-01 | SPEC.md first created (now superseded). Confirmed CLIProxyAPI (D1) and SQLite (D2). Project moved from `~/Projects` to `~/Desktop/Msc Project`. |
| 2026-03-27 | Session 1: repo scaffolding, classifier v1, Supabase schema (since dropped). |

---

## Where to look for what

| Question | Where |
|---|---|
| What is the evaluation methodology? | `docs/METHODOLOGY.md` (Section 6). |
| Where is the ODMI ground truth? | SQLite table `ground_truth`, loaded from `data/questions/2025_odm_questionnaire_data.xlsx` (sheet `merged_responses`) by `scripts/load_ground_truth.py`. |
| How is "match vs ODMI" defined? | `_MATCH_STATUS_SQL` in `dashboard/lib/db.py`. |
| Why did we make decision X? | This file (`docs/SPEC.md`), search for "Dx". |
| What did I do last session? | `docs/PROJECT_LOG.md`. |
| What did the supervisor say? | Notion supervision log. |
| Where are the parsed questions? | `data/questions/odmi_2025_questions.json`. |
| Where is the live dashboard? | `https://odmi-agent-swarm-f5b4cbeukwunzkuvp2tswn.streamlit.app/` (public, read-only). |
| Coverage of every pair / delete a bad result? | Sidebar → Database. |
| How are costs displayed? | All £ via `dashboard/lib/currency.py` (rate `USD_TO_GBP=0.79`). Underlying column is still `estimated_cost_usd`. |
| Where is the prelim draft? | `docs/REPORT_PRELIM.md`. |
| Where are citations? | `docs/references.bib`. |
| Known gaps and anticipated failure modes? | `docs/KNOWN_GAPS.md`. |
| Hand-mark CSVs (historical, superseded by D22)? | `data/hand_marks/`. |
