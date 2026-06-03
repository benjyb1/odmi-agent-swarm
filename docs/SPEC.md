# ODMI Agent Swarm — Living Spec

Last updated: 2026-05-25

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

### D3: Plain Python state machine for the Phase 2 agent swarm

**Amended 2026-06-02.** The original D3 specified a graph-orchestration
framework for the Coordinator → Researcher → Verifier pattern, on the
reasoning that conditional edges express accept/reject/retry logic that plain
chains cannot handle neatly. The implementation deviated: the Coordinator is a
plain Python state machine (`scripts/run_coordinator.py`). The retry loop is
linear, and a graph runtime added debugging overhead with no behavioural
benefit at this scale. The deviation is recorded in the `run_coordinator.py`
file header and in `docs/PROJECT_LOG.md`.

### D4: France-first baseline

Phase A runs against France only. France scored 100% on the 2024 ODMI, speaks
a high-resource language, and has a mature open data portal (data.gouv.fr).
If the pipeline fails on France, the problem is in the pipeline, not in the
country's data infrastructure.

### D5: Prompt versioning in the database

Every classification and every agent response links to the exact prompt version
that produced it via `prompt_versions.id`. Without this, score changes cannot
be attributed to prompt changes versus model behaviour.

### D6 / D8 / D9 / D10: Answerability rubric and hand-marking protocol — superseded by D22

**Superseded 2026-05-13.** D6 defined a three-dimension answerability rubric
(Evidence Accessibility, Answer Determinism, Source Complexity, composite 0–9).
D8 locked it as an analytical lens rather than a runtime classifier. D9 required
hand-marks to be git-committed before any swarm run on the same pair. D10 set
sample size at 30–50 questions stratified across ODMI dimensions.

All four are inert. D22 replaced the hand-mark evaluation pathway with direct
comparison against ODMI's published `merged_responses` (5,148 rows). The rubric
dimensions are retained in `docs/METHODOLOGY.md` as historical context only.

### D7: Phased country rollout

- **Phase A:** France only (controlled baseline).
- **Phase B:** Six countries across a 2×3 wealth × maturity matrix: France,
  Germany, Netherlands, Romania, Hungary, Estonia.
- **Phase C:** All 36 EU countries (stretch goal).

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

### D25: Every batch auto-publishes the DB to `origin/main`

**Date:** 2026-05-15.

Per D23 the Streamlit Cloud app rebuilds on every push to `main`, but
the deploy still serves whatever copy of `data/odmi.db` was in the
last push. To close that gap, `dispatch_subtrios.dispatch()` now calls
`publish_to_main()` after the threads join. The helper checkpoints the
SQLite WAL into the main `.db` file, stages it, commits with an
auto-generated message (`Batch: P1,P2 x DE,FR,NL (4/5 ok)`), and runs
`git push origin main`. The public dashboard then redeploys inside
~30 s with the new rows.

Safeguards:
- Skips silently if `ODMI_SKIP_AUTO_PUBLISH=1` is set. Use this for
  tests and for local-only exploration where a push would be noise.
- Skips if the current branch is not `main`. Worktree branches are
  developer scratch and do not deploy.
- Skips if `data/odmi.db` has not changed vs `HEAD`. No empty commits.
- Push failures are logged with `[publish]` prefix and do not raise.
  The next successful batch sweeps the backlog.

Trade-offs. Each commit re-ships ~8 MB of binary DB, so the repo will
grow ~400 MB per 50 batches. Acceptable through the prelim; revisit
with git LFS if push latency becomes a problem. The alternative
(uncommitted DB on the deploy) would mean the public page silently
falls behind every local run, which is what prompted this decision.

The hook lives at the tail of `dispatch()` rather than the CLI entry
point so that both `uv run python scripts/dispatch_subtrios.py` and
the local dashboard's Run Console publish on the same code path.

### D26: Per-call search-provider telemetry on `phase2_researcher_runs`

**Date:** 2026-05-25.

The Researcher's search wrapper (`agents/tools/search.py`) routes
queries through Tavily first and falls back to Brave if Tavily errors
or hits its quota. Until D26, the only signal we had was a
module-level `session_usage()` counter that died with the subprocess.
That made provider-conditioned analysis impossible after the fact: we
could not say "Tavily reached 92% match on Policy questions; Brave
reached 68%" because we did not know which provider served which pair.

D26 adds an optional `on_call` observer to `search()` and
`search_many()`. The Researcher passes a list-append callback so every
provider invocation emits one record:

```json
{"provider": "tavily", "ms": 245, "results": 5, "ok": true, "error": null}
```

The Researcher collects the list across both the narrow-trusted and
wide-fallback search passes, and `run_coordinator.py` serialises it
into the new `phase2_researcher_runs.search_provider_calls` column
(TEXT, JSON list, NULL on legacy rows). Old rows pre-2026-05-25 stay
NULL and are excluded from provider-conditioned analyses.

What this enables:
- Provider match-rate / latency / cost cross-tabs in the dashboard.
- A clean Tavily-vs-Brave comparison in the dissertation's
  optimisation chapter, replacing what would otherwise be a hand-wave
  about "the search backend was sometimes Brave".
- A diagnostic for the 2026-05-25 incident where Brave returned 422
  Unprocessable Entity on long-operator queries: the row's `ok=false`
  + `error` payload would have surfaced the failure mode in the
  dashboard the moment the first batch ran, instead of presenting as
  silent `0/81 ok` in the commit message.

Same-day side fix: the Brave query builder previously appended a
`-site:` clause for every entry in `BLOCKED_DOMAINS`, which pushed
queries past Brave's per-query operator limit and returned 422 for
every Researcher call once Tavily was exhausted. The deny-list is now
enforced solely by the `_scrub_blocked` post-filter and
`include_domains` is capped at eight `site:` clauses. The leakage
guard is unchanged.

### D27: Experiment isolation via `experiment_id` tag and the `experiments` registry

**Date:** 2026-05-25.

Ablation runs and condition comparisons must not pollute the
dissertation's headline numbers. D27 introduces a tag-based isolation
scheme rather than a parallel set of tables, on the principle that
schema duplication drifts over time and is harder to audit.

Changes:

- New table `experiments(experiment_id, name, description,
  conditions, created_at)`. One row per planned experiment. The
  `conditions` column holds a JSON list describing each condition's
  overrides (label, models, strategy, prompt_version_id).
- New nullable column `experiment_id` on `subtrio_status`,
  `phase2_final`, `phase2_researcher_runs`, `phase2_verifier_runs`,
  and `phase2_adjudications`. NULL identifies a main-results run.
- `dispatch_subtrios.dispatch()` and `run_coordinator.py` accept
  `--experiment-id` and `--condition-label`. Children stamp every
  inserted row with the tag via a module-level context variable
  (mirrors the existing `_dry_run` pattern; no change to the eight
  internal call sites).
- `dashboard/lib/db.py` adds a `MAIN_RUNS_FILTER` constant and
  applies it to the headline queries (`result_cards`,
  `country_outcome_counts`, `accuracy_summary`, `all_pair_status`,
  `already_finalised`). The Experimentation page (Phase 2, not yet
  built) will do the opposite, filtering to a single `experiment_id`.

`claude_usage_log.experiment_id` was deliberately omitted to keep the
hot LLM-call path untouched. Cost rollups by experiment can JOIN
through `subtrio_id` → `subtrio_status.experiment_id` when needed.

Phase 1 (this commit) covers schema + dispatcher/coordinator plumbing
+ defensive headline filters. Phase 2 builds the Streamlit
Experimentation page. Phase 3 adds cross-experiment comparison views.

Smoke test on 2026-05-25 confirmed end-to-end tagging:
`smoketest-001` propagated correctly from CLI through to the
`subtrio_status.experiment_id` column. The subprocess could not
finalise because both Tavily and Brave quotas were exhausted, but
the search-provider telemetry captured both failures cleanly,
demonstrating D26 + D27 working together.

### D28: Per-shape answer schema; forced-collapse rows hard-deleted

**Date:** 2026-05-26.

Until D28 every agent in the trio returned `answer: Literal["yes",
"no", "other", "not_applicable"]`. That fits the 121 binary
questions in the ODMI 2025 questionnaire but fails on the other 22,
whose actual answer space is a percentage band (`>90%` … `<10%`),
an ordinal magnitude (`all` / `majority` / `half` / `few` / `none`),
a count band (`yes, 6-9` / `1-4`), a small categorical
(`top-down` / `bottom-up` / `hybrid`), or a fixed timing bucket
(`within one day` / `within one week` …). On those questions the
swarm was forced to collapse to `other`, which discards the
discrimination ODMI actually scores on: a `71-90%` answer scores 20,
`10-30%` scores 2, and both would land in the same bucket today.

Decision: replace the flat literal with a discriminated union over
five answer shapes. Each row in `questions` gains a new
`answer_shape` column (and an `allowed_answers` JSON column where
the shape's allowed values vary per question). Researcher, Verifier
and Adjudicator outputs are validated against the shape stored on
the question.

The five shapes:

1. `binary`: `yes` / `no` / `other` / `not_applicable`. The current
   literal, kept verbatim.
2. `percentage_band`: parameterised, each question carries its own
   list of band labels (Q12 has six, Q2 has eight).
3. `ordinal_magnitude`: `all` / `the majority` / `approximately
   half` / `few` / `none` (plus optional `not_applicable`). PT32,
   PT37, P16, Q2 family.
4. `count_band`: parameterised list per question (P29's
   `yes, >9` / `6-9` / `3-5` / `1-2` / `no`, Q13's `1-4` / `5-10` /
   `>10`).
5. `categorical`: small fixed enum per question (P14's three-way
   model classifier, Q3's four-way timing bucket).

The new field also lets the Verifier prompt branch: for ordinal or
band shapes the "find counter-evidence" rule becomes "find evidence
the right band is one step lower" rather than "find evidence for
the opposite literal", which is a sharper instruction on these
questions than the current prompt can express.

Cleanup of in-flight evaluation rows. The DB held 148 finalised
pairs at the moment of this decision. 41 of them sat on
`final_answer = 'other'`, split into two groups:

- **19 forced collapses**, all on questions whose new shape is not
  `binary`. The swarm had no means to express the right answer on
  these. They are not honest evaluation signal and were
  hard-deleted (along with their 39 Researcher rows, 39 Verifier
  rows, 3 Adjudication rows, and 19 `subtrio_status` rows). A
  timestamped backup of the pre-deletion DB sits at
  `data/odmi.db.bak-pre-D28-20260526T100409Z`. Once the per-shape
  refactor lands these pairs can be re-dispatched cleanly.
- **22 honest "couldn't tell" outcomes**, on questions where ODMI's
  rubric is yes/no only. The swarm had `yes` and `no` on offer and
  picked `other` anyway (D24 forbidden-source refusals, low
  confidence, or honest uncertainty). These are real evaluation
  signal and stay in place.

Implementation rolled out across two commits (Phase 1: cleanup) and
five staged commits (Phase 2A through 2E), all landed 2026-05-26.

Phase 2A — schema and classification (commit `d631c30`). Adds
`answer_shape` and `allowed_answers` columns on `questions`. The
classifier in `scripts/migrate_d28_shapes.py` parses
`response_scoring` and tags every row: 124 binary, 12
percentage_band, 3 ordinal_magnitude, 2 count_band, 2 categorical.
Adds the `inconclusive` literal to `AnswerLiteral`. Migrates the
22 `phase2_final.other` rows on yes/no-only rubrics (and their 38
researcher / 46 verifier upstream rows) to `inconclusive`. Tests
in `tests/test_d28_classifier.py` lock in the classification rules.

Phase 2B — Pydantic loosening and shape-aware prompts (commit
`21255bb`). `answer` / `verifier_answer` / `adjudicator_answer`
become free-text strings (validated at runtime, not at the
Pydantic boundary). `ResearcherInput` / `VerifierInput` /
`AdjudicatorInput` carry `answer_shape` and `allowed_answers`.
New module `agents/tools/answer_shapes.py` (`load_question_shape`,
`is_valid_answer`, `normalise_answer`, `is_band_shape`,
`band_distance`). Researcher prompt bumped to V3; all four
Verifier strategies plus the adversarial query-gen bumped to V3
/ V2; Adjudicator V3. Each runner now post-validates the LLM's
emitted label against the question's allowed set and records a
note when normalised. `tests/test_answer_shapes.py` (13 cases).

Phase 2C — `near_match` SQL (commit `0d1a6c2`). `_MATCH_STATUS_SQL`
gains an EXISTS subquery over `questions` and `json_each` that
flags adjacent-band misses on the three ordered shapes as
`near_match` rather than `differ`. `accuracy_summary()` returns
both `accuracy` (exact) and `accuracy_within_one_band`.
`country_outcome_counts()` adds the new outcome label. Nine
integration tests in `tests/test_match_status_near_match.py`.

Phase 2D — dashboard render (commit `5aae4f0`). Match badge
palette gains a yellow "Adjacent band (D28)" tile. Results,
Database, Analytics, and Home now surface the new state and the
within-one-band figure. Questions page shows the per-question
`Shape` column.

Phase 2E — tests + smoke-test (this commit). Thirteen integration
tests in `tests/test_shape_aware_prompts.py` confirm the
allowed-answer list propagates from the DB through the input
models into the user messages seen by all three agents. Smoke
dispatch of Q12:FR (a percentage_band pair) booted cleanly: the
subtrio_status row was written, the Coordinator reached the
search stage. Phase 3 (the full re-dispatch of the 19
forced-collapse pairs plus broadening to all 22 non-binary
questions across FR / DE / NL / RO) is deferred: both Tavily and
Brave search quotas are currently exhausted (per the May 25
incident logged on D26 / D27). The shape-aware pipeline is ready;
it re-runs against the new schema once D29 (DIY-Tavily) lands in
June.

### D29: DIY search pipeline corrected; evaluated against Tavily by LLM adjudication

**Date:** 2026-06-01.

The DIY-Tavily pipeline (Serper SERP → fetch → trafilatura → Claude
snippet-pick) was underperforming: the layer-2 snippet-quality fixture sat at
31%. Root cause, proven by `evaluation/diagnose_extraction_ceiling.py`: the
layers ran in the wrong order. `fetch_text` stripped HTML tags and truncated to
4000 chars BEFORE trafilatura ran, so the picker saw ~4000 chars of tag-stripped
script / nav / cookie soup, and trafilatura (which needs the DOM) was a no-op via
the `is_html=False` short-circuit. The accepted evidence quote was present in the
picker's input only 38% of the time; running trafilatura on the RAW HTML lifts
that ceiling to 78%.

Fix: new `fetch_html` / `fetch_rendered_html` return raw HTML (generous cap, tags
intact); `search_diy._fetch_and_clean` runs trafilatura on the raw HTML, then caps
the clean text; picker `PAGE_TEXT_CAP` raised 8000 → 16000 (snippet-picker prompt
v2). Snippet quality 31% → 58%, and the layer-2 test now scores overlap with the
project's own `substring.normalise` (the Verifier's real acceptance standard)
rather than a harsher raw byte match.

Evaluation methodology: DIY need not reproduce Tavily's exact passage, so DIY is
compared to Tavily by a higher-order Opus adjudicator
(`agents/prompts/search_adjudicator.py`, `agents/tools/search_adjudicator.py`,
prompt v2). For each (question, country) pair the judge sees the ODMI gold answer
and both systems' evidence BLIND (System A / System B) and returns
winner / tie / both_fail. It runs position-swapped to control position bias; a
flip nets to a tie. Harness: `evaluation/diy_vs_tavily.py`; headline metric is
"DIY not worse than Tavily" on decisive (non-both_fail) pairs.

Result (36 dimension-stratified FR pairs, vs Tavily basic): DIY 12 wins, 2 ties,
4 losses, 18 both_fail. On the 18 decisive pairs DIY is not worse 78% of the time
and out-wins Tavily 3:1; DIY leads on every answerable dimension. This meets the
"≥80% as good as Tavily" target within the noise of a small sample (n=18) and a
judge with 67% position consistency.

Key finding, separate from the ratio: half the questions, and all nine Quality
questions in the sample, are unanswerable from the open web because the gold
answer is an MQA metric on the deny-listed data.europa.eu (D24) or a
questionnaire self-report. This bounds the swarm's ceiling on those questions
regardless of search provider.

Robustness fixes the eval surfaced: `_extract_json` now recovers JSON wrapped in
fences with trailing prose (the Opus judge did exactly this); `pick_snippet`
degrades to an empty result instead of crashing when the model emits invalid JSON
(unescaped inner quotes). Also fixed a latent `run_id` → `pair_run_id` join bug in
`build_snippet_fixtures.py` (it had mislabelled every fixture as Q6/FR).

Limitations: n=18 decisive, all France (question-diverse, country-skewed);
compared against Tavily's default (basic) tier, which is what the swarm uses;
judge position-consistency 67%. Chunk+rerank (research Tier-1: split the clean
text into ~500-char windows and rerank against the query, as Tavily advanced
does) is the lever to push past 80% unambiguously; deferred as diminishing-return
against the sample noise and the dominant deny-list ceiling.

### D35: `inconclusive` is an abstention, not a terminal answer

**Date:** 2026-06-02.

The D34 validation showed the gate fix alone recovered no pairs. With the false
rejection gone, the Researcher answered `inconclusive` at R1 and the Verifier
accepted the abstention, so the loop terminated before any retry. An
`inconclusive` is not a result; it means the agent could not determine the
answer. Treating it as a verified answer ended the search early.

The coordinator now treats `inconclusive` as a retry trigger, bounded by the
existing 3-retry budget (no new cap). On a non-final attempt an inconclusive
answer short-circuits to a retry before the Verifier runs, which saves the
Verifier call, carrying an abstention note plus the D33 query divergence so the
retry searches differently. If the budget is exhausted while still inconclusive,
the pair escalates to the Adjudicator; the Verifier still runs on the final
attempt so the Adjudicator has material to weigh. Two pure helpers,
`_is_abstention` and `_should_accept_verifier_pass`, carry the rule and are
unit-tested. `not_applicable` is a valid determination and is untouched.

This deliberately does not keep a "best answer" across retries. An answer the
Verifier refuted must not be passed through, or the verification step means
nothing. A refuted-but-correct answer has a legitimate home in the Adjudicator
(D32), which is the only place a Verifier refutation is overturned.

Receipt (forward validation, experiment_id `inconc_retry_v1`, on top of D34): of
the first three gate-collapse pairs re-run before the run was interrupted, all
three recovered from `inconclusive` to the correct `yes` (I11 FR at retry 1, I5
FR at retry 1, I8-a FR at retry 2), against 0 of 11 under the gate fix alone. The
Researcher retries past its R1 abstention and the D34 gate accepts the faithful
`yes`. Full re-run of the 15-pair set pending. 368 non-live tests passing.

### D34: Verification gate checks the quote against retrieved snippets, not a live re-fetch

**Date:** 2026-06-02.

The Verifier's substring gate re-fetched the cited URL at verify time and checked
the Researcher's evidence_quote against the live page. It failed 67% of the time
(179 of 266 main-run checks). Two artefacts compounded: the cited page often 403s
or has drifted, and the Researcher never read the full page anyway. It reads
search snippets (about 300 chars each), so a snippet-derived quote is rarely a
verbatim substring of the live HTML. The gate was rejecting on a rematch
artefact, not on whether the quote was faithful to the evidence.

The gate now checks the quote against the snippets the Researcher actually read.
The Researcher's `search_results` snippets are persisted on
`phase2_researcher_runs` (new `search_snippets` column, `migrate_search_snippets.py`)
and passed to the Verifier via `VerifierInput.researcher_snippets`;
`_run_substring_check` matches the quote against that corpus and does no live
fetch. The live-fetch path is kept only as a fallback when no snippets are
supplied (catalogue-computed answers). This preserves the anti-hallucination
property exactly: a quote absent from what the Researcher read still fails. It
changes the claim the gate makes from "this quote is on the live web right now"
(which the re-fetch could not reliably establish) to "this quote is faithful to
the evidence the Researcher retrieved", which is the gate's actual job. Live
reachability is recorded separately by the Researcher's head_ok check.

Snippet persistence also closes a reproducibility hole: the fetch cache held
about 3% of what main runs read, so gate decisions could not be replayed from
logs. Snippets are now stored per run.

Receipt (forward validation, experiment_id `gatefix_v1`, 15 gate-collapse and
found-then-lost pairs re-run): the substring gate's pass rate rose from 33% to
88% (15 pass / 2 fail), so the false rejections are gone. But only 2 of 15 pairs
finalised as match, and both reached `yes` because the Researcher happened to
answer `yes` at R1, not via the Adjudicator (no pair went to adjudication). The
fix is necessary, not sufficient. With the false rejection removed, the
Researcher answers `inconclusive` at R1 (confidence 0.10 to 0.35) and the
Verifier accepts the abstention as a pass, terminating before any retry. The
binding constraint has moved from the gate to the Verifier accepting
`inconclusive` with no retry floor. The broken gate had been forcing retries by
failing, and some of those retries reached `yes`; removing it removed the forced
exploration. The next fix is to treat `inconclusive` as keep-trying rather than a
terminal pass, plus a minimum-retry floor. 335 non-live tests passing.

### D32: Finalisation uses the Adjudicator's own answer, not the last Researcher output

**Date:** 2026-06-02.

A failure-mode analysis of the 43 finalised pairs that disagree with ODMI ground
truth found that finalisation was discarding correct answers. When the
Adjudicator resolved a deadlock, `coordinate` rebuilt the final answer from the
verdict label rather than reading the answer the Adjudicator had already
committed to. On `researcher_correct` it took `researcher_outputs[-1]`, the last
attempt, which after a decay to `inconclusive` was inconclusive; on
`verifier_correct` it synthesised an answer from the Verifier's counter-evidence.
The populated `adjudicator_answer` field was used only on the `neither` branch.

The Adjudicator records its authoritative answer in `adjudicator_answer`, with
`chosen_source_url` and `chosen_evidence_quote`, for every resolved verdict (its
prompt requires them). The verdict label is attribution; the answer field is the
answer. Finalisation now trusts it. The three resolved verdicts
(`researcher_correct` / `verifier_correct` / `neither`) share one path that
builds the final output from the Adjudicator's fields; only `escalate_human` (or
an Adjudicator failure) keeps the last Researcher output. The logic is extracted
into a pure helper, `_finalise_after_adjudication`, and unit-tested in isolation.

Receipt: replayed against the stored rows, four pairs flip from `differ` to
`match` with no re-run (P26-b FR, PT14 FR, I16 EE, I17 EE), each an Adjudicator
`yes` that finalisation had overwritten with `inconclusive`. The remaining
found-then-lost losses need the verification-gate fix, which is separate and not
done here. New `tests/test_finalise_after_adjudication.py`.

### D33: Retry queries are forced to diverge

**Date:** 2026-06-02.

The Researcher's query generator received the same input on every retry (country,
portal, question), so it reissued near-identical or byte-identical queries and the
loop re-read the same pages. Of 68 retried pairs, 41 never changed their answer
across rounds. The Verifier already produces a `suggested_search_query` on
rejection, but nothing consumed it at the query-generation step.

The query generator now sees, on a retry, the Verifier's rejection reason, its
suggested query, and the list of queries already tried, with an instruction to
generate different ones (`_QUERY_GEN_VERSION` 1 to 2). `ResearcherInput` carries a
new `previous_search_queries` list; the coordinator accumulates every query run
across attempts and passes it on the next build. The first-attempt message is
unchanged, so non-retried runs behave exactly as before.

This is a deliberately small lever. The same failure-mode analysis showed that
divergent retries address only about six pairs; the dominant losses were the
finalisation bug (D32) and the verification gate, not search repetition. It is
kept because the searches did repeat and the Verifier's suggestion was going
unused, closer to a latent defect than a design choice. New
`tests/test_query_gen_divergence.py`.

### D31: Search knobs are experiment conditions

**Date:** 2026-06-01.

The search provider and its cost knobs were hard-coded (provider "auto", 5
results per query, up to 3 generated queries). They are now threaded end to end
(`dispatch_subtrios` → `run_coordinator` → `coordinate` → `run_researcher` /
`run_verifier` → `search_many`) as `--provider`, `--max-results-per-query`, and
`--num-queries`, and exposed in the Run Console launch form next to
experiment_id / condition_label. Defaults are unchanged, so main runs behave
exactly as before.

This makes the DIY cost/quality trade-off runnable as a tagged experiment.
Conditions hold provider=diy, the models, the strategy, and the pair set
constant and vary only the knobs:

- `diy_full`: 3 queries x 5 results (current default).
- `diy_lean`: 2 queries x 3 results.
- `diy_q3r3`: 3 queries x 3 results, to isolate which knob carries the cost.

Per-condition metrics: accuracy against ODMI ground truth (the existing
`_MATCH_STATUS_SQL`), and Claude calls / tokens / cost / retry-count per pair
from `claude_usage_log`. The confound to watch is retries. Leaner search can
fail more often and trigger another full Researcher + Verifier round, so the
cost metric is total calls per pair, not per search; a cheaper per-search
config can end up more expensive end to end. Analysis groups finalised pairs by
condition_label (the existing Analytics grouping). The experiment is defined and
runnable but not yet run.

### D30: Deterministic catalogue-metrics tool for the computed Quality questions

**Date:** 2026-06-02.

A subset of ODMI Quality questions cannot be answered by web search. They ask
for a proportion of the national catalogue, for example "what percentage of
metadata uses DCAT-AP recommended classes" (Q17) or "what share of datasets
carry licensing information" (Q12). These are computed statistics, not facts
stated on any page. The one public source that publishes them is the EU
Metadata Quality Assessment (MQA) on data.europa.eu, which is deny-listed under
D24 because it is also where ODMI derives its own answers. So the swarm
abstained (`inconclusive`) and scored about 47% on Quality.

The fix is a deterministic Python tool (`agents/tools/catalogue/`) that harvests
each country's live catalogue metadata and computes the metric ourselves,
independently of the MQA. The model does not run the computation; it only picks
the metric and reads the result, so token cost is near zero.

**Scope.** The shape filter `answer_shape IN ('percentage_band','count_band')`
returns 14 questions. Nine are computed in v1: Q12, Q13, Q16, Q17, Q18, Q21,
Q22, Q25, Q27. Q26, Q28 and Q29 are flagged ambiguous in
`docs/CATALOGUE_METRICS.md` with proposed interpretations, awaiting sign-off.
P29 (annual events) and Q2 (a harvesting-workflow self-report) are excluded as
not catalogue-derivable. The full question to metric mapping is in
`docs/CATALOGUE_METRICS.md`.

**Per-country stacks (discovery, verified live 2026-06-02, national portals
only, no data.europa.eu).**

| CC | Portal | Stack | National DCAT-AP RDF | Route chosen | ~Datasets |
|----|--------|-------|----------------------|--------------|-----------|
| FR | data.gouv.fr | udata 16.5 | yes (`/api/1/site/catalog.ttl`) | dcat_rdf | 73,734 |
| DE | ckan.govdata.de | CKAN 2.10 + dcatde | yes (`/catalog.ttl?page=N`) | dcat_rdf | 151,289 |
| RO | data.gov.ro | CKAN 2.8.3 | yes (`/catalog.xml?page=N`) | dcat_rdf | ~4,800 |
| HU | kozadatportal.hu | CKAN 2.9.7 | yes, but no dct:license in it | ckan_json | 2,282 |
| NL | data.overheid.nl | CKAN 2.8 DONL | no (404 on all RDF paths) | ckan_json | ~20,800 |
| EE | andmed.eesti.ee | custom NestJS | no (SPA only) | estonia_json | 5,708 |

The common path is the national DCAT-AP RDF feed (rdflib), which gives a
per-dataset graph for both the presence metrics and the SHACL conformance
metrics. Two portals expose no national RDF (NL, EE), so a DCAT-AP graph is
synthesised from their JSON for the conformance metrics, with the mapping
recorded as a caveat. One portal (HU) exposes RDF that omits dct:license
entirely, so HU harvests via its CKAN JSON (which carries license_id) and
synthesises graphs for conformance. The route is recorded per country in
`data/catalogue/portals/<CC>.json`.

**Independent recompute, not a reproduction of the MQA.** Conformance (Q16) runs
the official SEMIC DCAT-AP 2.1.1 mandatory SHACL shapes (vendored, see
`agents/tools/catalogue/shapes/PROVENANCE.md`) over each dataset's bounded
description via pyshacl, sampled with a disclosed sample size for the large
portals. Recommended (Q17) and optional (Q18) class usage are field counting
against the recommended-shape predicate set and the spec's optional-property
list. The presence metrics (Q12/Q21/Q22/Q25/Q27) and the distinct-licence count
(Q13) are field counting over the harvested records. The band is assigned from
the question's own `allowed_answers`; the tool never reads `ground_truth` and
ODMI's answer never feeds the computation.

**Storage.** The raw harvest is cached gzipped on disk under
`data/catalogue_snapshots/<CC>/<timestamp>/` (gitignored: FR is ~74k datasets,
DE ~151k, far too large for git). Two committed tables hold the receipt:
`catalogue_snapshots` (endpoint, timestamp, dataset_count, sha256, route,
partial flag) and `catalogue_metrics` (per-question raw value, numerator,
denominator, band, breakdown). A computation replays from the disk cache with
no network call; an examiner re-harvests from the manifest endpoint to
reproduce. RO filters foreign datacentre IPs and has downtime, so the harvester
is resumable and surfaces a partial harvest rather than truncating silently.

**Integration (minimal, existing code path).** `run_researcher` routes the nine
computable band/count questions to `catalogue.compute` before query generation
and emits a normal `ResearcherOutput` (source_url = the catalogue endpoint,
evidence_quote = the computed breakdown, answer = the band). `run_verifier`
short-circuits these to a deterministic recompute from the cached snapshot:
pass iff the band matches, else fail with the recomputed band as
counter-evidence. The Coordinator, the CLI runners and the dashboard pick this
up unchanged. A harvest failure returns None and the pair falls back to the
web-search path.

**Finding (validation against ODMI ground truth, 2026-06-02).** Computed band
vs ODMI's recorded answer across the Phase B set (exact / near_match / differ
over the nine metrics):

| CC | Datasets harvested | exact | near | differ |
|----|--------------------|-------|------|--------|
| HU | 2,282 (full) | 8 | 1 | 0 |
| NL | 20,772 (full) | 5 | 0 | 4 |
| DE | 3,000 (sample) | 4 | 2 | 3 |
| FR | 5,000 (sample) | 4 | 1 | 4 |
| RO | 5,143 (full) | 3 | 3 | 3 |
| EE | unavailable (HTTP 403, IP block) | - | - | - |

Three patterns, all defensible findings rather than tool errors:

1. **Self-report ceiling (the headline, D29).** France was awarded full marks
   having self-reported the top band on nearly every Quality question. The
   independent recompute contradicts this: licence coverage 37.8% (Q12), open
   licence 37.7% (Q25), and strict DCAT-AP mandatory conformance 31.9% (Q16),
   all far below `>90%`. The first-10-pages sample read higher (66.9%), so the
   udata feed is order-biased and the 5,000-dataset figure is the better
   estimate. The structural metrics that hold everywhere (Q17, Q18, Q21, Q22
   recommended/optional usage and the URLs) reproduce `>90%` exactly.

2. **Strict SHACL catches real non-conformance.** Q16 is whole-dataset pass/fail
   against the official SEMIC mandatory shapes (a single violation fails the
   dataset), which is stricter than the MQA's per-property compliance scoring.
   DE reads 4.2% because its distributions carry an `spdx:Checksum` with a value
   but omit the mandatory `spdx:algorithm` triple: a genuine DCAT-AP.de
   incompleteness that the self-reported `>90%` hides. Treat our Q16 as a
   conservative lower bound and a stricter lens than the MQA, not a reproduction
   of it.

3. **The tool surfaces questionable ground truth.** RO and NL agree closely on
   licence and structure, but ODMI's recorded RO answers for several questions
   (access-URL presence `<10%`, recommended usage `10-30%`) are contradicted by
   a live catalogue that exercises them at ~100%. Here the independent recompute
   looks more accurate than ODMI's stale self-report.

HU agrees with ODMI on 8 of 9. EE could not be harvested: its API returned 403
to this environment's IP, so the swarm falls back, an honest "portal blocks bulk
harvest" outcome. Per-route reliability caveats (HU/RO use CKAN JSON because
their RDF omits `dct:license`; NL/EE synthesise graphs from JSON; Q16 on
synthesised routes tends high; Q21 is authoritative only on RDF routes) are in
`docs/CATALOGUE_METRICS.md`.

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
- 129 finalised swarm pairs across FR / DE / NL / RO, covering all
  four ODMI dimensions (Policy, Portal, Quality, Impact). Total
  spend $13.28 (~£10.49). Down from 148 after D28's hard-delete of
  19 forced-collapse rows on non-binary questions.
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
| 2026-06-02 (langgraph removal) | D3 amended from "LangGraph for the Phase 2 agent swarm" to "Plain Python state machine", to match the shipped `run_coordinator.py`. The earlier rationale (graph framework for conditional edges) and the record of the deviation are retained. Stale "runs on LangGraph" claims corrected across METHODOLOGY §5/§8, AGENT_DESIGN §1/§5/§8 (deviation banner added at §5), REPORT_PRELIM objectives/plan/milestones, and PROGRESS_SLIDES stack line. The dead `langgraph`, `langchain-anthropic`, and `langchain-community` dependencies removed from `pyproject.toml` (no Python file imports them; the LLM interface uses the `anthropic` SDK directly). `anthropic>=0.87` promoted to a direct dependency, since `agents/tools/llm.py` imports it and it was only present transitively via `langchain-anthropic`. Lockfile re-resolved; 335 tests pass. Kept deliberately: the "why we dropped it" record (CLAUDE.md, PROJECT_LOG, `run_coordinator.py` header) and the related-work citations in REPORT_PRELIM §2.2 and references.bib. |
| 2026-06-02 (retry/finalisation) | D32 + D33 added, both prompted by a failure-mode analysis of the 43 ground-truth disagreements. D32: finalisation now trusts `adjudicator_answer` for every resolved verdict instead of re-deriving from the verdict label; the logic moved into a pure helper `_finalise_after_adjudication`. Four pairs flip `differ` to `match` on a stored-row replay (P26-b FR, PT14 FR, I16 EE, I17 EE), each an Adjudicator `yes` previously overwritten with `inconclusive`. D33: retry queries forced to diverge; the query generator now receives the Verifier's rejection reason, suggested query, and prior queries with an instruction to vary (`_QUERY_GEN_VERSION` 1 to 2), `ResearcherInput.previous_search_queries` added, coordinator accumulates queries across attempts; first-attempt path unchanged. Defaults and non-retried runs behave as before. New `tests/test_finalise_after_adjudication.py` and `tests/test_query_gen_divergence.py`; 297 non-live passing. The dominant remaining loss (the 67% substring-gate failure that decays answers to `inconclusive`) is diagnosed but not fixed here; it needs snippet persistence first. |
| 2026-06-02 (later) | D30 added: deterministic catalogue-metrics tool (`agents/tools/catalogue/`). Harvests national-portal metadata and computes the nine catalogue-derivable Quality band/count questions (Q12, Q13, Q16, Q17, Q18, Q21, Q22, Q25, Q27) without the deny-listed MQA. Per-country adapter layer over three stacks (udata, CKAN, custom) and four routes (dcat_rdf preferred; ckan_json / udata_json / estonia_json fallbacks); registry in `data/catalogue/portals/<CC>.json`. Conformance (Q16) via the official SEMIC DCAT-AP 2.1.1 mandatory SHACL shapes through pyshacl, sampled with disclosed size; recommended/optional usage (Q17/Q18) and the presence/count metrics by field counting; bands assigned from each question's own `allowed_answers`. Raw harvest cached gzipped on disk (gitignored); committed receipts in new `catalogue_snapshots` / `catalogue_metrics` tables (+ `scripts/migrate_catalogue_tables.py`). Wired into `run_researcher` (route before web search) and `run_verifier` (deterministic recompute-from-cache, pass iff the band matches). Mapping doc `docs/CATALOGUE_METRICS.md`. Validated against ODMI GT (leakage-guarded): HU 8/1/0, NL 5/0/4, DE 4/2/3, FR 4/1/4, RO 3/3/3; EE blocked (403). Headline: FR self-reported `>90%` on licence/conformance but the independent recompute reads ~38% licence coverage and ~32% mandatory conformance (the D29 self-report ceiling). Per-country route findings: HU and RO RDF feeds omit `dct:license` so they harvest via CKAN JSON; DE Q16 4.2% is a real DCAT-AP.de incompleteness (checksums missing `spdx:algorithm`) under strict whole-dataset SHACL. 33 new offline tests; 246 non-live passing. |
| 2026-06-02 | Run Console: each active subtrio card gained a ✕ cancel button. Clicking it calls the new `db.cancel_subtrio(subtrio_id)`, which kills the coordinator process recorded in `subtrio_status.process_pid` (SIGTERM, escalating to SIGKILL, after a `ps`-based PID-reuse guard so a recycled PID is never signalled) and then deletes every row that run wrote, scoped by `pair_run_id`/`subtrio_id` across `phase2_final`, `phase2_adjudications`, `phase2_verifier_runs`, `phase2_researcher_runs`, and `subtrio_status`. Deletion is by subtrio, not by (question, country), so earlier finalised runs of the same pair survive; `claude_usage_log` is left intact so the cost receipt stays (same policy as `delete_pair`). The coordinator installs no SIGTERM handler, so it dies without rewriting a status row after deletion. Read-only deploys short-circuit via `mode.block_if_read_only()`. New `tests/test_cancel_subtrio.py` (2 cases: scoped deletion, unknown-id no-op). |
| 2026-06-01 (later) | D31 added: search knobs (provider, results-per-query, query count) threaded end to end and exposed in the Run Console, so the DIY cost/quality trade-off is runnable as a tagged experiment (`diy_full` 3x5 vs `diy_lean` 2x3, plus `diy_q3r3` 3x3 to isolate the knob). Defaults unchanged (provider auto, 5 results, no query cap), so main runs are unaffected. New `tests/test_search_knobs.py`; 215 non-live passing. Flagged (not fixed here) a stale AppTest path: `test_apptest_handoff` opens `4_Strategy_Lab.py`, since renamed to `4_Verifier_Strategies.py`. |
| 2026-06-01 | D29 added: DIY search pipeline corrected and benchmarked against Tavily. Root-caused the 31% snippet quality to a fetch/extract ordering bug (tag-strip + 4000-char truncation ran before trafilatura, so the picker saw script/nav soup and trafilatura was a dead `is_html=False` no-op); the accepted quote was in the picker input only 38% of the time vs 78% with trafilatura on raw HTML (`evaluation/diagnose_extraction_ceiling.py`). Fix: new `fetch_html` / `fetch_rendered_html` (raw HTML), `search_diy._fetch_and_clean` runs trafilatura on raw HTML then caps, picker `PAGE_TEXT_CAP` 8000→16000 (prompt v2). Snippet quality 31% → 58%; layer-2 test switched to normalised matching. New adjudicated DIY-vs-Tavily harness (`evaluation/diy_vs_tavily.py`) with a blind, position-swapped Opus judge (`search_adjudicator` prompt/tool v2): 36 FR pairs → DIY 12 wins / 2 ties / 4 losses / 18 both_fail; 78% not-worse on decisive pairs, out-wins Tavily 3:1, leads every answerable dimension. Finding: half the questions (all 9 Quality) are unanswerable from the open web (answer on deny-listed data.europa.eu or self-report). Robustness: `_extract_json` handles fenced+trailing-prose JSON; `pick_snippet` degrades gracefully on invalid JSON; fixed the `run_id`→`pair_run_id` join bug in `build_snippet_fixtures.py`. 213 non-live tests passing. |
| 2026-05-26 (later) | D28 Phase 2 landed across five staged commits (A–E). New `answer_shape` and `allowed_answers` columns on `questions`, with 124 / 12 / 3 / 2 / 2 split across binary / percentage_band / ordinal_magnitude / count_band / categorical (commit `d631c30`). Pydantic `answer` fields loosened from a fixed Literal to free-text strings validated at runtime via the new `agents/tools/answer_shapes.py` module; Researcher / Verifier / Adjudicator prompts bumped (V3 / V3 / V3) and each agent now post-validates the emitted label against the per-question allowed list (commit `21255bb`). `_MATCH_STATUS_SQL` gains an `EXISTS` over `json_each(q.allowed_answers)` that flags adjacent-band misses as `near_match`; `accuracy_summary` returns both `accuracy` and `accuracy_within_one_band` (commit `0d1a6c2`). Dashboard renders the new state across Home, Results, Database, Analytics, and Questions (commit `5aae4f0`). Stage E (this commit) adds 13 integration tests on shape-aware prompt assembly and smoke-tests one band-shape pair (Q12:FR) end-to-end; the Coordinator booted cleanly but both Tavily and Brave quotas are exhausted, so the full re-dispatch of the 19 forced-collapse pairs is deferred to after D29 (DIY-Tavily, planned June). Test count: 122 passing. |
| 2026-05-26 | D28 added: per-shape answer schema (`binary`, `percentage_band`, `ordinal_magnitude`, `count_band`, `categorical`) to replace the flat `Literal["yes","no","other","not_applicable"]` that mis-fitted ~22 of 143 ODMI questions. Phase 1 (this commit) is the cleanup: 19 forced-collapse `final_answer = 'other'` rows on non-binary questions hard-deleted from `phase2_final` + 39 Researcher + 39 Verifier + 3 Adjudicator + 19 `subtrio_status`. Pre-deletion DB backed up at `data/odmi.db.bak-pre-D28-20260526T100409Z`. The 22 honest "couldn't tell" rows on binary-rubric questions are kept as real evaluation signal. Stale finalised-pair count in Current status updated (148 → 129). Phase 2 (`answer_shape` column, prompt branching, `near_match` SQL) and Phase 3 (re-dispatch) still to build. |
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
| Which experiments are done / left to run, and their results? | `docs/EXPERIMENTS.md` (status board). Ready-to-run agent prompts in `docs/prompts/`. |
| What did the supervisor say? | Notion supervision log. |
| Where are the parsed questions? | `data/questions/odmi_2025_questions.json`. |
| Where is the live dashboard? | `https://odmi-agent-swarm-f5b4cbeukwunzkuvp2tswn.streamlit.app/` (public, read-only). |
| Coverage of every pair / delete a bad result? | Sidebar → Database. |
| How are costs displayed? | All £ via `dashboard/lib/currency.py` (rate `USD_TO_GBP=0.79`). Underlying column is still `estimated_cost_usd`. |
| Where is the prelim draft? | `docs/REPORT_PRELIM.md`. |
| Where are citations? | `docs/references.bib`. |
| Known gaps and anticipated failure modes? | `docs/KNOWN_GAPS.md`. |
| Hand-mark CSVs (historical, superseded by D22)? | `data/hand_marks/`. |
| One-stop CLI for swarm ops (status, run, audit, purge)? | `scripts/harness.py`. Read-only by default; destructive ops need `--yes`. |
