# ODMI Agent Swarm — Living Spec

Last updated: 2026-07-21

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
**Repo:** `/Users/benjyb/Desktop/MscProject`.
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

**Phase B sample superseded by D42, then by D47.** The evaluation sample is now
the D47 base-rate-stratified held-out set (eight countries: BA, MK, ME, BG, FI,
HR, SE, BE) with a five-country in-sample dev set (NL, MT, NO, FR, AL). The
D42 nine-country 3×3 matrix and the original six-country 2×3 wealth × maturity
sketch are both kept below for the audit trail.

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

### D45: Verifier architecture retained, justified by the EXP-11/12/13 programme

**Date:** 2026-06-11.

The verifier investigation (full synthesis in `docs/VERIFIER_FINDINGS.md`)
concludes by retaining the incumbent design rather than adopting any redesign.
D45 records that as a justified decision, not a non-result: four lines of attack
were pre-registered and run, and the incumbent held against all of them.

- **Prompt (EXP-11).** The tristate verdict collapses to always-confirm/abstain
  (Youden's J 0.03 vs the incumbent disprove's 0.41; it refutes 1 of 150
  candidates); the deterministic quote-gate strips paraphrased-but-real
  refutations (sensitivity 0.62 -> 0.10). Incumbent `disprove` retained.
- **Evidence (EXP-12).** Richer evidence does not raise discrimination. The
  verifier's own counter-search adds nothing detectable (no-search J 0.42 vs
  with-search 0.37, not significant) and its live production form was the worst
  condition (0.10). The verifier's value is cognitive, not retrieval (confirms
  D15). Current DIY-search recipe retained; no shape-conditional recipe adopted.
- **Wiring (EXP-13a).** Relaxing the `fail` block (advisory / shaded / veto-only)
  trades matches for committed-wrong one-for-one; under the committed-wrong-first
  rule no variant beats the hard gate. Gate retained.
- **Reframing.** The verifier verdict is the deciding factor on only 9 of 237
  in-loop commits: the D37 floor is the binding precision control, and the
  verifier's influence flows through the Adjudicator weighing its
  counter-evidence (removing the verification layer costs 27 matches and adds 43
  abstentions at -16 wrong, p < 0.002). The architecture is in practice
  Researcher -> floor -> Verifier-as-advisor -> Adjudicator-as-decider.

Shipped from the programme: **matcher v2** (per-snippet, ellipsis-aware grounding
gate; `agents/tools/substring.py::contains_v2`, wired into `agents/verifier.py`),
closing FM-11 and part of FM-02. Dropped before shipping: the absence
confidence-ceiling (net-negative on dev) and the absence receipts check
(near-inert). `verifier_confidence` audited as decision-irrelevant; kept as
telemetry. The tristate models and prompts remain in the tree as evaluation-only
apparatus (no production path requests them). Open questions (adjudicator
ablation, critic-decider merge, held-out evidence work) are logged in
`docs/VERIFIER_FINDINGS.md` section 7, each needing its own pre-registration.

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
the evidence already collected and either picks a winner or abstains
(D51/D52: the verdict is `abstain` and the terminal status
`abstained_adjudicator`; there is no human queue).

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
| `model-opus` | claude-opus-4-6 | $5/$25 per M tokens |

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

**Date:** 2026-05-12. **Layers 1 and 2 superseded by D40 (2026-06-03):** the
soft limit and its enforcement (pre-flight refusal and the low-water spawn stop)
are removed. The rolling-window cost is still computed and displayed (layer 3,
the clean rate-limit shutdown, is unchanged); it just no longer blocks anything.

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
queries through Tavily first and falls back if Tavily errors or hits
its quota (the fallback target is now DIY then Brave, per D36; it was
Brave alone when D26 landed). Until D26, the only signal we had was a
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

### D37: commit confidence floor, and honest abstention over a forced guess

**Date:** 2026-06-02.

The D35 validation exposed two problems. First, the test set was confounded:
France is 85% yes-gold and the 15 re-run pairs were 14/15 yes, so "12 of 14
recovered" cannot be told apart from a model that learned to guess the majority
class. An "always yes" baseline scores 85.3% on France (122 yes, 20 band/other,
1 no, of 143) and 67.9% globally. Second, D35 forced a commit at the end of the
budget by routing every abstention to the Adjudicator. PT14 FR is the tell:
forced to commit, it produced a confident wrong `no` that the Verifier passed.

D37 makes the loop abstain rather than guess.
- Commit confidence floor (`COMMIT_CONFIDENCE_FLOOR = 0.65`): an answer is
  accepted only if the Verifier passes, the answer is a real label (not
  `inconclusive`), and its confidence is at least 0.65. A sub-floor pass is
  treated as not-yet-answered and retried with feedback that names the gap.
  PT14's 0.55 would now be rejected.
- Honest abstention: `inconclusive` or a sub-floor answer retries within the
  existing 3-retry budget; if it cannot get confident, the Adjudicator may
  return `inconclusive`. The Adjudicator prompt (V4) now prefers an honest
  `inconclusive` over guessing a label to break a tie. `inconclusive` was
  already an accepted Adjudicator output, so no schema change was needed, which
  matters while a concurrent session is writing the shared DB.

This trades raw accuracy against yes-heavy ground truth for honesty: an
abstention beats a lucky or confident-wrong guess. The accuracy of D34, D35 and
D37 is untrustworthy until measured on a set that is not yes-heavy. The honest
validation set is being rebuilt from no-gold pairs (BA/MK/ME/BG/IS each have 50+)
and band questions, where an "always yes" guess scores low so finding can be told
from guessing. 393 non-live tests passing.

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

Receipt (forward validation, experiment_id `inconc_retry_v1`, on top of D34; 14
of 15 pairs finalised, P25 FR errored without a final row): 12 of 14 recovered to
match, against 2 of 14 under the gate fix alone (D34) and 0 in the original main
run. Gate-collapse pairs the gate fix had left at `inconclusive` now resolve to
the correct `yes`, reached across retries (rt1 to rt3) and, for PT11 and PT12 EE,
via the Adjudicator once the budget was spent. Two did not recover: PT33 FR
stayed `inconclusive` through the Adjudicator (its ground-truth string is itself
a compound), and PT14 FR committed to `no` where the truth is `yes`. That last
one is the honest cost of forcing commitment: a wrong answer that passed the
Verifier rather than an abstention. On this set the gate fix plus the abstention
rule moved recovery from 2/14 to 12/14. 368 non-live tests passing.

Caveat (added under D37): this set is yes-heavy (14 of 15 yes-gold) on an
85%-yes country, so 12/14 cannot be distinguished from majority-class guessing.
The number is not trustworthy on its own; see D37 and the honest-validation
note.

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
builds the final output from the Adjudicator's fields; only `abstain` (D51,
formerly `escalate_human`) or an Adjudicator failure keeps the last Researcher
output. The logic is extracted
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

### D36: search auto-fallback is Tavily → DIY → Brave

**Date:** 2026-06-03. **Superseded by D43 (2026-06-09):** the fallback chain is
retired. `provider="auto"` is now DIY only; Tavily and Brave are never used in
production. The description below is kept for the audit trail.

The `provider="auto"` chain in `agents/tools/search.py` now falls back through
the DIY pipeline before Brave. The order is: Tavily first; on a quota / rate /
credit error, the DIY pipeline (Serper SERP → fetch → trafilatura → snippet
pick, per D29); and only if DIY also raises, Brave as a last resort.

Rationale. D29 established that DIY is not worse than Tavily on the
web-answerable pairs (EXP-1: DIY wins 89% of the 55 decided FR pairs), so when
Tavily's credits run out DIY is a better stand-in than Brave, which has never
cleared an adjudicated comparison and previously returned 422s on long-operator
queries (D26). Brave stays in the chain as a final safety net rather than the
first fallback. The explicit single-provider modes (`tavily`, `diy`, `brave`,
`serper_raw`) are unchanged and never fall back, so A/B experiments that pin a
provider are unaffected. `_PROVIDER_USAGE_COUNTERS` gains a `diy` slot and the
`on_call` telemetry (D26) emits one record per provider attempt, so a
Tavily-miss → DIY-hit now shows as two rows in `search_provider_calls`.

This supersedes the two-provider description in D26 (the per-call telemetry
mechanism D26 added is unchanged; only the fallback target changes).

---

## Current status

> **Currency note (2026-06-29).** The authoritative live state is, in order:
> the change log below (current to 2026-06-29), `docs/ARCHITECTURE.md` (the
> config ledger), and `docs/EXPERIMENTS.md` (the experiment board, EXP-10..21).
> The "Built / Not yet built / Open questions" lists in this section are a
> 2026-06-03 snapshot kept for continuity; where a later change-log entry
> contradicts them, the change-log entry wins. Headline shifts since the
> snapshot: evaluation redesigned to the D47 base-rate-stratified held-out set
> (dev NL/MT/NO/FR/AL, held-out BA/MK/ME/BG/FI/HR/SE/BE), search closed to
> DIY-only (D43), portal discovery shipped (D46), the experiment orchestrator
> shipped (D48), and the verifier programme closed on the incumbent (D45).

**Phase:** Dev-set experiment programme. Swarm running end-to-end; dashboard live
(local + Streamlit Cloud); ODMI ground truth loaded. Malta dev baseline done;
dev-set ablations (EXP-10/14/16/17 and the verifier programme EXP-11/12/13) done;
confirmatory re-tests EXP-18/19/20 designed and in progress; the held-out
eight-country headline run (EXP-21) is gated on a config freeze.

### Experiments programme (EXP-1..9, 2026-06-03 snapshot) and search apparatus (D30-D37)

> Superseded by the change log and `docs/EXPERIMENTS.md`. The live programme is
> EXP-10..21; EXP-1/4/5 (provider comparisons) are dead under D43. Read the
> bullets below as historical context, not the current plan.

Two pre-registrations fix the designs before the runs: `docs/EXPERIMENTS_PROTOCOL.md`
(the search experiments EXP-1..5) and `docs/EXPERIMENTS_VERIFIER.md` (EXP-6). The
human-readable board is `docs/EXPERIMENTS.md`; the machine registry is the
`experiments` table (D27).

Apparatus, all built and unit-tested:
- `evaluation/stats.py` — Wilson intervals, exact binomial sign test, McNemar,
  Wilcoxon, Krippendorff alpha. The judge harnesses report intervals, not bare
  point estimates.
- Deny-list parity (DIY filters the Serper SERP pre-fetch, so every provider
  drops D24 domains before retrieval, not after) and evidence normalisation
  (equal passage count, registrable-domain URLs) so the blind judge cannot
  fingerprint a provider.
- Cross-family judges beside the Opus judge: Gemini (dead, zero quota), Groq /
  Llama-3.3-70B (caps tokens per organisation, so its one daily pool blocks every
  key once spent) and Mistral Large (`search_adjudicator_mistral.py`, the judge
  that delivered the EXP-1 reliability number), plus an answer-blind variant, for
  inter-rater reliability against the same-family self-preference threat.
- Adjudication caching (`evaluation/adjudication_cache.py`) so a killed judge run
  resumes from disk rather than re-paying.
- `evaluation/provider_ab.py` — N-provider pairwise round-robin, Copeland ranking.
- `evaluation/verifier_strategies.py` — the EXP-6 four-arm signal-detection harness.

Status (detail in `docs/EXPERIMENTS.md`):
- **EXP-1** (DIY vs Tavily, FR, refreshed): done. DIY wins 89% of the 55 decided
  FR pairs, Wilson CI [78, 95], sign-test p < 1e-4, leading every web-answerable
  dimension. Answer-blind agreement 67%. Cross-family reliability done
  (2026-06-03) via Mistral Large on the frozen 27-pair subsample: raw agreement
  78%, Krippendorff alpha 0.648; all six disagreements are Opus `both_fail` vs a
  Mistral commitment, none a provider-vs-provider flip. Rebuts the same-family
  self-preference concern.
- **EXP-2a/2b** (search-knob cost vs quality, FR then EE): pairs selected, not yet
  dispatched.
- **EXP-3** (multilingual EE/LT/IS): skipped this round; the LT/IS dispatch kept
  stalling at the search step under repeated machine restarts.
- **EXP-4/EXP-5** (Brave, then the four-provider A/B): one judge run yields both;
  interrupted near 882 of ~1080 verdicts, resumable from the cache.
- **EXP-6** (verifier strategy discrimination): dropped this round (2026-06-09).
  Designed and partially run (3/89), retargeted to Malta-primary under R4;
  apparatus and the partial stay in the repo so it can be revived, but the
  four-arm judge run is not a priority for the current pass.
- **EXP-7** (retry chaining): reframed (2026-06-09) from a confirmatory "does
  chaining help" experiment to a chaining-optimisation target. The `--chained`
  code (default off, baseline byte-identical) and the `EXPERIMENTS_CHAINING.md`
  pre-registration stay as the starting point.
- **EXP-9** (model variants): running (2026-06-09). Five arms over the Malta 60
  via `scripts/run_exp9_model_variants.sh` (haiku / sonnet / opus-4.6 / tiered /
  a cross-family Mistral arm), one variable, every other knob pinned. No longer
  quota-gated (20x plan); see the EXP-9 section in `EXPERIMENTS.md`.

**Malta baseline dispatch (2026-06-03, done; 60/60).** The shared prerequisite for
EXP-6/7/8/9. The canonical pair set is frozen and committed at
`data/questions/malta_eval_pairs.json` (60 pairs, 30 `no` / 30 `yes`, seed
20260603, dimension split Impact 17 / Portal 24 / Policy 10 / Quality 9; all 30
`no`-gold binary questions included as the minority class, the 30 `yes`-gold pairs
a size-matched dimension-stratified draw). Generator
`scripts/build_malta_eval_pairs.py`. The baseline dispatch (provider auto,
`condition_label` baseline, no `experiment_id`; batches `exp6_malta` then
`malta_baseline`) finalised all 60: 43 committed yes/no plus 17 honest
`inconclusive` abstentions (D37). The last two, I8-d and PT12, had failed on
`search_empty` because their evidence sat on Cloudflare-protected data.gov.mt;
they were recovered to `inconclusive` once `head_ok` gained a Playwright fallback
for WAF 403s (see Built). Balance-aware quality
(R4): exact match 32/60 raw, 32/43 on committed answers; no-gold minority recall
(TNR) 0.87 with 3 false positives of 23 committed (I7, I8-b, PT29); yes-gold recall
(TPR) 0.60; Youden's J 0.47; mean commit confidence 0.58. Zero data-leakage in any
finalised row; batch cost ~$4.98. EXP-7/8/9 run their own `condition_label` /
`experiment_id` dispatches over the same committed pair list. Three faults were
found and fixed along the way, none of them quota: a missing worktree `.env` plus
an empty `ANTHROPIC_AUTH_TOKEN` injected by the desktop app, which made every LLM
call fail as a misleading `APIConnectionError` (`agents/tools/llm.py`); a resume
path that reused failed / `inconclusive` Researcher rows and stranded 11 pairs at
stage 'researching' (`scripts/run_coordinator.py`); and `head_ok` reporting
Cloudflare-protected portals (data.gov.mt) as `url_unreachable`, which it now
clears with a Playwright render on a WAF 403/429/503 (`agents/tools/fetch.py`).
The not-done set is computed dynamically (canonical IDs minus distinct MT
`phase2_researcher_runs` IDs), so any later re-run resumes cleanly.

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

### D38: Universal experiment rules, with a base-rate rule on country selection

Decision: every experiment now answers to one numbered checklist, R1 to R12, in
`docs/EXPERIMENTS_PROTOCOL.md` section 0. Each per-experiment pre-registration
declares which rules it meets and names any it cannot; a broken rule is a written
limitation, not a silent omission.

The rule that changes designs is R4, the base-rate rule. France's binary gold
runs 119 `yes` to 1 `no`, so a model that always answers `yes` scores about 99%
and a false positive never surfaces; accuracy there measures nothing. R4 requires
(a) the majority-class baseline printed beside every accuracy figure, (b) a
balance-aware headline metric (Youden's J, MCC, balanced accuracy, per-class
rates) when the classes are skewed, and (c) country selection by minority-class
share subject to a well-resourced-language constraint. Malta is the primary test
country (English official, ~30 `no`-gold binary questions), Netherlands the
secondary; countries above roughly 90% one class are barred as a primary set and
may appear only as a labelled degenerate-baseline contrast.

Consequences applied in the same pass: EXP-6 retargeted from a France-dominated
should_fail class to Malta-primary (`EXPERIMENTS_VERIFIER.md`, harness strata
updated, the France/injected partial kept only as a robustness arm); EXP-8
(Family 1 cost-side) and EXP-9 (Family 3 model variants) pre-registered on Malta;
and a rubric audit (protocol section 12) that flags EXP-1's France E1 accuracy as
base-rate degenerate (the E2 provider win-share is unaffected) and EXP-3's
Lithuania control as undiscriminating on binary, since it holds zero negative
golds. All three optimisation runs were gated on a Malta Researcher dispatch; that
dispatch is now done (2026-06-03, 60/60 finalised, see the Malta baseline entry in
Current status), so EXP-6/8/9 are unblocked.

Rationale: the swarm's headline contribution is an accuracy-vs-cost surface. A
surface measured on a degenerate country would be indistinguishable from
majority-class guessing, so the base-rate rule protects the central result.

### D39: EXP-7 chained retry arm, built behind a default-off flag

**Date:** 2026-06-03.

The retry loop spends up to eight calls per pair but treats each as an
independent shot. The Verifier searches the web every round and often finds real
counter-evidence; the loop keeps its verdict and bins the rest. D33 carries
queries and the rejection reason forward, D34 persists snippets, D37 applies the
commit floor, but no round sees the evidence the earlier rounds gathered. EXP-7
tests whether chaining the evidence across the loop recovers more correct answers
per call than independent retries, without raising the false-positive rate.

The chained arm is built and gated behind `--chained` (default off), so
production and the EXP-8/9 baseline are byte-identical to the independent-retry
loop. Three changes, all flag-gated:

- The Verifier's counter-evidence (`counter_evidence_quote` / `counter_source_url`)
  is fed back into `ResearcherInput` on retry, not just the verdict and a query
  (`VerifierFeedback` extended with two optional fields, both default None).
- An evidence corpus accumulates across rounds (a new `EvidenceItem` model; the
  snippets are already persisted under D34) and is carried forward via
  `ResearcherInput.prior_evidence`. The coordinator merges with de-dup on
  (URL, snippet prefix) and a 40-item cap, in pure helpers
  (`_evidence_from_researcher`, `_evidence_from_verifier`, `_merge_evidence`).
- The Adjudicator synthesises over the whole corpus
  (`AdjudicatorInput.evidence_corpus`), committing only above the D37 floor and
  abstaining otherwise. The floor and abstention rules are unchanged across both
  arms; the treatment only changes what each call sees, never the commit bar.

The carried evidence and its using-instruction travel in the per-call user
message, not the system prompt, so `prompt_versions` rows are identical across
arms and an empty corpus renders byte-for-byte as the pre-EXP-7 prompt. The flag
is threaded through `dispatch_subtrios.py` → `run_coordinator.py` as `--chained`.
Offline tests (`tests/test_chained_evidence.py`, 18 cases) pin the three
properties: the chained path carries evidence forward, the baseline path is
byte-identical, and the flag defaults off. 418 non-live tests passing.

Pre-registered in `docs/EXPERIMENTS_CHAINING.md` under the universal rules
(`EXPERIMENTS_PROTOCOL.md` R1 to R12): Malta primary per R4 (no-gold-rich, so a
false `yes` shows up), baseline vs chained, balance-aware endpoints with the
false-positive rate as a co-primary, paired McNemar and Wilcoxon, one
confirmatory joint claim (balanced-accuracy non-decrease at a non-increased
false-positive rate). The run is gated only on the Malta dispatch (search quota,
shared with EXP-6/8/9) and Claude headroom; the code and pre-registration are
done.

Rationale: this is an optimisation experiment on the loop itself, so the arm has
to be runnable yet must not perturb the baseline it is measured against. A
default-off flag with byte-identical baseline prompts is the only way to keep the
EXP-8/9 baseline and production untouched while the chained arm waits on quota.

### D40: Remove the local cost soft limit

**Date:** 2026-06-03. Supersedes D20 layers 1 and 2.

The dispatcher's soft limit (D20) refused a launch when the projected cost
exceeded a notional remaining budget, and stopped spawning new subtrios once the
rolling-window cost crossed a 5% low-water mark. In practice it only got in the
way: the figure is a guessed arithmetic equivalent of a flat CLIProxyAPI
subscription (D1, Q9), not a real balance, and CLIProxyAPI strips the
rate-limit headers anyway, so the "budget" never reflected actual Max capacity.
The one real ceiling is Claude Max's own rate limit, which already surfaces
cleanly as a 429 and a resumable interrupted shutdown (D20 layer 3, kept).

Removed: `DEFAULT_SOFT_LIMIT_USD`, `LOW_WATER_FRACTION`, the `soft_limit_usd` and
`force` parameters and `--soft-limit-usd` / `--force` CLI flags on
`dispatch_subtrios.py`, the `CostEstimate.soft_limit_usd` /
`budget_remaining_usd` fields, the `DispatchResult.aborted_due_to_budget` field,
the pre-flight refusal, and the per-spawn low-water check. `harness.py` no longer
passes `--soft-limit-usd`. The dashboard sidebar drops the soft-limit slider and
the progress-toward-limit bar; the Run Console drops the "Window soft limit"
metric and the "Force release" checkbox. The rolling 5-hour spend is still
computed and shown everywhere it was (sidebar, Run Console, Costs page) as a
plain information meter, and the pre-flight estimate is still logged; neither
blocks a dispatch. Tests updated; 438 non-live passing.

Rationale: a cap that does not track a real balance and that the user has to
force past on every meaningful run is friction without protection. Cost
visibility stays; the gate goes.

### D41: Runaway circuit breakers (not a budget)

**Date:** 2026-06-03. Follows D40.

With the dollar soft limit gone, the one residual risk is a misspecified
experiment that burns the whole 5-hour Claude Max window before anyone notices.
D41 adds two circuit breakers, both keyed on real units (pairs and calls) and
both set far above any real run, so they are silent in normal use and fire only
on a clear runaway. This is the opposite of D20's budget: not "may I spend this?"
on every run, but "this is obviously broken, stop".

1. **Pre-flight size guard (on by default).** A single dispatch above
   `MAX_PAIRS_PER_DISPATCH = 500` pairs is refused before anything spawns, with a
   clear message, unless `allow_large=True` / `--allow-large` is set. The biggest
   legitimate runs are ~100-150 pairs (a full single country); the
   all-questions x all-countries cross-product accident is 5,148. 500 sits
   cleanly between, so it catches the footgun without nagging. The Run Console
   surfaces it as a one-off "allow this large run" checkbox.
2. **Mid-flight call breaker (opt-in).** If `--max-calls N` is set, the dispatch
   loop stops spawning new subtrios once the batch's own logged Claude calls
   (`claude_usage_log` scoped to this batch's subtrios, via `_batch_call_count`)
   reach N. Off by default, for the rarer runaway-loop case. A normal pair is ~5
   calls (~17 worst case), so a sane cap is well above n_pairs x 17.

`DispatchResult` gains `aborted_oversize` and `calls_capped` flags so the UI and
logs can show why a batch stopped short. The real ceiling is still Claude Max's
own 429 (D20 layer 3, the clean resumable shutdown). New
`tests/test_dispatch_runaway_guard.py` (8 cases); 446 non-live passing.

Rationale: the user's actual worry is "a rogue experiment eats the 5-hour token
budget", not per-run cost. A high circuit breaker on the real units answers that
without re-introducing the friction D40 removed.

### D42: Nine-country held-out evaluation matrix (3×3 maturity × language-resource)

**Numbering collision (flagged 2026-07-12 pre-EXP-31 audit).** "D42" was
independently assigned twice: this entry (2026-06-09, the evaluation matrix)
and a second, unrelated D42 below at "Concurrency consumes the shared budget
linearly" (2026-06-04, chronologically earlier despite its later position in
this file). Both are cross-referenced from code comments and other docs
(`run_coordinator.py`, `run_experiments.py`, `docs/EXPERIMENT_RUNBOOK.md`,
`docs/PROJECT_LOG.md` Session 21) with enough surrounding context to
disambiguate, so neither is renumbered retroactively — that would touch
history across ~10 files for a citation-clarity fix. Anyone citing "D42" in
new writing should name the subject, not just the number.

**Superseded by D47 (2026-06-22).** Kept as audit trail. The 3×3 maturity ×
language matrix is replaced by the base-rate-stratified held-out set; the body
below records the original design and rationale.

**Date:** 2026-06-09. Amends D7's Phase B sample.

**Superseded by D47 (2026-06-22).** The maturity x language matrix is replaced by
a base-rate-stratified held-out set. Measuring the ODMI score against the binary
yes-share gives Pearson r = 0.98, so maturity and base-rate balance are one axis,
not two, and the matrix spent three of nine cells (FR/SK/EE) on countries with
1-3 negative golds while excluding the Balkan/accession tail that carries the
false-positive claim. Retained below for the audit trail.

The primary evaluation sample is nine countries arranged on a 3×3 grid: ODMI
maturity (high / mid / low) crossed with language-resource level (high / mid /
low), one country per cell. This replaces the six-country 2×3 wealth × maturity
sketch in D7. Wealth is dropped as an axis; language-resource takes its place,
because RQ3 is about whether the swarm degrades on lower-resource languages, and
wealth was never doing independent work.

> **Do not run the matrix yet (2026-06-09).** The language-resource axis is a
> placeholder. The tiers below are a hand-assigned proxy, not measured. Before
> this matrix drives any headline run, the language-resource level must be fixed
> empirically: an actual measurement of how well the swarm's model reads and
> reasons over each country's language (a per-country Claude language-competence
> score, the open question Q4 below). Until that score exists the matrix is a
> design sketch for discussion only, and the cell assignments may move. SK / SI
> / SE are wired into `run_coordinator.py` so the codes exist, but that is
> plumbing, not a green light. Development still happens on countries outside
> the matrix (Norway is the current dev sweep), so this gate blocks nothing in
> the meantime.

| | High-resource lang | Mid-resource lang | Low-resource lang |
|---|---|---|---|
| **High maturity** | FR (100.0) | SK (95.4) | EE (94.0) |
| **Mid maturity** | DE (87.6) | HU (78.0) | SI (91.2) |
| **Low maturity** | SE (78.0) | RO (75.6) | MT (66.9) |

Maturity is the country's overall ODMI score (sum of `awarded_score` /
`max_score` across all 143 questions in `ground_truth`); the percentage is shown
in each cell. Tiers are rank-thirds of the 36 countries. Language-resource is a
declared proxy (DeepL support, speaker count, and a published low-resource
taxonomy) rather than anything currently in the DB; it must be cited and given a
per-country evidence note in the dissertation, not asserted.

**Hold-out rule.** The nine are a locked evaluation set. The default ("production")
pipeline is not tuned against their results. Free-form prompt and retrieval
iteration aimed at raising accuracy happens on development countries drawn from
the 27 outside the matrix (candidates: ES / IT high-resource, CZ / HR
mid-resource, LV / LT low-resource), so iteration sees language and maturity
variety without touching the eval set. The pipeline is frozen (prompt versions
and knob settings committed; the commit SHA is the lock, same rule as the old D9
hand-mark lock) before the nine are run for the headline numbers.

**What is permitted on the nine.** Pre-registered between-condition experiments
that report a baseline and compare arms: the Verifier-strategy comparison (EXP-6,
Family 2), and on the same basis the cost-side conditions (Family 1) and model
variants (Family 3). These compare arms on a fixed country rather than tuning the
default pipeline to flatter a reported number, so they do not contaminate the
held-out estimate.

**What is forbidden.** Iterative optimisation of the default pipeline against the
nine countries' results. The one tripwire to watch: an experiment-winning
condition must not silently become the new default and then have the headline
cross-country accuracy re-reported on the same nine without disclosure. Lock which
condition is "production" before the held-out run.

**Two wrinkles, recorded honestly.**

1. France is both a matrix cell (high / high) and the legacy development sandbox
   (D4). Its accuracy is therefore in-sample, and is uninformative anyway under
   the base-rate rule (D38 R4: France binary gold is ~99% `yes`). Report France as
   the development point; the other eight cells are the clean held-out estimate.
2. Most cells hold one country, so a per-cell estimate is a single noisy point.
   This is a limit of any nine-country design, not of holding out; optimising on
   the set would hide the noise rather than remove it. Cell-level claims stay
   cautious; the cross-cell trend is the load-bearing result.

`run_coordinator.py` only carries language codes for FR / DE / NL / RO / HU / EE /
MT, so SK, SI, and SE need their official-language codes added (sk, sl, sv) before
dispatch. NL leaves the sample (it shared the mid / high cell with DE).

### D43: DIY is the sole search provider; a 30s fetch-stage deadline (revised 2026-06-24: per-pair, not a batch stop)

**Date:** 2026-06-09. Supersedes D36; retires the D20/D40/D41 cost-scarcity framing.

Two linked changes, both following the move to the Claude Max 20x plan.

**Plan change.** The subscription is now the 20x plan, so Claude headroom is no
longer a practical constraint on a dissertation-scale run. Experiment status
lines that read "gated on quota" or "pending quota" are retired; the only real
ceiling left is Claude's own 429, which already shuts down cleanly and
resumably (D20 layer 3, kept). D40 already removed the guessed cost soft limit;
D41's runaway circuit breakers stay because they guard against a misconfigured
experiment, not against cost.

**DIY only.** `provider="auto"` in `agents/tools/search.py` is now an alias for
`"diy"`. Tavily and Brave are never called in production. EXP-1 settled that DIY
is not worse than Tavily on the web-answerable pairs (it wins 89% of the decided
FR pairs), so there is no reason to spend on a paid provider or to let a silent
fallback substitute one mid-run and confound a result. The explicit `tavily`,
`brave`, and `serper_raw` modes remain in the code but only to reproduce the
EXP-1 comparison; nothing in production reaches them. Telemetry (D26) is
unaffected and now records `diy` for every production search.

**30s fetch-stage blocker.** With one provider and no fallback, a slow search is
a signal, not something to paper over. The DIY network fetch stage (SERP →
fetch → trafilatura, in `agents/tools/search_diy.py`) now carries a 30s
wall-clock ceiling per query (`DIY_FETCH_DEADLINE_S`). The ceiling covers only
the network stage, where blockers live; the Claude snippet-picker that follows
is metered Claude latency, not a blocker, so it sits outside the window.
Exceeding the ceiling raises `BlockerShutdown`. That exception subclasses
`BaseException`, not `Exception`, so the `except Exception` handlers throughout
the DIY pipeline and the agents cannot absorb it; it propagates to the
Coordinator's `main()`, which flushes partial state, marks the subtrio
`interrupted_blocker`, and exits with `EXIT_CODE_BLOCKER` (43). The dispatcher
treats 43 as a global stop, tearing the whole batch down exactly as it does for
a 429. The intent is deliberate: a DIY fetch over 30s means a real blocker (a
Cloudflare or WAF challenge, a hanging portal, a network fault) that a human
must clear, so the run stops loudly rather than limping on or guessing from thin
evidence. The stop is resumable: fix the blocker and re-dispatch, and the
not-done set is recomputed.

**Revised 2026-06-24 (per-pair, not a batch stop).** The raise-and-halt design
described above is the original 2026-06-09 decision. It proved too blunt once
multi-country batches were routine: one slow or WAF-guarded national portal would
trip the 30s ceiling and tear down every other pair in the batch, including pairs
already near completion. The fetch-stage timeout is now a per-pair event. On
timeout the stage still abandons the hung futures (a single fetch cannot spin
forever), but instead of raising `BlockerShutdown` it keeps whatever returned in
time and lets that one pair carry on with partial evidence; the pair's own retry
loop re-queries if the evidence is too thin. Each timeout is recorded via
`_record_fetch_stall` in the `fetch_stage_timeouts` table, so a burst across the
batch is still visible to a systemic breaker that can separate one slow portal
from a batch-wide block. The `BlockerShutdown` propagation path is unchanged and
still carries Claude's 429 to a clean, resumable stop (D20 layer 3); only the
fetch-stage trigger was removed. Code: `agents/tools/search_diy.py` (commit
`08629e4`). The fetch-stage-deadline test in `test_search_diy.py` was rewritten
from `test_fetch_stage_deadline_raises_blocker` to
`test_fetch_stage_deadline_returns_partial_no_blocker` accordingly (commit
`6c1b09d`); the `BlockerShutdown` propagation test in `test_search_provider_arg.py`
still stands (it covers Claude's 429 path, not the fetch stage).

New / changed tests: the four D36 auto-fallback tests in
`test_search_provider_arg.py` rewritten to the DIY-only contract, a
blocker-propagation test there, and a direct fetch-stage-deadline test in
`test_search_diy.py`. 526 passing.

---

### D42: Concurrency consumes the shared budget linearly (a correction)

**Numbering collision.** See the disambiguation note on the other D42 entry
above ("Nine-country held-out evaluation matrix", 2026-06-09) — same number,
independently assigned, not renumbered.

**Date:** 2026-06-04. Corrects `EXPERIMENTS_PROTOCOL.md` section 10. Follows D40,
D41.

Orchestrating agents had been treating concurrent runs as a throughput hazard and
sequencing work "so it does not contend on one quota". That reasoning is wrong and
is now corrected in the protocol. All Claude calls draw on one Max budget through
the proxy, and concurrent calls consume it **additively**, exactly as expected.
There is no super-linear penalty and no per-call slowdown: below the limit,
concurrency overlaps request latency and finishes sooner; at the limit, total time
is budget-bound whether the work runs in sequence or together, so concurrency is
neutral, never worse. The proxy strips every `anthropic-ratelimit-*` header
(Session 9 probe, `scripts/probe_ratelimit.py`), so capacity is unobservable here,
and D40 already removed the cost soft limit as a guessed, unmeasurable figure. Soft
-limit and usage-limit anxiety about running two things at once is not supported by
anything measured on this project.

The real reason to keep two arms of one experiment apart is **data isolation, not
the rate limit**: a shared resume path must not reuse one arm's Researcher rows for
the other. The 2026-06-04 EXP-6 / Malta-`v2` collision (a live verifier-strategy
run rebuilding its candidate set off Malta rows a sibling agent was concurrently
rewriting) was exactly this, a data-state problem with no rate-limit component.
Sequencing arms is therefore a cleanliness choice keyed on
`experiment_id` + `condition_label` scoping, not a budget necessity. Rewrote
`EXPERIMENTS_PROTOCOL.md` section 10 and the `EXPERIMENTS_CHAINING.md` section 10
note accordingly; no code change.

---

### D44: Adjudicator abstains instead of committing "no" on absence of evidence

**Date:** 2026-06-10 (`70ed63c`, following same-day `88c6c61`). **Missing from
this register until the 2026-07-12 pre-EXP-31 audit** — the rule shipped in
code and prompts on 2026-06-10 (referenced by D46 below, by D51/D52, by
`docs/VERIFIER_FINDINGS.md`, `docs/PROMPT_AUDIT.md`, and three other docs) but
was never written up here. Backfilled from the commit and its call sites, not
from a contemporaneous note; treat the date as the implementation date, not a
design-discussion date.

Two paired rules, both landing in the same v4 Adjudicator prompt bump:

- **Prompt rule** (`agents/prompts/adjudicator.py:103,108`): prefer an honest
  `inconclusive` over guessing a label to break a Researcher/Verifier tie, and
  "absence of evidence is not evidence of `no`" — only answer a negative label
  when the evidence positively shows the thing is absent or false, never
  convert "we could not find it" into "no".
- **Structural backstop** (`scripts/run_coordinator.py:436-443`): if the
  Adjudicator commits a negative label with no supporting evidence quote
  (`chosen_evidence_quote` under the 10-char minimum), the coordinator
  overrides the answer to `inconclusive` regardless of what the prompt
  produced. The prompt is the primary guard; this is the code-level fallback
  for when it doesn't hold.

Rationale: an ODMI question's `no` and "we found no evidence either way" are
different claims. A failure to find a publicly-documented feature does not
prove the feature is absent — the country may simply not publish evidence of
it. Conflating the two inflates confident-wrong commits on exactly the
internal-practice / self-report question families where public evidence is
structurally thin (see `docs/ABSTENTION_TAXONOMY.md`, the "no asymmetry").

This is the mechanism behind the D37 floor's honest-abstention framing and is
retained unmodified through EXP-11..13 (D45) and the D50 neg_licence proposal,
which explicitly licenses committing `no` only under stated conditions that do
not weaken this backstop.

### D46: Portal discovery replaces hand-authored catalogue registries

**Date:** 2026-06-10. Extends D30 (catalogue tool); D24 (leakage) is the
binding constraint throughout. Numbered D46 because D44 is merged and D45
is claimed by the in-flight `audit-fix-batch` branch.

**Problem.** The D30 catalogue route fires only for countries with a
`data/catalogue/portals/<CC>.json` registry, and only six existed, all
hand-authored. Norway scored low on Quality purely because `NO.json` did
not exist while data.norge.no published DCAT-AP-NO throughout. The
answerable-share analysis prices the gap at ~6.4 points of accuracy
ceiling per country (83.0% without a registry vs 89.4% with). Hand-
authoring 36 registries and re-verifying them each cycle does not scale.

**Design.** A discovery pipeline (`agents/tools/catalogue/discovery/`)
turns a committed seed URL into a verified registry:

1. *Seeds.* `data/catalogue/portal_seeds.json`: one entry per assessed
   country with `portal_base`, optional `alternates` and `hints` (the FDK
   search service for NO, the EntryScape SPARQL host for SE), and a
   mandatory `source` annotation. Compiled without consulting the EU
   aggregator; the loader refuses deny-listed entries.
2. *Fingerprinting.* `probes.py` recognises CKAN (`package_search`, both
   standard and `/data`-prefixed), uData (`/api/1/datasets/`), paged
   DCAT-AP feeds (`catalog.{ttl,xml,rdf}` and the uData site catalogue),
   SPARQL (`ASK {?s a dcat:Dataset}` with sparql-results content
   negotiation), piveau hub-search, OpenDataSoft, data.json, and the
   hint-driven FDK pattern. A probe miss is any HTTP or parse failure; a
   deny-list refusal always propagates (leakage is never read as a miss).
3. *Verification.* `verify.py` harvests one page through the real adapter
   per candidate route (preference: dcat_rdf, sparql_rdf, ckan_json,
   udata_json, piveau_json, fdk_rdf) and auto-detects the known caveats:
   the HU/RO pattern (RDF feed omits `dct:license`; a licensed JSON route
   wins and the omission is recorded), the FDK pattern (no
   `dcat:downloadURL`, Q21 reads ~0% faithfully), JSON-synthesised
   conformance, no licence metadata on any route, and the data.gov.cy
   producer bug (`dcat:Distribution` used as a predicate, named in the
   rejection).
4. *Emission.* `emit.py` writes the same registry shape as the
   hand-authored six plus `discovery_method`, `discovery_evidence`, a
   machine-readable `caveats` list and an auto-fetched robots.txt
   summary. Every URL in the outgoing payload is re-checked against the
   deny-list; an existing registry is never overwritten without force.
5. *Fallback.* A country with no verified route keeps the web-search
   path; the report records `needs_new_adapter` (stack recognised, no
   adapter) or `failed` (with the rejection evidence), never a silent
   low score.

**Leakage controls.** All discovery traffic flows through
`catalogue/_fetch.py`, which now also re-checks the redirect chain and
final URL (a portal 30x-ing to data.europa.eu surfaces as
`BlockedEndpointError`, not data). The seed loader, prober and emitter
each re-check the deny-list independently. Tests pin every layer
(`test_catalogue_fetch_guard.py`, `test_portal_discovery_*.py`).

**Experiment (2026-06-10, one-page samples, no full harvests).** Stage 1,
on the frozen pre-adapter probe set across all 36 assessed countries: 14
verified working routes (CH, EL, FI, FR, HU, IE, LU, LV, ME, NL, PT, RS,
SI, UA), 5 recognised stacks without an adapter (AT piveau; CZ, HR, SE
sparql; NO fdk), 17 failed (custom stacks with no public catalogue API:
AL, BA, BE, DK, ES, IT, LT, PL, SK; WAF or IP blocks: BG, MK, MT, RO,
EE; the CY malformed feed; IS retired its CKAN into island.is; DE
govdata unreachable from this network at probe time, re-verified once
the host returned). The prober re-found the hand-authored FR, HU and NL
routes unchanged, including HU's RDF-omits-licence fallback, which
validates the fingerprinting against known ground truth. Stage 2, two
new adapters built in response: `sparql_rdf` (one paged CONSTRUCT,
dataset UNION distribution triples; the generic three-level shape timed
out live on data.gov.cz) and `piveau_json` (hub-search pages),
converting AT, CZ, HR and SE; NO's FDK adapter already exists on the
parallel Norway branch. Final state: 19 verified routes (15 newly
emitted registries plus the four re-found hand-authored ones), NO
pending its branch merge, 16 countries with no deterministic route.
Registry coverage goes from 6 hand-authored to 21 countries on this
branch (22 at the Norway merge); per `evaluation/discovery_ceiling.py`
the 15 newly covered countries gain a mean +6.5 points of open-web
accuracy ceiling (83.0% to 89.4%), level with the hand-authored six. Per-country outcomes are
in `evaluation/results/discovery_report.json` and the table in
`docs/PORTAL_DISCOVERY.md`.

**Limits.** A one-page sample can misread an order-biased feed, so the
sample statistics are verification signals, not metric values. WAF and IP
blocks are environment-dependent (EE's hand registry hit the same wall).
piveau portals can federate EU-scope datasets; data.gv.at's index is all
countryData today, and any federating piveau portal needs a scope filter
before metrics run. The registries discovery emits are receipts, not
guarantees: each cycle re-runs discovery and re-verifies before a
harvest, which is the point of automating it.

---

### D47: Evaluation redesign — base-rate-stratified held-out set, not a matrix

**Date:** 2026-06-22. Supersedes D42 (the nine-country 3x3 matrix). Builds on D38
(R4 base-rate rule), D22 (ODMI ground truth), and D24 (deny-list).

**The finding that forces the change.** A country's ODMI score is almost exactly
its share of `yes` answers: Pearson r = 0.98 between the weighted ODMI score (sum
`awarded_score` / sum `max_score`) and the binary yes-share across the 36
countries (France 100% score / 99% yes; Bosnia 15% / 15%). Two consequences:

1. Guessing `yes` on every question scores the country's ODMI score, so naive
   accuracy on a high-maturity country measures nothing: it reproduces the ODMI
   ranking. The swarm's discrimination (can it correctly answer `no`) is only
   visible where `no` golds exist, which is only the low-maturity tail.
2. The negative golds are scarce and clustered. Binary no-share runs from 85%
   (Bosnia) to 0% (Lithuania); the usable negative-gold counts sit in the Western
   Balkans and accession states (BA 78, MK 73, ME 59, BG 51, IS 48, EL 32),
   almost none of which D42 selected. The matrix optimised a maturity x language
   grid and excluded the countries that carry the headline claim.

So maturity and base-rate balance are one axis (r = 0.98), not two, and the
binding characteristic of an evaluation set is negative-gold density, not grid
coverage.

**Why stratified, not random.** The quantity that carries the dissertation (the
false-positive rate and true-negative rate, the proof the system does not
fabricate) is a rare-event quantity concentrated in a few countries. A random
draw of countries would be dominated by all-`yes` countries with almost no
negatives, so the false-positive estimate would be unmeasurable or very wide.
Random sampling of a rare-event population is statistically inefficient. The
standard, more defensible design is class-stratified (case-control style)
sampling that oversamples the rare class, with the rule pre-registered and the
inclusion stated. Defensibility comes from the committed rule, not from
randomness.

**Development set (in-sample, five countries).** Tuning happens only here; these
are never the headline. Chosen to span the regimes the pipeline is optimised
against so it does not overfit one:

- NL (balanced 22% no, well-resourced, thick web),
- MT (balanced 31% no, low-resource English + Maltese; already burned as the
  EXP-6 / 9 / 10 and verifier-programme primary, so reclassified here from
  held-out to in-sample),
- NO (degenerate 8% no, well-resourced, existing dev trails),
- FR (degenerate 1% no, well-resourced, the legacy D4 sandbox),
- AL (balanced 23% no, Albanian low-resource, thin web), added so the hard
  low-resource thin-web regime can be tuned without burning an eval country.

**Held-out evaluation set (eight countries, frozen, pre-registered rule).**
Selected before any headline run by an auditable rule, not a hand-picked list:

- Stratum A, low/mid-resource language, negative-rich: the four highest
  negative-gold counts among non-major-Western-European languages outside the
  dev set, which is BA, MK, ME, BG.
- Stratum B, higher-resource language, as balanced as available: the four highest
  no-share well-resourced-language countries outside the dev set, which is FI,
  HR, SE, BE.

This yields about 368 binary negative golds (261 in A, 107 in B), all four ODMI
dimensions, all five answer shapes, across roughly 1,144 (question, country)
pairs. The two strata are the deliberate language contrast that replaces the
matrix's language axis: if the false-positive rate is flat across A and B,
language drives abstention not error (the RQ3 prediction); if it rises in A, that
is the headline negative result. One pre-stated contrast, not a 3x3 grid.

**Reporting (balance-aware, three-outcome).** No single accuracy number. The
headline is balance-aware: per-class true-positive and true-negative rates with
Wilson intervals, balanced accuracy, Youden's J, against the majority-class
baseline (D38 R4). Because the swarm abstains (D35 / D37), report the
risk-coverage triangle: commit-accuracy (of committed answers, the share
correct), coverage (committed vs abstained), and the false-positive rate among
commits (the safety metric), with the curve as the D37 floor moves. Stratify by
dimension (Quality's deny-list / self-report ceiling shown as honest abstention,
not hidden) and by answer shape (`near_match` for adjacent bands). Disagreements
with ODMI gold get a blind adjudication over frozen evidence and are reported as a
band (lower bound treats every disagreement as a swarm error, upper bound excludes
the confirmed-stale gold), because ODMI gold can be one cycle old (D22). France
stays in the report as a labelled degenerate-baseline contrast, to show
empirically why raw accuracy is the wrong metric. The deny-list (D24) is verified
before the run.

**Freeze protocol.** The pipeline (prompt versions and knob settings) is committed
before the eval runs; the commit SHA is the lock (same rule as the old D9
hand-mark lock and D42). The held-out eight are not touched by any experiment,
development or between-condition, until that frozen headline run. This is stricter
than the D42 between-condition permission and overrides it for the new eight
(decided 2026-06-22): every experiment develops and confirms on the in-sample dev
set, so the held-out estimate is read exactly once, from a frozen pipeline. No
experiment-winning condition becomes the default and then has the headline
re-reported on the eight without disclosure.

**Stretch.** All 36 countries, balance-aware, as a later deployment-scale run that
backs the generalisation claim. The eight-country set is the headline; it proves
discrimination and honesty where they are measurable, and is not claimed to be
population-representative on its own.

**Open follow-ups.** (a) Language codes for AL, BA, MK, ME, BG, FI, HR, SE, BE
need adding to `run_coordinator.py` before dispatch (D42 already flagged sk / sl /
sv). (b) The "English official, no language confound" justification for Malta in
`EXPERIMENTS_PROTOCOL.md`, `METHODOLOGY.md`, `EXPERIMENTS_MALTA_FAILURES.md`, and
the EXP-6 / 9 / 10 designs is oversold (about half Malta's estate is low-resource
Maltese); MT is reclassified as in-sample here regardless, but those documents
still carry the old claim and need the same correction.

---

### D48: Experiment orchestration framework

**Date:** 2026-06-22.

Running experiments reliably needs the rules enforced by construction, not by
memory. Three artefacts:

1. **Orchestrator** (`scripts/run_experiments.py`). One process owns every arm of
   a run. It solves the two concurrency catches structurally: arms typed
   `retrieval` or `cost` are forced to `--no-cache` (the DIY cache is keyed on
   query/url, so a warm cache would let one arm read another's snippets), and
   arms run sequentially each capped at one `global_parallel` in-flight budget
   (the binding limit is concurrent DIY pipelines hitting Serper/WAFs, not the
   linear Claude budget per D42, so sequential-at-cap matches concurrent-at-cap
   with clean per-arm cost and no cross-arm race). Preflight hard-fails on a
   held-out D47 country, a missing call budget, an unloadable deny-list, a
   duplicate condition label, or an arm that moves more than one knob. It pauses
   itself on a budget projection, an unhealthy arm (blocker rate or finalise
   rate), or a dispatch error, and writes `evaluation/runs/<run_id>/` manifest +
   JSONL event log. Resumable by re-running the same spec.

2. **Runbook** (`docs/EXPERIMENT_RUNBOOK.md`). The operational layer over
   `EXPERIMENTS_PROTOCOL.md` (which keeps the R1-R12 statistics): the spec
   format, the preflight gate, the concurrency model, the reflection points, and
   the bug log.

3. **Skill** (`.claude/skills/run-experiment/`). The agent procedure, framing the
   discipline of a careful researcher who runs autonomously but stops to think at
   the pause points. Autonomy model (decided 2026-06-22): fully autonomous within
   the guardrails, with self-pausing reflection points so nothing escalates its
   own resource use; the agent surfaces to a human only for a freeze decision, a
   production-default change, a recurring unexplained pause, or an unexplained
   budget rise.

### D49: Experiment-number reconciliation — two programmes collided at EXP-22/23/24

**Date:** 2026-06-26.

Two experiment programmes both on `origin/main` had independently claimed
EXP-22, EXP-23 and EXP-24, so each number named two different experiments.

- The **confidence-framework** deep dive (designed 2026-06-24/25, concluded null,
  no production change, zero run data in the DB) registered EXP-22 entailment-
  scored Verifier, EXP-23 self-consistency confidence, EXP-24 argue-the-opposite,
  EXP-25 decomposed and calibrated commit score.
- The **language/retrieval** programme (run data + analysis scripts) used EXP-22
  foreign-language ablation (AL), EXP-23 trusted-domain narrow-then-widen, EXP-24
  snippet-cap.

Resolution: the language/retrieval programme keeps 22/23/24. It has 96 finalised
rows under `exp22_foreign_lang_al`, two spec JSONs and several analysis scripts,
so renumbering it would mean migrating run data. The confidence framework moves
to the next free block:

| Was | Now | Experiment |
|---|---|---|
| EXP-22 | EXP-25 | entailment-scored Verifier commit gate |
| EXP-23 | EXP-26 | self-consistency confidence |
| EXP-24 | EXP-27 | argue-the-opposite check |
| EXP-25 | EXP-28 (renumbered again to EXP-30 on 2026-07-01; the arch-ablation ladder claimed EXP-28 with run data) | decomposed and calibrated commit score |

Applied in this change: renumbered `docs/CONFIDENCE_FRAMEWORK_DEEPDIVE.md`, the
confidence section of `docs/EXPERIMENTS.md`, the confidence change-log entry
below, `evaluation/confidence_gates.py` and `evaluation/nl_fp_audit.py`; renamed
`evaluation/exp22_entailment_smoke.py` and its result `.jsonl` to `exp25_*`. The
`experiments` table rows `exp22_entailment_gate` / `exp24_argue_opposite` rename
to `exp25_*` / `exp27_*` on the canonical DB (no child rows; the binary DB
diverges per worktree, so it is not committed here). The language/retrieval
EXP-22/23/24 references are left as-is. EXP-25 to EXP-27 plus EXP-30 are reserved for the
confidence framework.

### D50: neg_licence Researcher prompt variant — favoured, adoption deferred

**Date:** 2026-06-29. Builds on the EXP-A/B/C prompt programme (commit `2c5b239`)
and D47 (held-out freeze).

The EXP-C negative-evidence-licence Researcher variant
(`phase2_researcher_neg_licence`) is built, registered as its own
`prompt_versions` row, and selectable with `--prompt-variant neg_licence`. It is
**not** the production default; `full` remains live.

**Evidence.** Two one-variable runs (prompt only):

- NL dev (`expC_neg_evidence_licence`, n=51/arm, Opus, picker off, verifier_search
  never): directional on all four endpoints (commit rate +2.0pp, commit accuracy
  +4.7pp, neg-FPR -15.3pp, TN recall +3.8pp) and passes the pre-registered joint
  non-inferiority rule, but on tiny cells: TN recall moves on a single pair
  (2/26 -> 3/26), neg-FPR rests on 8-9 committed negatives, and the Wilson
  intervals overlap.
- Held-out (`expC_held_neg_licence`, partial 149 pairs/arm, Sonnet, picker on,
  verifier_search always): TN recall 34 -> 50% on 119+ negative golds, commit
  accuracy 50 -> 56%, neg-FPR flat 26 -> 25%. Powered and production-config.

**Why deferred, not adopted.** The powered, production-config evidence is the
held-out run, and the held-out 8 are the frozen EXP-21 headline set; adopting on
it would let the held-out set shape production config and weaken EXP-21's
independence. The dev run protects EXP-21 but is underpowered and was gathered
under a non-production retrieval config (picker off, verifier_search never), so on
its own it is too weak to set a production default. The clean path, a powered
production-config dev confirmation (NL +/- AL, picker on, verifier_search always),
is owed but blocked on Claude run budget.

**Adoption gate.** Flip `--prompt-variant` default `full` -> `neg_licence` in
`scripts/dispatch_subtrios.py` and `scripts/run_coordinator.py` once a powered
production-config dev confirmation reproduces the direction at adequate power.

### D51: Adjudicator `escalate_human` verdict renamed to `abstain`

**Date:** 2026-06-29.

The fourth Adjudicator verdict is renamed from `escalate_human` to `abstain`. No
human is ever in the loop in this automated swarm, so the old name was a misnomer:
when the Adjudicator cannot pick a winner it abstains, and the pair finalises as
`inconclusive` under the D37 floor. The rename is label-only. The verdict's
meaning, the 0.6 auto-promotion floor, the answer space and the
absence-of-evidence rule are unchanged.

**Scope.** The `AdjudicatorVerdict` literal (`agents/models.py`), the
auto-promotion logic and the `promoted_to_abstain` telemetry field
(`agents/adjudicator.py`), the registered Adjudicator prompt (standard
`phase2_adjudicator` v5 -> v6, free arm `phase2_adjudicator_free` v2 -> v3; both
re-register on the next run), the finalisation branch
(`scripts/run_coordinator.py`), the schema CHECK (`scripts/setup_sqlite.py`), and
the evaluation scripts (`stack_attribution.py`, `abstention_taxonomy.py`, which
coalesce the legacy string). The pair-level terminal status
`escalated_adjudicator` is a separate axis and is **not** renamed; it still flags
a pair the Adjudicator could not settle. (Superseded by D52: that terminal
status is itself renamed `escalated_adjudicator` -> `abstained_adjudicator`.)
Normative docs (`AGENT_DESIGN.md`,
`ARCHITECTURE.md`, `ABSTENTION_TAXONOMY.md`, this spec) are updated; dated records
(`PROMPT_AUDIT.md`, `EXPERIMENTS*.md`, `PROJECT_LOG.md`) keep `escalate_human` as
the name in force when they were written.

**Data.** `scripts/migrate_escalate_human_to_abstain.py` widens the CHECK to admit
`abstain`, keeps `escalate_human` as an accepted legacy value, and converts the
313 existing `escalate_human` rows to `abstain`. Verified on a DB copy: 1,190
adjudication rows preserved, idempotent, indexes and column order intact. The
migration is owed against the canonical DB and run there after merge, not
committed from a worktree (the binary DB diverges per worktree).

### D52: Abstention terminal statuses renamed `escalated_*` -> `abstained_*`; no human-review stage

**Date:** 2026-06-29. Extends D51.

The system has no human-review stage. A pair either commits an answer or
abstains, and an abstention is itself terminal. The old `escalated_captcha` /
`escalated_adjudicator` terminal statuses implied a handoff to a human queue
that was never built, so they are renamed to `abstained_captcha` /
`abstained_adjudicator`. This supersedes the D51 note that the
`escalated_adjudicator` status would stay.

**Scope.** The `TerminalStatus` literal (`agents/models.py`), the finalisation
return (`scripts/run_coordinator.py`), the `phase2_final.terminal_status` CHECK
(`scripts/setup_sqlite.py`, admits `abstained_*`, retains `escalated_*` as
legacy), the dashboard (the Home "Human queue" widget becomes an "Abstentions"
view; Results path summaries and the Run Console pipeline chip drop the "human"
framing), and the evaluation scripts (`adjudicator_commit_policy.py`,
`abstention_taxonomy.py`, which match both names). KNOWN_GAPS gap #3 (the
human-queue CSV writer) is closed as not-a-gap. The separate `flag_review`
evaluation bucket (a committed answer on an n/a gold, held for the researcher's
own review) and the D22 disagreement glance are methodology, not a system
stage, and are unchanged beyond dropping the word "human" from their prose.

**Data.** `scripts/migrate_terminal_status_to_abstained.py` widens the CHECK to
admit `abstained_*`, keeps `escalated_*` as accepted legacy values, and converts
the 313 `escalated_adjudicator` rows in `phase2_final` (plus 336
`final_verdict` mirrors in `subtrio_status`) to `abstained_adjudicator`. Verified
on a DB copy: 2,759 `phase2_final` rows preserved, UNIQUE and indexes intact,
idempotent. Owed against the canonical DB and run there after merge, not
committed from a worktree.

### D53: LanguageRoute `human_required` renamed to `unsupported`

**Date:** 2026-06-29. Extends D51/D52.

The third `LanguageRoute` value, `human_required` (set when neither native Claude
reading nor DeepL can handle a source language), is renamed to `unsupported`.
There is no human-translation stage; a pair whose language cannot be processed
abstains. The value has never been set in any logged run (every
`language_route_used` row is `native`), so this is a clean rename with no data to
migrate.

**Scope.** The `LanguageRoute` literal (`agents/models.py`) and the
`language_confidence.routing_decision` CHECK (`scripts/setup_sqlite.py`), plus
`AGENT_DESIGN.md`. The `language_confidence` table is empty on the canonical DB,
so its CHECK was rebuilt in place to admit `unsupported` (no rows to preserve, no
legacy value retained).

### D54: `pipeline_mode` architecture-ablation knob; EXP-28/29 pre-registered

**Date:** 2026-07-01.

The coordinator gains a `pipeline_mode` knob (`--pipeline-mode`, default
`trio`) so the value of the verification layer can be measured live rather
than by replay (EXP-13a). `trio` is byte-identical to production.
`no_adjudicator` keeps the Researcher-Verifier loop but terminates retry
exhaustion in an honest abstention (`abstained_no_adjudicator`); it delivers
the owed EXP-15 design. `researcher_only` removes the verification layer:
a real label at or above the D37 floor commits (`accepted_researcher_only`),
a sub-floor answer retries with the same floor-feedback message the trio
uses, and exhaustion abstains (`abstained_researcher_only`). The D35/D37
honesty layer is retained in every mode: it is a distinct mechanism from the
adversarial layer under ablation.

**Scope.** `scripts/run_coordinator.py` (knob + loop logic),
`scripts/dispatch_subtrios.py` (passthrough), `scripts/run_experiments.py`
flag_map, `agents/models.py` TerminalStatus, dashboard Results page path
summaries, `scripts/setup_sqlite.py` CHECK plus
`scripts/migrate_pipeline_mode_statuses.py` (table rebuild, three new
statuses; run against this worktree's DB, owed against canonical after
merge). 8 new tests in `tests/test_pipeline_mode.py`.

**EXP-28** (`exp28_arch_ablation`): the three arms over the 156-pair dev
battery (MT 60 + NL 52 + AL 44, 78 negative golds), all models pinned
`claude-sonnet-5`. **EXP-29** (`exp29_sonnet5_model`): the same trio and
pairs on `claude-sonnet-4-6`, the model contrast; adoption rule
pre-registered (switch default to Sonnet 5 only if non-inferior on balanced
accuracy, delta >= -0.02, and no-gold FP rise <= 2 points). Warm SHARED
cache across arms is pre-registered as a matched-evidence design choice
(arms differ only downstream of retrieval). Full pre-registration in
`docs/EXPERIMENTS_ARCH_ABLATION.md`.

### D55: Claude 5 transport compatibility; agent instructions move to the user turn

**Date:** 2026-07-01.

Exposing `claude-sonnet-5` required a CLIProxyAPI restart, and the restarted
proxy (7.2.45) REPLACES the API `system` parameter with the Claude Code
system prompt on its Claude OAuth channel: every instruction the swarm sent
as `system` was silently discarded, for every model. Verified empirically
(a system-only instruction was ignored by both `claude-sonnet-4-6` and
`claude-sonnet-5`; the query-gen model answered the ODMI question instead of
generating queries). Three fixes in `agents/tools/llm.py`:

1. Agent instructions (persona, task, schema) now travel in the user turn
   inside an `<instructions>` block. Restores instruction delivery for all
   models through the proxy.
2. Claude 5 family models reject the `temperature` parameter (400); it is
   omitted for the `claude-*-5` family, kept for every pre-5 model.
3. Claude 5 responses can lead with a thinking block and can exhaust tight
   caller budgets (the Verifier's 200/240-token calls) before any text:
   text blocks are joined explicitly, and a structured-call retry runs at
   4x budget when the failed attempt stopped on `max_tokens`.

Consequences recorded honestly: any run before 2026-07-01 used the old
transport (system param delivered), so cross-date comparisons cross a
transport change and are flagged per R12; the pre-registered EXP-28/29
comparisons are all within-night and unaffected. `claude-sonnet-5` added to
the pricing table at the standard Sonnet rate (notional, D1/Q9).

### D56: `claude-sonnet-5` adopted as the default model, by direct instruction

**Superseded by D59 (2026-07-09).** The official default reverts to
`claude-sonnet-4-6` after Sonnet 5 collapsed coverage on the EXP-28 control arm.

**Date:** 2026-07-01/02.

Benjy's directive, given directly (not via the EXP-29 pre-registered
adoption gate): "from now on we're only using sonnet 5 not sonnet 4.6 for
the experiments and anything." This supersedes the EXP-29 non-inferiority
rule in D54 as the adoption mechanism; EXP-29's Sonnet 4.6 control arm
still runs and its numbers are reported, but the switch itself is a
directed decision, not an empirically gated one. Recorded honestly per the
project's evaluation standards: EXP-29 becomes a post-hoc characterisation
of the switch already made, not a pre-registered gate that was passed.

**Scope.** `DEFAULT_MODEL` in `agents/tools/llm.py`
(`claude-sonnet-4-6` -> `claude-sonnet-5`); the `_read_default` fallback in
`scripts/dispatch_subtrios.py`; `MODEL_OPTIONS` in
`dashboard/pages/1_Run_Console.py` and `dashboard/pages/6_Models.py` gain
`claude-sonnet-5` as the first (default-selected) option, `claude-sonnet-4-6`
retained for comparison runs. The canonical `model_defaults` DB rows were
updated directly in the canonical checkout by a parallel session
(`claude/musing-villani-d7c805`, 2026-07-01 22:16) ahead of this code-level
change landing; this entry brings the code in this branch in line. Any
run before 2026-07-01 used Sonnet 4.6 and must stay labelled as such
(the D55 transport change is a second, independent confound on the same
date — both apply to any 2026-07-01-onward run).

### D57: Held-out exposure voided; EXP-31 is the single reported headline run

**Date:** 2026-07-02. Directed by Benjy: the eight held-out countries are
re-run in full on the final frozen config, once every config-changing
experiment has finished.

**The exposure.** The D47 "read exactly once" protocol has already been
breached twice, on the record:

1. `exp21_frozen_headline`, 2026-06-24: a partial overnight dispatch
   finalised 301 pairs (FI 143/143, HR 59, SE 99) on a pre-freeze config
   before being interrupted (power event; see `docs/OVERNIGHT_RUN_LOG.md`).
2. `expC_held_neg_licence`, 2026-06-27/28: 627 finals across all eight
   held-out countries as a neg_licence A/B replication. D50 explicitly
   excluded this signal from the adoption basis, so no production config
   choice has consumed held-out outcomes.

**The ruling.** All held-out `phase2_final` rows prior to the freeze are void
for reporting. They stay in the DB as audit trail. The headline run is
re-registered under a fresh ID, `exp31_frozen_headline_v2`, dispatched only
after the freeze gates in `docs/EXPERIMENTS_FINAL_PROGRAMME.md` are met. The
dissertation discloses both exposures and the void ruling; the defensible
claim becomes "no tuning decision consumed held-out outcomes" rather than
"never read", and the disclosure paragraph is part of the evaluation chapter.

**Consequences.**
- EXP-21's registry entry and board row are closed as superseded by EXP-31.
- EXP-31..35 are pre-registered in `docs/EXPERIMENTS_FINAL_PROGRAMME.md` and
  the `experiments` table: EXP-31 (headline v2), EXP-32 (all-Haiku cost
  point), EXP-33 (tiered models, the D18 hypothesis), EXP-34 (retrieval
  strategy re-run on Sonnet 5; EXP-23 produced no Sonnet-usable data),
  EXP-35 (single-agent self-critique arm, completing the EXP-28 ladder).
- EXP-9 (`model_variants_mt`) is closed as stalled (21 of ~300 finals,
  Sonnet 4.6 era, old Malta pair list, pre-D55 transport); superseded by
  EXP-32/33 on the current battery. Rows stay as audit trail.
- The cost/efficiency analyses (RQ5) are rebuilt over live data rather than
  the June Malta batch: `evaluation/cost_report.py` computes the cost
  surface, per-role attribution, and cost per committed-correct answer from
  the canonical DB, with SVG figures under `docs/figures/`.

### D58: 503 `auth_unavailable` handled as a resumable shutdown, not a crash

**Date:** 2026-07-02/03.

Found live during the EXP-28 rerun: the `researcher_only_s5` arm came back
from `arm_health` unhealthy (finalise_rate 0.353, 100+ pairs stuck at
`subtrio_status.stage='researching'` with no `phase2_final` row). Root
cause was not a bug in the `researcher_only` pipeline_mode logic (D54):
under concurrent-window load, CLIProxyAPI's shared Claude Max auth-file
pool has no session free for a given model and returns a 503
`auth_unavailable`, which the SDK surfaces as `anthropic.InternalServerError`.
That propagated uncaught through `call_for_structured`, crashing the
coordinator subprocess mid-stage with no DB update at all — the
subtrio_status row was silently orphaned and the pair vanished from both
the health check and the idempotent resume set, indistinguishable from a
pair that was simply still running.

**Fix.** `agents/errors.py` adds `AuthUnavailableShutdown(RateLimitedShutdown)`:
same shape as a 429 (transient shared-capacity exhaustion, not a caller
bug), so it reuses the entire tested 429 contract — same
`EXIT_CODE_RATE_LIMITED`, same dispatcher global-stop-and-resume — via
subclassing, with no changes needed to `dispatch_subtrios.py` or
`run_experiments.py`. `agents/tools/llm.py::call_for_structured` catches
`anthropic.InternalServerError` (any 5xx from the proxy/upstream, not only
the literal `auth_unavailable` message) alongside the existing
`RateLimitError` catch, logs a `claude_usage_log` row
(`rate_limited=True`), and raises the new subclass.
`scripts/run_coordinator.py`'s `except RateLimitedShutdown` block branches
on `isinstance(exc, AuthUnavailableShutdown)` to write an honest
`final_failure_reason` (`auth_unavailable` vs `anthropic_rate_limit`)
rather than mislabelling every subclass as a plain rate limit. Verified
live: replayed the exact crash (`Q23:MT`, `researcher_only_s5` knobs)
against the real proxy under load — the same 503 now prints
`[AUTH UNAVAILABLE]` and reaches the clean `interrupted_rate_limit` path
instead of an uncaught traceback. 3 new tests
(`tests/test_auth_unavailable_shutdown.py`); 770 pass.

**Scope note.** The Mistral call path (`_mistral_structured_call`, the
EXP-9 cross-family arm) is not wrapped in this try/except and keeps the
same gap; out of scope here since no current experiment exercises it.

### D59: revert to `claude-sonnet-4-6` as the official default; Sonnet 5 kept only as a labelled comparison

**Date:** 2026-07-09. Directed by Benjy. Supersedes D56.

**The finding that forces it.** EXP-28's `trio_s5` arm is the production
architecture with nothing changed but the model (Sonnet 5). It performed far
below the Sonnet 4.6 baseline: coverage 0.27 against roughly 0.85 on 4.6, worst
on the thin-web countries (Malta 7 of 60 committed, 0.12, against 0.72 in the
June 4.6 baseline), at about 3x the cost per pair (GBP 0.141 vs 0.05). It is not
a crash. The verifier verdicts are healthy and the researcher finds evidence
(candidate recall 0.60), but Sonnet 5 stays under the D37 0.65 confidence floor
on sparse evidence, runs the retry loop to exhaustion (mean 2.9 of 3 on Malta),
and abstains. Both the researcher (more `inconclusive` answers) and the verifier
(more `fail` verdicts on committed `yes`) turned more conservative.

**The decision.** The official default reverts to `claude-sonnet-4-6`, the model
every June development experiment ran on (EXP-14/16/17/19/20, the Malta baseline,
the verifier programme). Reverting aligns the frozen headline config with the
validated model and makes the dissertation's completed-experiment labelling
consistent, since those results are all 4.6. Sonnet 5 stays selectable in the
dashboard as a labelled comparison arm, so the coverage collapse can be reported
as evidence rather than hidden.

**Scope.** `DEFAULT_MODEL` in `agents/tools/llm.py` and the `_read_default`
fallback in `scripts/dispatch_subtrios.py` reverted `claude-sonnet-5` ->
`claude-sonnet-4-6`; `MODEL_OPTIONS` in the two dashboard pages reordered so 4.6
is first (default-selected), 5 retained; `model_defaults` DB rows set to 4.6 for
all three roles in the canonical and this worktree DB via the new idempotent
`scripts/set_default_model.py`. The picker falls back to `DEFAULT_MODEL`, so the
whole stack returns to 4.6. The Sonnet 5 pricing row and the `_rejects_temperature`
Claude-5 detector are retained (harmless; needed when Sonnet 5 runs as a
comparison).

**Caveat this does not fix (important).** This reverts the model, not the D55
transport. CLIProxyAPI 7.2.45 still forces agent instructions into the user turn
for every model, so 4.6 now runs on the new transport too. If the coverage
collapse was transport-driven rather than model-driven, reverting the model alone
will not restore it. The first 4.6 run under the current transport is therefore
the model-vs-transport test the `trio_s46` pilot was designed to be: coverage
back near 0.72 means Sonnet 5 was the cause (model); coverage still near 0.27
means the transport change is implicated and needs a plumbing fix, not a model
swap.

**Consequences for the programme.** EXP-31..35 were pinned to `claude-sonnet-5`
(D57 final programme); the frozen headline (EXP-31) and the dev-battery re-runs
move to 4.6. EXP-28's Sonnet 5 rows (`trio_s5` etc.) become a labelled
"Sonnet 5 collapsed coverage" characterisation, not the architecture-ablation
result; the ablation ladder needs re-running on 4.6 to be valid. EXP-29's
Sonnet 4.6 arm is now the config itself, not a contrast.

**Availability note.** At decision time the proxy was returning
`auth_unavailable` for all models (the swarm had not dispatched since
2026-07-03), so 4.6 availability through CLIProxyAPI is verified on the first
call after the proxy re-authenticates, before any run is trusted.

### D60: deny-list path fragment broadened to catch prefixed ODMI-result slugs

**Date:** 2026-07-09. Extends D24 (the hard ban on ODMI publications as evidence).

**The gap.** `BLOCKED_PATH_FRAGMENTS` in `agents/tools/blocked_domains.py` held
`/open-data-maturity` with a leading slash. `is_blocked` is a substring test, so
a slug that carries a prefix before the compound, such as
`/article/2025-open-data-maturity-highlights-progress-in-the-eu-countries/`, did
not match (the slash sits before `2025`, not before `open`). Found in the
2026-07-09 pilot pre-flight: a Malta national-portal page reporting the 2025 ODMI
results was used as a Researcher source and reached one finalised pair; the
D24 audit script did not flag it because the fragment did not match. This is the
FM-14 content-leakage class: a page carrying ODMI's own answers entering the
evidence for the signal we predict.

**The fix.** The fragment is broadened to the bare compound `open-data-maturity`
(the two now-redundant longer variants `open-data-maturity-report` /
`open-data-maturity-index` are removed, subsumed). The compound is
ODMI-specific, so it does not over-block generic open-data pages: a plain
`open-data-portal` slug, `data.gov.mt` datasets, the Wikipedia `Open_data_*`
articles, and the `eur-lex` High-Value-Datasets regulation all still pass
(pinned in `tests/test_blocked_domains.py`). Domain blocking stays the primary
defence; the path fragment is the secondary guard. `/odmi` keeps its leading
slash and carries the same latent prefix risk, but a bare `odmi` fragment would
over-match, so it is left as is and the domain-level block covers the ODMI hosts.

**Scope and audit.** One-line change in `blocked_domains.py`; two regression
tests added (the prefixed slug blocks, a generic open-data slug passes); the
pinned-fragment belt-and-braces test updated to the new string. 41 deny-list
tests pass. One pilot pair (`exp29_sonnet5_model`) is retro-flagged as touching
the now-blocked URL and is excluded from any reported figure and re-run clean.
`check_data_leakage.py` remains the pre-run and post-run gate for EXP-31; it
inherits the broadened fragment automatically.

### D61: pre-July transport fully restored (proxy cloak disabled + system param), so the baseline matches June

**Superseded in part by D62 (2026-07-10).** The cloak-disabled half of this
decision did not hold: Anthropic 429s undisguised Sonnet/Opus OAuth traffic
(Haiku passes undisguised, which is the tell that this is a disguise problem,
not quota exhaustion), so the cloak must stay ON permanently. With the cloak
on, CLIProxyAPI rewrites the API `system` param to the Claude Code prompt and
silently discards agent instructions sent that way — exactly the D55 problem
D61 believed it had retired. D62 keeps D61's model-baseline goal (matching the
validated June behaviour) but reaches it by folding instructions into the user
turn in a way that survives the cloak, not by disabling the cloak. Do not
re-attempt the cloak-disabled / system-param transport in any future session;
it is permanently dead. See D62 below.

**Date:** 2026-07-09. Completes D59 (Sonnet 4.6 revert) by removing the July
transport change (D55) entirely, not just the model.

**Why D59 was not enough.** D55's user-turn instruction folding was a workaround
for CLIProxyAPI 7.2.45's "cloak" feature, which disguises non-Claude-Code clients
as Claude Code and rewrites the `system` prompt. That is a proxy behaviour, not a
model one, so reverting the model (D59) left the July transport in place: the
2026-07-09 diagnostic pilot ran on Sonnet 4.6 but with the cloak still active, so
its numbers are not the clean pre-July baseline (Malta coverage 0.35 vs June 0.72;
NL over-committing). The requirement is that this experiment's baseline is the
exact configuration of the validated June dev runs.

**The restoration (two halves).**
1. **Proxy:** `disable-claude-cloak-mode: true` added to
   `/opt/homebrew/etc/cliproxyapi.conf` (backed up to `.bak-precloak`). The proxy
   now passes the API `system` prompt to Claude as-is, with no Claude Code prompt
   injected. Returns a 429 cooldown (not 401) after the flip, confirming the Max
   auth still works; the disguise was not load-bearing for auth.
2. **Code:** the D55 user-turn folding in `agents/tools/llm.py::call_for_structured`
   is reverted to the pre-July call shape (`system=sys_text`, clean user message).
   No test pinned the folding; 19 llm/model tests pass. The Claude-5-only
   temperature-omit and thinking-block handling stay but are inert on 4.6.

**Verification gate (owed before any run).** The combined change is verified with
one call once the Max quota recovers: a `system`-only instruction must be
honoured end to end (auth works AND our system prompt reaches the model). Only
after that passes does any EXP-28 dispatch start. If Sonnet 5 is ever run as a
labelled comparison, cloak-off means it too uses the plain `system` param.

**This gate never passed as written; superseded by D62 below.** The
`system`-only verification call failed: with the cloak on (which it has to
be — see D62), the API `system` param never reaches the model, so a
`system`-only instruction is never honoured. D61's premise (cloak off, plain
`system` param) turned out to be unrunnable in production.

### D62: agent instructions folded into the user turn, cloak-safe

**Date:** 2026-07-10 (`b6f5eb6`). Supersedes the transport half of D61; keeps
D61's goal (a 4.6 baseline that reproduces validated June behaviour).

**The problem, live.** D61 assumed the proxy cloak would stay off, so it sent
the full agent prompt and schema via the API `system` param. The cloak cannot
stay off (see the D61 annotation above: Anthropic 429s undisguised Sonnet/Opus
OAuth calls). With the cloak back on, CLIProxyAPI 7.2.45 replaces the `system`
param with its own Claude Code prompt, silently discarding everything D61 put
there. Observed directly: the EXP-34 4.6 pilot came back **10/10
`agent_failure`**, every one `query_gen_schema_invalid` (the Researcher never
saw its own instructions, so it could not even form a query), and the
closed-book battery's abstention framing collapsed (**0% vs the expected
22.4%** — an agent with no instructions cannot know it is allowed to abstain).

**The fix.** `agents/tools/llm.py::call_for_structured` folds the full prompt
and schema into the user turn inside an `<instructions>` block, so the
instructions reach the model regardless of what the cloak does to `system`.
This is the same direction as D55's original workaround, now understood as the
permanent shape rather than a July-only patch to be reverted. 13
insertions/10 deletions, one file.

**Verification.** The EXP-34 4.6 pilot re-run finalises **20/20** across both
arms with the abstention framing restored, matching the pre-July shape D61 was
trying to reach. This is the evidence base for treating EXP-34's re-pinned
spec (`evaluation/specs/exp34_pilot_nl_s46.json`, registered as
`exp34_retrieval_strategy_s46`) as running under a working transport, and the
first `claude-sonnet-4-6` data point under any post-D55 transport.

**Standing rule.** The cloak stays ON permanently. Any future proxy/transport
change must be tested against this failure mode (silent instruction discard,
not a loud error) before being trusted — the 10/10 `agent_failure` and the
abstention-rate collapse are the two cheap tripwires that caught it here and
should be re-checked after any CLIProxyAPI upgrade. The EXP-29 4.6 battery
(2026-07-10..12) and the EXP-36 headline both run on this transport.

### D63: EXP-28 architecture-ablation table filled by zero-cost replay of the trio run, not fresh dispatch; underlying rows subsequently lost to operator error

**Date:** 2026-07-12. Companion to the 2026-07-12 D62-regression change-log entry
below (same 156-pair `trio_s46` run; this entry covers the `no_adjudicator` and
`researcher_only` arms of the same experiment).

**Method.** `no_adjudicator` and `researcher_only` outcomes are fully derivable
from the trio run's own `phase2_researcher_runs`/`phase2_verifier_runs` rows:
the Researcher/Verifier loop runs byte-identically across all three
`pipeline_mode` values up to the point they diverge (`scripts/run_coordinator.py`
~L1310-1470). `no_adjudicator` differs from `trio` only at retry-exhaustion (an
Adjudicator call becomes an automatic `abstained_no_adjudicator`); if a trio
pair was `accepted_by_verifier`, the Adjudicator was never reached and
`no_adjudicator`'s answer is identical by construction, no replay needed.
`researcher_only` is simply the first Researcher attempt whose answer is not
an abstention and whose confidence clears the D37 0.65 commit floor
(`COMMIT_CONFIDENCE_FLOOR`), which is saved for every attempt of every trio
pair regardless of `pipeline_mode`. Avoided a ~300-pair fresh dispatch this
way (flagged after one was drafted and briefly launched -- ~9 pairs ran before
being caught and killed; those 9 were kept and used as the live-check sample
below instead of being wasted).

**Results (156-pair replay).** `trio` (actual): 52.6% coverage / 64.6%
commit-accuracy. `no_adjudicator` (replayed): 42.3% / 65.2%. `researcher_only`
(replayed): 46.8% / 65.8%. Commit-accuracy is flat across all three arms --
the Verifier and Adjudicator are not adding precision on this battery; the
full trio's only measurable value over the ablated arms is coverage (+10pt
over `no_adjudicator`, +6pt over `researcher_only`). Consistent with the
2026-06-25 confidence-experiments finding that no evidence gate catches the
confident FPs.

**Live-check (9 targeted pairs, real dispatch, not reused).** 8/9 matched the
replay's prediction exactly. The one miss (`I22:MT`) was not a replay-logic
error: a fresh `no_adjudicator` dispatch retrieved genuinely different search
evidence than the trio run had for the same pair (different source URLs,
committed on attempt 2 instead of reaching retry-exhaustion), so the D54
"warm shared cache" design does not hold 100% of the time across arms
dispatched in separate invocations. Read the replay table as a reliable
directional result, not an exact one -- roughly a 1-in-9 chance any single
replayed pair's outcome would differ under a genuinely fresh live run.

**Data-loss caveat (why this cannot be re-verified from the DB right now).**
The 156-pair `trio_s46` dataset this replay depends on was never committed to
canonical `data/odmi.db` (worktree DBs diverge by convention and are not
committed; backfill was owed but not done before the loss below), and was
subsequently destroyed in the source worktree by a `git checkout --
data/odmi.db` run during an unrelated rebase attempt, which silently reverted
the live, uncommitted working file to a stale pre-session commit. No WAL file
or local Time Machine snapshot survived to recover it. The numbers in this
entry are transcribed from the analysis performed in-session before the loss,
not independently re-verifiable against the DB as of this commit. Re-running
the 156-pair `trio_s46` battery (`evaluation/specs/exp29_s46_100pct_cumulative.json`,
already registered) would restore a requeryable dataset; until then, treat
this section as a documented finding, not a live number.

### D64: EXP-31 discarded; EXP-36 is the fresh frozen headline, wide_only adopted, coordinator data-integrity fixes in

**Date:** 2026-07-13. Supersedes D57's `exp31_frozen_headline_v2`, which pinned a
cut model (Sonnet 5, reverted by D59) and predated the July verdicts. The
headline is re-minted as EXP-36 (`exp36_frozen_headline`) with a fresh
pre-registration, `docs/EXPERIMENTS_EXP36_PREREG.md`, which holds the full
decision map. Spec `evaluation/specs/exp36_frozen_headline.json`.

**The frozen configuration.** DIY (D43); models `claude-sonnet-4-6` for
researcher, verifier, adjudicator and picker (D59); user-turn transport with the
cloak on (D62); results-per-query 5 (EXP-18); verifier counter-search always
(EXP-19); no chaining (EXP-20); full Researcher prompt, neg_licence off (D50);
trio pipeline (D54); abstention floor 0.65 (D37); `no_cache` for the run. The one
production flip is `search_strategy = wide_only`.

**wide_only adopted (EXP-34).** The 2026-07-13 EXP-34 re-run on 4.6 (NL+MT+AL dev
battery, `exp34_retrieval_strategy_s46`) met the pre-registered adoption rule on
NL (negative-gold FP 17 to 14 paired, commit-accuracy 0.62 to 0.67, non-inferior),
and no country regresses. Adopted on the literal pre-registered NL rule. Neither
effect reaches significance at full power (the pooled FP McNemar is p=0.727 and a
paired accuracy test on the pairs both arms committed is a tie), so no general
accuracy or FP-reduction claim is made beyond the NL rule; the raw pooled
commit-accuracy figures (0.679 to 0.733) are not a valid paired effect because the
arms abstain on different pairs. The code default flips
`narrow_then_wide` to `wide_only` across the dispatcher, coordinator and
Researcher; narrowing is inert on the eight held-out countries anyway (no
trusted-domain lists), so the headline runs wide on every reported country.

**Coordinator fixes carried by the freeze.** Four data-integrity defects fixed
before dispatch: B1 `invalid_answer_shape` now retries rather than committing
junk; B2 a final-attempt Verifier `schema_invalid` adjudicates on the answer in
hand rather than dropping the pair; B3 an empty catalogue abstains rather than
reporting "<10%"; B4 the dashboard Run Console no longer offers the cut Sonnet 5.
B1/B2 are covered by `tests/test_coordinator_bug_fixes.py`. The EXP-18/19/20/34
verdicts were measured pre-fix; the fixes touch only malformed-output edge cases,
not the tested knobs, so the verdicts carry (disclosed in the prereg).

**Resume rule.** The headline resumes at pair granularity across interruptions
(finalised pairs kept, unfinished re-run) under one frozen config and one run_id;
a resume under any changed knob voids the run.

**Remaining gate.** The ARCHITECTURE.md freeze commit and tag are applied as the
last step before dispatch; the `exp36_frozen_headline` registry row and the void
of `exp31_frozen_headline_v2` land in the canonical DB at the same point.
Dispatch is from a fresh copy of the purged canonical DB (held-out cache removed
2026-07-13, commit b8a316c), never a worktree copy.

### D65: EXP-41 measures run-to-run stability; EXP-40's lost rows were recovered, not re-run

**Date:** 2026-07-21. Pre-registration: `docs/EXPERIMENTS_RUN_STABILITY.md`.
Registry ids `exp41_stability_rep1`, `rep2`, `rep3`. Specs generated by
`scripts/gen_exp41_specs.py`. Not yet dispatched.

**The defect, and its repair.** An audit found the EXP-40 cooperative arm had
zero rows in all 46 `odmi.db` copies on disk and no `experiments` registry row
anywhere. It ran on 2026-07-19 in a worktree that was later deleted; the code,
prereg and analysis JSON were committed but the rows never were, because
`data/odmi.db` is LFS tracked and no commit in that sequence touched it.
`evaluation/exp40_analysis.py --db data/odmi.db` returned n=0 for all four arms
while still printing `McNemar p=1.000`, the same p-value the dissertation
reports, so the documented reproduction path yielded a plausible null from an
empty database with no error.

The rows were recovered from an orphaned Git LFS object that was one prune away
from deletion, and are now committed as SQL dumps under `data/recovery/`.
Verified independently: restoring both dumps into a copy of the canonical DB
and re-running the committed analysis reproduces
`evaluation/results/exp40_analysis.json` byte for byte, all four arms, primary
contrast n=154 at 8 versus 8, p = 1.00. **§4.2 stands on recovered rows and
needs no re-run.** A fresh cooperative run would have produced different
numbers on a non-deterministic system and forced §4.2 to be restated rather
than reproduced.

**Outstanding.** The canonical `data/odmi.db` has not yet been restored from
the dumps: it still lacks both experiments and carries the pre-EXP-40 CHECK
constraint. Procedure in `data/recovery/README.md`.

**What EXP-41 now is.** Three fresh dispatches of the incumbent trio over the
156-pair dev battery, 468 pairs, closing the second condition of the §2.2
Reproducibility criterion (evidence that a repeat returns the same answers)
which §4.7 leaves open and Table 3.1 omits entirely. The originally-scoped
cooperative re-run is dropped as unnecessary, and replicate 1 no longer doubles
as a live trio arm for §4.2: replacing the exp34 replay would restate a settled
result for no defect. Instead the replicates give §4.2 an empirical noise floor
for its ablation ladder, which that section can currently only bound with
overlapping Wilson intervals.

**Configuration.** Verified identical to the incumbent: EXP-36's frozen
headline and EXP-34's `wide_only` arm agree on every behavioural knob, each
leaving a different subset implicit at its default. All 21 knobs are pinned
from one `FROZEN_KNOBS` dict and all reach the command line. No seed.

**Leak controls.** `--no-cache` disables cache reads only, so writes refill the
cache and the purge repeats before every run; `scripts/purge_search_cache.py`
was added for it, since `purge_heldout_cache.py` clears only the held-out
eight. Each replicate takes a distinct `experiment_id`, because
`run_experiments.finalised_pairs` and `_find_resumable_researcher` are both
scoped on `(experiment_id, condition_label)`: replicates sharing a key would be
skipped outright and would share evidence. All four model knobs pinned because
`model_defaults` still holds a cut `claude-sonnet-5` row. `refresh_catalogue`
and `no_warm_catalogue` cannot be set from a spec and are disclosed as
unpinnable but inert, since none of the 156 pairs is catalogue-computable.

**Pre-registered bars.** Outcome unanimity ≥ 0.80 with Fleiss' κ ≥ 0.60,
predicted to miss; commit-rate range across runs ≤ 0.10; label agreement given
all three committed ≥ 0.90 with κ ≥ 0.70, predicted to clear. The predicted
miss follows from the pile-up at the D37 floor: of 81 committed exp34
`wide_only` pairs, 19 sit at exactly 0.65. Evidence-path divergence across runs
is descriptive and is the result the experiment is for. No adoption rule;
production stays trio (D45).

### D66: a row with no LLM call says which path it took; a crashed pair is never an abstention

Three logging defects, all the same shape: a code path recorded "nothing to
report" where it should have recorded what actually happened. Found while
checking whether the §4.2 ablation ladder was contaminated by the cut Sonnet 5
(it is not: all four arms are `claude-sonnet-4-6`, replayed off
`exp34_retrieval_strategy_s46` / `wide_only` by `evaluation/exp40_analysis.py`;
the Sonnet-5 `exp28_arch_ablation` arms are not what the table reads).

**1. An output-less Researcher attempt left no row.** `run_coordinator.py`
persisted a failed attempt only when it still carried an output, on the
reasoning that an unrecoverable failure "has nothing to persist". It has the
fact that it ran. Skipping the write made the retry the first logged attempt, so
the trail renumbered itself silently: 17 of the 156 `exp34_retrieval_strategy_s46`
pairs have no `retry_count=0` row for this reason, while the other 139 are
0-indexed. Any reader keying on attempt 1 mistakes a lost attempt for a
Researcher that declined, which is what the researcher-only arm does. Now every
failed attempt is persisted with `failure_mode` set, so
`_find_resumable_researcher` (`failure_mode IS NULL`) still never resumes from it
and the Adjudicator still never weighs it. Historical rows are not
reconstructible and are disclosed instead: the arm reports the gap count, and the
bound on it is small (commit rate 0.237 -> 0.244, commit-accuracy 0.649 -> 0.658
under an earliest-attempt fallback), and it leans conservative, since it moves
the weakest arm up and makes the ladder's own claim marginally weaker.

**2. `model_version` collapsed three different situations into `unknown`.** The
fallback wrote the bare string whenever no usage was attached, so a deliberate
no-call path was indistinguishable from a logging failure. Two real cases were
hiding there: 49 seeded EXP-40 Researcher rows (a frozen attempt reused rather
than paid for again) now read `seeded_replay`, and 48 deterministic
catalogue-recompute Verifier rows, 33 of them in the EXP-36 headline, now read
`deterministic`. The second matters beyond tidiness: it makes the deterministic
verification route countable, which §3.5's convergent-validity argument relies
on. `unknown` is retained for a gap nobody can explain. Historical rows are left
as they are; rewriting recorded values to look tidier is worse for an audit trail
than leaving them and saying so here.

**3. The ablation adapter recoded crashes as abstentions.** `_pair_row` in
`exp40_analysis.py` mapped every non-commit to `abstained_adjudicator`, so
`three_outcome` reported `n_failed: 0` while the source carried 8 `agent_failure`
pairs (MT I5, I8-a, PT10, PT12, PT17, PT18, PT44; AL I9-a). The reader already
separates crashes from abstentions; the adapter defeated it before it got there.
A crash is not a decision to decline, and abstention quality is the Selectivity
claim the ablation exists to measure. The cooperative arm has 0 crashes over its
156, so the shared denominator was also mildly unfair to the three adversarial
arms. Crashes now survive the mapping, and `completed_only()` reports coverage on
the pairs that completed in every arm, which keeps the arms paired and the
McNemar contrast valid.

**Consequence for §4.2.** Commit-accuracy and the McNemar null are unchanged (a
crash contributes no commits; n=154 at 8-vs-8, p=1.00). Coverage gains a second,
honest denominator: trio 0.468 -> 0.493, no_adjudicator 0.391 -> 0.412,
researcher_only 0.237 -> 0.250, cooperative 0.404 -> 0.426 on n=148. Every
ordering is preserved, so no conclusion moves. The report should quote one
denominator and name it; the full-universe figures remain in the JSON as the
sensitivity. New tests `tests/test_exp40_analysis.py` (5) and 10 added to
`tests/test_coordinator_bug_fixes.py`.

### D67: the test suite cannot open the canonical database

`uv run pytest` used to write to `data/odmi.db`. The file's sha256 drifted
from the committed LFS oid on every full run, and the fix was a convention:
remember to `git checkout -- data/odmi.db` afterwards. That is the wrong
control for this file. It is the primary store, it is tracked, it holds the
frozen EXP-36 rows, and one unnoticed `git add -A` would commit a mutated
database over them. The same repo has already lost a 156-pair uncommitted
dataset to a `git checkout` on this path, so the recovery step is itself a
hazard.

The write came from the dispatch tests. `dispatch_subtrios._reset_fetch_stall_window`
and `_recent_fetch_timeouts` call `connect()` with no argument and run
`CREATE TABLE IF NOT EXISTS fetch_stage_timeouts` plus a `DELETE`; a traced
run recorded 1,084 opens of the canonical path, 1,081 of them through
`agents/tools/db.py:connect`.

Two layers, both in the new repo-root `conftest.py`, so nothing changes
outside pytest. First, a session-scoped scratch copy of the database (an
APFS clone where available, so the 330 MB costs nothing), with every module
constant that names the canonical file rebound to it before each test.
Tests that read real rows keep reading them; their writes are discarded.
Second, `sqlite3.connect` is wrapped to raise `CanonicalDatabaseAccess` on
the canonical path in any spelling, relative, absolute or `file:` URI,
read-only included. Anything the redirect misses fails loudly and names the
call rather than reaching the file.

The redirect only works if the path is read at call time, so `connect()`
and `ensure_prompt_version()` in `agents/tools/db.py`, and the four
`db_path: Path = DB_PATH` defaults in `scripts/run_researcher.py` and
`scripts/run_verifier.py`, now resolve `DB_PATH` inside the function
instead of binding it as a default argument. Behaviour is unchanged for
every caller; the constant is simply no longer frozen at import.

The remaining gap is a module first imported inside a test body, whose
constant the per-test scan has not seen. The five modules that own a DB
path are imported up front for that reason, and the guard catches the rest
by design.

### D68: a verifier stance is search direction plus verdict burden, and the frozen set has one auditable door

Three defects blocked EXP-42. The 2026-07-27 SPEC entry recorded the first
two as fixed. An audit on 2026-07-29 found none of the wiring in the code,
so they are recorded here with the state verified rather than asserted.

**A stance the implementation never had.** `run_verifier` called
`generate_adversarial_queries` unconditionally: the only branch on that
path was the EXP-14 `skip_web_search` policy. The corroborate prompt's step
4 told the verifier to search for support, so the cooperative arm was
handed counter-evidence and asked to corroborate from it. EXP-40's own
pre-registration claimed "step 4 flips the search direction", which nothing
in the code did. A verifier that searches one way and judges the other is
not a stance and measures no question that was asked, so the search
direction and the verdict burden now move together:
`verifier-corroborate` calls the new `generate_corroborative_queries`.

The EXP-42 prereg had specified wiring in the existing
`generate_confirmation_probes`. That was wrong on inspection and is
corrected in the prereg's change log. The probe generator is
absence-specific, opening "The Researcher has answered that some feature,
API, dataset, or policy instrument does NOT exist", and asks for queries
that would find that thing if it existed. It does not apply to a positive
claim, and on a negative claim it hunts the positive thing, which is
refutation. Wiring it in would have left the arm searching adversarially on
positive answers and refutationally on negative ones, the same chimera
renamed. The built replacement mirrors the adversarial generator's
shape-awareness in the opposite direction, so the arms still differ by
stance alone.

**Rigour parity.** Corroborate V2's preamble dropped disprove V4's "Vague,
paraphrased, or out-of-date evidence is grounds for rejection" with no
equivalent, so the corroborative verifier lacked a gate its comparator had.
The bias ran toward passing, which is toward the section 2.5 hypothesis, so
EXP-40's null was conservative and stands. V3 adds the corroborative mirror
("does not constitute corroboration") rather than disprove's wording, which
would import the opposing framing. Steps 1 to 3 stay byte-identical to
disprove V4 and a test now pins that rather than leaving it to inspection.

**One door, and it is logged.** The D47 guard had a single exemption,
`headline: true`. EXP-36 has used it and EXP-42 must not claim it, because
the headline flag is the receipt for the reported result. A second touch
now requires `heldout_second_touch`, a non-empty
`heldout_second_touch_justification`, every country in the run held-out,
and no headline claim. The justification is written to the run manifest and
the event log, so the disclosure survives alongside the rows it produced.
This is a door rather than a removed check: the flag alone fails preflight.

EXP-42's spec deliberately does not carry the flag. Dispatch stays blocked
until the second-touch call is made and the sign-off is named in the
justification. That call is Benjy's and his supervisor's, not an autonomous
one, and the freeze is burned for later tuning either way.

## Change log

| Date | Change |
|---|---|
| 2026-07-30 (EXP-42 COMPLETE: stance is equivalent on accuracy, unresolved on precision) | **All 1,144 held-out pairs run.** Stance-sensitive n = 1,111 after excluding 33 pairs decided by the D30 catalogue recompute, where the Verifier makes no LLM call and stance cannot reach the outcome (both arms commit on all 33 and agree on 32; they are guaranteed ties that would shrink the difference and make equivalence easier to declare than warranted). Finding them needed BOTH the `deterministic` and `unknown` model_version labels, since the two run epochs log the same path differently (D66) and matching one alone made arm A look as though it never used the catalogue. **Endpoints.** Coverage A 0.444 vs B 0.461. Commit accuracy on binary golds A 0.740 vs B 0.727. Negative-gold FPR over all 370 negative golds A 0.232 vs B 0.270, paired exact p = 0.065 on 18-vs-32 discordant. Committed-correctness paired exact p = 0.562 on 50-vs-57. Delivered accuracy A 0.353 vs B 0.361, **TOST against the pre-registered +/-0.05 margin p = 0.0001, EQUIVALENT**. **Reading.** Stance does not change how often the system is right, and that is now settled by an equivalence test rather than by a failure to reject, which is exactly what EXP-40 could not supply and what D68 flagged section 4.2 for over-reading. Stance does appear to change what the system asserts: the corroborative arm commits more and false-positives more on negative golds, the direction section 2.5 predicts, but at p = 0.065 that is not significant and must not be written as though it were. Sections 4.2 and 5.2 need revising, not deleting: 'the Verifier's stance does not matter' is now supported for accuracy and NOT supported for the negative-gold false-positive rate. Characterisation only, no adoption rule, production stays trio (D45). **Second touch of the D47 frozen set, authorised by Benjy on 2026-07-29 with NO supervisor sign-off on record**; the justification stored in the run manifest and event log says so in those words. The set is burned for later tuning. Owed in the dissertation limitations. **Run quality.** 0 deny-list violations, 0 agent crashes, 0 verifier failures; every commit carries a non-empty source URL and evidence quote; abstained pairs exhausted all 4 attempts against 1.56 for commits. Arm A's replayed FPR reproduces EXP-36's published 0.255 (0.253 pre-exclusion), validating the replay rule. **Four incidents, all recovered, no data lost:** a dispatch launched inside the CLI process tree died silently on a session restart (now detached, PPID 1, with a heartbeat supervisor); the 5-hour Claude window exhausted at 02:12 and killed two orchestrators (the 25-minute cooldown recovered it; the earlier stop-on-barren-sweep logic would have abandoned the battery at 62%); SE stalled 3 sweeps because the pre-dispatch catalogue warm dies in rdflib and exits before dispatching any pair, and `--no-warm-catalogue` was missing from `build_command`'s flag_map so setting it did nothing silently (added, with a regression test, after verifying arm A answered SE Quality through the agent pipeline too so skipping the warm is not a confound); 2 pairs duplicated because a final with no researcher row is invisible to the resume skip-set, both duplicates agree and analysis dedups on (question_id, country_code). Merged to canonical: `exp42_stance_heldout` 1,146 rows, `exp42_pilot_heldout` 111, `exp42_smoke_dev` 10; analysis reproduces off canonical. Tooling: `evaluation/exp42_analysis.py`, `evaluation/exp42_checkpoint.py`, `scripts/exp42_supervisor.py`. |
| 2026-07-29 (D68: EXP-42 build complete, dispatch still blocked; dissertation experiment inventory) | **The three EXP-42 blockers are built and tested (`83d193a`, 13 new tests, suite 914 pass / 13 skip against a real DB).** The 2026-07-27 entry below records two of them as fixed. They were not: an audit found `generate_confirmation_probes` reachable only from `evaluation/verifier_redesign.py`, `run_verifier` calling `generate_adversarial_queries` unconditionally, `verifier-corroborate` still registered at V2, and no `heldout_second_touch` anywhere in the tree. All three are now in code, with the state verified rather than asserted. Detail in D68. **One design correction:** the prereg specified wiring in `generate_confirmation_probes`; on inspection that generator is absence-specific ("the Researcher has answered that some feature ... does NOT exist") and hunts the positive thing, so it does not apply to a positive claim and is refutation on a negative one. Built instead as `generate_corroborative_queries`, a direction mirror of the adversarial generator with the same shape-awareness, which keeps the arms differing by stance alone. **Dispatch remains blocked by design:** the EXP-42 spec deliberately does not carry `heldout_second_touch`, so preflight still refuses all eight countries. With the flag and a justification added by hand the dry-run passes clean at 8 arms / 1,144 pairs / `--no-cache` on every arm / SE last, and the justification is echoed to the manifest and the event log. Arm A needs no dispatch and was recomputed here off the canonical exp36 rows: 526 of 1,144 commits (0.460), reproducing the prereg figure exactly, with trio at 636/1,144 (0.556) matching the dissertation's headline coverage. Outstanding before any dispatch: the replay adaptation in `evaluation/exp40_analysis.py`, the 392-hit seed-count preflight, and the resume-safe runbook (prereg items 5 to 7). **Dissertation, separately.** An inventory of Appendix C found 23 completed rows, all with results, and three completed experiments cited in the body but missing from the table: the all-Opus cost point (`exp36_model_opus`), the closed-book probe (`cb_heldout_20260725`) and the 94-case false-positive audit. Added in red with a `[CC]` note flagging three things to settle: the `exp36_model_opus` / `exp36_frozen_headline` number collision (still open, needs the D49 call), a coverage mismatch between §4.4 (Opus 29.5%, Sonnet 46.8%) and `docs/MODEL_COST_ACCURACY_LANDSCAPE.md` (30.1%, 50.0%), and §4.2/§6 naming the FP-audit judge as Opus 4.8 where both artefacts record `claude-opus-4-6`. The Appendix C heading promised a planned-experiments table that does not exist; per Benjy there should not be one, so the heading and the section-8 intro were corrected. EXP-35 (8 pilot finals) and EXP-33 (59 of 156) remain incomplete and uncited. |
| 2026-07-27 (EXP-42 registered; EXP-40's stance null found over-read) | **Audit of the corroborative-vs-adversarial result the dissertation leans on.** §4.2 states "the Verifier's stance does not matter" and §5.2 calls the paired test "perfectly null"; §5.2 also uses the stance swap to argue the Verifier's prompt difference has "negligible effect". None of that is licensed by EXP-40. McNemar p=1.00 on 8-vs-8 discordant pairs fails to reject a null; it is not an equivalence result, no TOST or margin was pre-registered, and §4.2's own line ("at this n only large effects are detectable, and a null reads as no large effect detected") contradicts the three stronger claims. Minimum detectable effect on EXP-40's 16 discordant pairs is ~7.3pp; the neg-gold FPR difference (17/78 vs 19/78) carries a CI of roughly ±0.13, so the data are compatible with the corroborative arm being materially worse. The defensible claim is the EXP-38/EXP-40 reconciliation (stance governs the verifier's own discrimination, J 0.41 vs 0.16, but washes out end to end because the D37 floor and retrieval bind system precision, per D45), not "stance does not matter". **EXP-42 pre-registered** (`docs/EXPERIMENTS_EXP42_STANCE_HELDOUT.md`, registry row `exp42_stance_heldout`, zero data rows at registration per R1) to settle it with power and on the right population: 1,144 held-out pairs, 909 binary golds, 370 negative golds against EXP-40's 154/78, cutting the minimum detectable effect to ~3.0pp and the FPR-difference CI to ~±0.06, with a TOST margin of ±0.05 fixed in advance. Two arms: A adversarial `no_adjudicator` replayed off exp36 at zero cost (verified yield 526/1,144 = 0.460, no pairs lost), and B corroborative live (~57.5k calls), dispatched as eight per-country sub-batches because the seed predicate pins a single scalar `condition_label`; these are one condition, not eight. A third live adversarial drift-control arm was drafted and cut on review: drift and run-to-run noise add discordance symmetrically while McNemar tests asymmetry, so the nuisance costs power rather than validity, and the arm would have spent ~10k calls plus 200 further pairs of frozen-set exposure to re-measure a configuration EXP-36 already characterises. The seeded (392, retrieval identical to arm A) vs unseeded (752, live retrieval) contrast is registered as a free diagnostic in its place, with the difficulty confound disclosed. **Three fairness defects found in the EXP-40 apparatus.** First, the "one variable is stance" claim is wider than documented: steps 1-3 of the two verifier prompts are byte-identical as claimed (verified by diff, 461/714/253 B), but corroborate V2's preamble drops disprove V4's "Vague, paraphrased, or out-of-date evidence is grounds for rejection" (`agents/prompts/verifier.py:269-270`) with no equivalent, so the corroborative verifier is missing a rigour gate its comparator has. The bias runs toward passing, i.e. toward the §2.5 hypothesis, so EXP-40's null is conservative and stands, but EXP-42 registers V3 restoring the corroborative mirror ("vague, paraphrased, or out-of-date evidence does not constitute corroboration") rather than the adversarial wording, which would import the opposing framing. Second, and more seriously, **the cooperative arm searches adversarially**: `generate_adversarial_queries` (`agents/verifier.py:628-630`, prompt at `103-125`) is shared and instructs the model to find evidence AGAINST the answer and, for binary questions, to "search for the opposite label", while corroborate V2 step 4 instructs the verifier to search for support. The corroborating verifier is therefore handed counter-evidence and asked to corroborate from it, and EXP-40's own prereg claimed "step 4 flips the search direction", which the implementation never did. An earlier draft of the EXP-42 prereg wrongly called this "the tighter one-variable design"; corrected. Fixed by wiring the already-written but harness-only `generate_confirmation_probes` (`agents/verifier.py:208`) into the cooperative path, with a production-readiness pass since it has never run outside `evaluation/verifier_redesign.py`. This widens the treatment to stance as a coherent construct (search direction and verdict burden moving together, since a verifier that searches one way and judges the other measures nothing); EXP-38's search-free replay already isolates the verdict rule alone, so the decomposition sits across the two experiments. Third, a predicted structural block on correct negatives (a corroborative verifier cannot positively establish an absence, and 370 of the 909 binary golds are negative) was tested against the EXP-40 rows and **refuted**: corroborate P(pass) 0.648 on negative researcher answers vs 0.647 on positive (Fisher p=1.00), correct negatives passed 44/62 (0.710) vs disprove's 49/64 (0.766) (p=0.55), commits on negative golds 27/78 vs 28/78 (p=1.00), and passes cite real independent evidence rather than defaulting. Neither stance has a negative-specific commit route: `absence_corroborated` and the tristate commit rule in `docs/VERIFIER_REDESIGN.md` were never implemented (0 code hits, 0 DB columns; that doc's header says as much), and D44 is a restriction confined to the Adjudicator path, so it never fires in cooperative mode. The one significant verdict difference is on `inconclusive` researcher answers (corroborate passes 0.147 vs disprove 0.514, p=0.0013), now pre-registered as the expected mechanism, with limited practical reach since an abstention cannot commit regardless of verdict. **Framed explicitly as a steel-man**, since Benjy asked for the corroborative arm to be optimised: arm B gets V3, aligned retrieval and a verified parse path while arm A stays frozen production, so a corroborative loss supports §2.5 far more strongly than EXP-40 did, whereas a corroborative win is confounded with tuning and may only be written up as "competitive when optimised". Both readings fixed before data. Secondary architecture-level contrast added, trio (3 agents) vs cooperative (2), unmatched by construction but the practically interesting one, with cost verified rather than asserted: 4.26 agent calls per pair against 6.30 on the matched dev battery, 32% fewer, the saving being entirely the Adjudicator since attempts per pair are 2.78 vs 2.81; the held-out saving should be nearer 15% because the Adjudicator fires on 0.55 of pairs there against 1.92 on dev. Seed coverage against exp36 is 392/1,144 (0.343), not random (761 of 1,158 attempt-1 rows were `inconclusive`), so the seeded subset is pre-registered as a paired subgroup and the full battery stays primary; exp36 stored `condition_label` as the country code, so eight per-country arms are required or the seed silently matches nothing. Deny-list verified pre-retrieval at three layers plus the parametric-emission scrub (`agents/verifier.py:388-420`), which matters more here than anywhere else since a confirmation-seeking verifier reaching ODMI's own answers is the worst-case leak. **Not dispatched, and blocked on a decision rather than on build.** The D47 freeze is enforced in code (`scripts/run_experiments.py:170-174`); the only exception is `headline: true`, which EXP-42 must not claim, since EXP-36 is the headline and a false flag would corrupt the receipts. The guard was left in place. Proceeding needs Benjy's and his supervisor's call on a second touch of the frozen set, then an auditable override (`heldout_second_touch` plus a logged justification), not a removed check. The spec is otherwise dry-run clean. |
| 2026-07-26 (D67: suite locked out of the canonical DB) | Closed the hazard the D66 entry noted in passing: `uv run pytest` mutated the git-tracked `data/odmi.db` on every run, and the only control was remembering to restore it. Traced the writes to `dispatch_subtrios._reset_fetch_stall_window` / `_recent_fetch_timeouts`, which call `connect()` bare and create-then-clear `fetch_stage_timeouts` (1,084 canonical opens in one traced suite run, 1,081 via `agents/tools/db.py:connect`). New repo-root `conftest.py` adds a session-scoped scratch copy of the database with every canonical-DB module constant rebound to it per test, plus a `sqlite3.connect` wrapper that raises `CanonicalDatabaseAccess` on the real path in any spelling. To let the redirect reach default callers, `connect()` / `ensure_prompt_version()` and four `db_path: Path = DB_PATH` defaults in `scripts/run_researcher.py` and `scripts/run_verifier.py` now resolve `DB_PATH` at call time rather than binding it at import; no caller behaviour changes. Verified by sha256 across a full run: `213ff498...` before and after, `git status --short data/odmi.db` clean, where the same run beforehand left it at `4aeb0a45...`. Suite 901 pass, 13 skip, 0 fail on the rebased tree (the 3 `test_catalogue_adapter_rdf.py` failures present while this work was done were fixed upstream by `840beff`). New tests `tests/test_db_guard.py` (14). |
| 2026-07-26 (D66: three logging defects fixed) | Checked the §4.2 ablation ladder for Sonnet-5 contamination and cleared it: all four arms are `claude-sonnet-4-6`, replayed off `exp34_retrieval_strategy_s46` / `wide_only`, not the banned `exp28_arch_ablation` arms (which do still sit in canonical, 155-156 pairs each, and must not be read; the planned `exp28_s46_rerun` never got past its 8-pair pilot). The check surfaced three logging defects, fixed here with tests first. (1) `run_coordinator.py` skipped the Researcher receipt when an attempt produced no output, which renumbered the retry trail and cost 17 exp34 pairs their `retry_count=0` row; every failed attempt is now persisted with `failure_mode` set, leaving resume and adjudication behaviour untouched. Historical rows are unrecoverable, so `attempt1_gap_pairs()` reports the gap and the bound is disclosed (0.237 -> 0.244 commit rate under an earliest-attempt fallback, conservative in direction). (2) The `model_version` fallback wrote `unknown` for any usage-less row; 49 seeded EXP-40 Researcher rows now read `seeded_replay` and 48 deterministic catalogue-recompute Verifier rows (33 in the EXP-36 headline) now read `deterministic`, which makes the deterministic route countable for §3.5. Historical values left alone deliberately. (3) `exp40_analysis.py` recoded 8 `agent_failure` pairs as abstentions, so `n_failed` read 0 and a crash counted as a decision to decline; crashes now survive the mapping and `completed_only()` gives coverage on the 148 pairs that completed in every arm. §4.2 consequence: commit-accuracy and the McNemar null unchanged, coverage rises uniformly (trio 0.468 -> 0.493, no_adj 0.391 -> 0.412, researcher_only 0.237 -> 0.250, cooperative 0.404 -> 0.426), all orderings preserved. `evaluation/results/exp40_analysis.json` regenerated. Tests: 20 pass across `tests/test_exp40_analysis.py` (new, 5) and `tests/test_coordinator_bug_fixes.py` (10 added); full suite 881 pass, 13 skip, with 3 pre-existing `test_catalogue_adapter_rdf.py` failures unrelated to this work (`dcat_rdf.py:44` TypeError, present on a clean tree). Separately noted: running the suite mutates `data/odmi.db`, so the worktree copy was restored and is not part of this commit. |
| 2026-07-21 (EXP-41 pre-registration; EXP-40 rows recovered) | Audit found the EXP-40 cooperative arm had zero rows in all 46 `odmi.db` copies on disk and no `experiments` registry row anywhere; `evaluation/exp40_analysis.py --db data/odmi.db` returned n=0 for all four arms while still printing `McNemar p=1.000`, the p-value the dissertation reports, so the documented reproduction path yielded a plausible null from an empty database. The rows were then recovered from an orphaned Git LFS object (one prune away from loss) and committed as SQL dumps under `data/recovery/`; verified independently here by restoring them into a copy of canonical and reproducing `evaluation/results/exp40_analysis.json` byte for byte, all four arms, n=154 at 8-vs-8, p=1.00. §4.2 needs no re-run. Outstanding: canonical `data/odmi.db` has not yet been restored from the dumps and still carries the pre-EXP-40 CHECK. EXP-41 (D65, `docs/EXPERIMENTS_RUN_STABILITY.md`) accordingly narrowed from 624 pairs to 468: three fresh incumbent-trio replicates over the 156-pair dev battery, closing §4.7's open second Reproducibility condition and giving §4.2 an empirical noise floor for its ladder. New tooling: `scripts/purge_search_cache.py` (`--no-cache` disables cache reads but not writes, so the cache must be archived and purged before every run, not once, and the existing purge clears only the held-out eight), `scripts/gen_exp41_specs.py` (three specs from one FROZEN_KNOBS dict), `scripts/register_exp41.py`, `tests/test_exp41_prereg.py` (14 pass). Six further leak carriers found and controlled; two would have voided the experiment silently, since replicates sharing an `experiment_id` are skipped outright by `finalised_pairs` and share evidence via `_find_resumable_researcher`. All three dry-runs preflight-pass at 156 pairs with `no_cache=True` and all 21 knobs on the command line. Not dispatched: awaiting Benjy's review. |
| 2026-07-17 (held-out false-positive audit, n=83) | Generalised the NL FP audit (2026-06-25 entry) to the eight D47 held-out countries that carry the frozen EXP-36 headline, at Benjy's direction (a post-hoc disagreement audit for the D22 staleness band, not a config experiment: no swarm run, no knob change, canonical DB read-only). New `evaluation/heldout_fp_audit.py` runs the same two-pass method as NL over the frozen stored evidence, same `claude-opus-4-6` judge, with the pass-1 (charitable: genuine_error / definitional_gap / defensible_or_stale_gold) and pass-2 (adversarial advocate: swarm_over_read / ambiguous / gold_wrong) rubrics imported verbatim from `nl_fp_audit.py` / `nl_fp_audit_adversarial.py`, so the two audits are directly comparable. All 83 committed binary false positives (swarm yes / gold no): BA 7, BE 4, BG 6, FI 17, HR 4, ME 19, MK 16, SE 10. Automated verdicts: charitable 17/83 genuine error, 60/83 definitional gap, 6/83 defensible/stale gold; adversarial 60/83 over-read, 22/83 ambiguous, 1/83 gold_wrong. The single `gold_wrong` (SE I27) and all six `defensible_or_stale_gold` were then checked by hand against the actual stored snippets (`evaluation/results/heldout_fp_audit_verification.md`); none holds as a swarm win. SE I27's advocate fabricated Sweden-specific figures (a Lantmäteriet 10-21bn SEK/yr estimate, an SSE/Vinnova study) that are absent from the one stored snippet (a 2020 entryscape.com blog citing the generic pan-EU "Economic Impact of Open Data" report); the swarm's real evidence is an over-read of a Europe-wide report, so the gold "no" stands. Evidence-checked headline: **0/83** false positives where the swarm is right and ODMI wrong, matching NL 0/22. Genuine swarm-error rate is 20% (vs NL ~0-9%): the held-out countries are harder (thinner, lower-resource portals) so the swarm over-reads more, but the errors are swarm-side, not stale gold. Consequence: the D22 staleness band on the EXP-36 held-out commit-accuracy is negligible, so match/differ is a fair headline metric. Method caveat recorded in the verification note: an adversarial advocate prompted for the best case will import facts not present in the shown snippets, so `gold_wrong` / `defensible_or_stale_gold` are human-review flags, not conclusions. Artefacts: `evaluation/heldout_fp_audit.py`, `results/heldout_fp_audit.jsonl` (83 rows), `_summary.md`, `_verification.md`. Committed `d003ae5` plus this entry. |
| 2026-07-16 (supervision addendum: freeze-gate bug; EXP-36 ownership) | `scripts/assert_freeze.py` bug found and fixed: the `_git()` helper's `strip()` ate the leading status column of the first `git status --porcelain` line, so ` M data/odmi.db` (the explicitly allowed DB write) read as dirty and `run_exp36.sh` aborted every resume after the run had mutated the DB - the one-command launcher could start a fresh run but never restart one. Fix: `rstrip(chr(10))` only; validated against the frozen exp36-run worktree (FROZEN with the DB modified, HEAD at tag). Operational note: the second window-exhaustion stall (finals 672/1,144) was resumed not by this session's supervisor (its relaunches hit the gate bug) but by the haiku-sonnet-opus-comparison window, which drives per-country night specs through `run_experiments.py` directly and owns the EXP-36 resume; this session's auto-relaunch supervisor was stood down in favour of a passive completion watch to avoid cross-window double-dispatch. The 5-hour Claude window, not the monthly cap, is the binding constraint (confirmed by Benjy 2026-07-16). |
| 2026-07-16 (EXP-38 result; EXP-39 registered; EXP-28 re-run + EXP-35 pilot; EXP-36 stall + supervisor) | **EXP-38 done (new):** corroborative vs adversarial verifier framing over the frozen EXP-11 150-candidate ladder, search-free, `claude-sonnet-4-6`. Disprove re-baseline J 0.41 (reproduces the June 0.41 to two decimals on the D62 transport) vs new `verifier-corroborate` J 0.16 via the predicted sensitivity collapse (0.72 -> 0.32); corroborate halves the false-rejection rate (0.31 -> 0.16), reported as the trade. Supplies the missing direct evidence for the dissertation section 2.5 adversarial-beats-corroborative claim; prereg + result `docs/EXPERIMENTS_CORROBORATE.md`. **EXP-39 registered and part-run:** language-comprehension probes without DeepL (budget): argostranslate (local OPUS-MT) replaces it, fixing the Claude-translates-for-Claude circularity; Part A swap replay (en->fr control / bg / sq over the English-evidence ladder subset) pending translations; Part B within-country english-vs-non-english evidence contrast ran on main rows (only NO has mass both sides: 0.93 vs 0.83 commit-acc, MH OR 2.29, CIs overlap; powered read waits for the EXP-36 rows). **EXP-28 re-run + EXP-35:** re-pinned under clean id `exp28_s46_rerun` on `wide_only` (deviation from the July `narrow_then_wide` pin, reasons + frontier-control consequences in `docs/EXPERIMENTS_EXP28_RERUN_NOTE.md`), EXP-35 folded into the same 4-arm spec; 4-arm 5% pilot dispatched (first attempt died on a missing worktree `.env`, the exact failure mode the EXP-36 runbook documents; fixed, resumed). EXP-33 spec written (`exp33_tiered_s46.json`), queued behind the ladder. **EXP-36 operational:** the headline run exhausted the Claude window at 569/1,144 finals and its dispatch died; relaunched via `run_exp36.sh` (resume-safe) and a Python supervisor now auto-relaunches on window recovery until 1,144 (probes the cloaked LLM path, 2-OK-streak + 20 min cooldown guards). EXP-36 post-run analysis pack built + tested (`evaluation/exp36_analysis.py`, 11 unit tests, smoke on voided exp21 rows): balance-aware headline, strata, RQ3 stratum contrast, calibration/ECE, risk-coverage sweep, D22 bracket. Registry ids `exp38_verifier_corroborate` / `exp39_language_probe` / `exp28_s46_rerun` added (worktree DB). Flagged for reconciliation: `exp36_model_opus` (all-Opus-4.8 point, 157 finals, canonical DB) collides with `exp36_frozen_headline` on the EXP-36 number and declares the void `trio_s5` control (D59) — its valid 4.6 comparator is EXP-34's baseline arm or a bridge, per the rerun note; needs a D49 call before write-up. |

| 2026-07-13 (D64: EXP-31 discarded, EXP-36 fresh frozen headline) | See D64 above. Discarded `exp31_frozen_headline_v2` (Sonnet-5-pinned, never ran); minted EXP-36 (`exp36_frozen_headline`) with a fresh pre-registration (`docs/EXPERIMENTS_EXP36_PREREG.md`) and spec (`evaluation/specs/exp36_frozen_headline.json`, eight per-country sub-batches, dry-run clean, every knob pinned). **wide_only adopted (EXP-34, `exp34_retrieval_strategy_s46`, 4.6):** NL adoption rule met (neg-gold FP 17->14 paired, commit-acc 0.62->0.67), pooled commit-acc 0.679->0.733 with no country regressing; FP-reduction not significant at full power (pooled McNemar p=0.727), so no general FP claim. Code default flipped `narrow_then_wide`->`wide_only` across dispatcher/coordinator/researcher, byte-identical tests updated; narrowing is inert on the held-out 8 (no trusted lists) so the headline runs wide everywhere. **Coordinator data-integrity fixes, reconciled against the 2026-07-12 entry below on merge (same B1-B4 audit, independent fixes):** B1 (`invalid_answer_shape` retries rather than commits junk) was fixed on both branches; this branch's version is complete (handles retry and final-attempt exhaustion via adjudicate-on-prior-attempts), the 2026-07-12 branch's version only handled retry, so its now-dead duplicate block was removed on merge. B2 (a final-attempt Verifier `schema_invalid` adjudicates on the answer in hand instead of dropping the pair) is new on this branch only. B3 (empty-denominator catalogue metric) was fixed on both branches at different layers (this branch: `metrics.py` returns `NOT_APPLICABLE`; 2026-07-12 branch: `compute.py` falls back to web search) and both are kept as complementary. B4 (dashboard drops the cut Sonnet 5) was fixed on both branches for `1_Run_Console.py`; the 2026-07-12 branch also dropped it from `6_Models.py`, which this branch's prereg had deliberately kept as a labelled D59 comparison — unresolved discrepancy, flagged to Benjy rather than picked unilaterally on merge. New tests `tests/test_coordinator_bug_fixes.py`; full suite re-verified after merge. ARCHITECTURE.md ledger and FINAL_PROGRAMME gate 5 corrected to 4.6 / EXP-18 / EXP-34. Remaining before dispatch: ARCHITECTURE.md freeze tag, canonical `exp36` registry row + void of `exp31_v2`, deny-list and held-out cache audits, all on a fresh copy of the purged canonical DB. |
| 2026-07-12 (pre-EXP-31 audit, Phase 0) | D62 registered (had shipped in code on 2026-07-10, `b6f5eb6`, with no SPEC entry until this audit); D44 backfilled (shipped 2026-06-10, `70ed63c`/`88c6c61`, also missing); D61 annotated as superseded-in-part by D62; the D42 numbering collision flagged in place (not renumbered, ~10 files cross-reference both). Two bugs fixed: `invalid_answer_shape` now retries instead of silently committing an off-schema answer as a guaranteed differ (`run_coordinator.py`); a catalogue metric with a zero denominator now falls back to web search instead of confidently emitting the bottom percentage band at 0.95 confidence (`compute.py`). Dead `claude-sonnet-5` removed from the two dashboard model pickers. `exp34_retrieval_strategy_s46` registered in the (worktree-local) `experiments` table — was unregistered, would have hard-failed runbook preflight gate 6. EXP-10 floor-sweep replay re-run at 0.65/0.60/0.55/0.50 on MT (n=60, free, no dispatch): **0.65 held** — 0 pairs recover at 0.60 (identical to 0.65), 0.55 recovers 3 at 0.67 precision and 0.50 recovers 8 at 0.75 precision, both under the 0.80 adoption bar; NL (n=3) too small to inform. Purged ~11,014 SERP + ~1,928 fetch + ~29,104 snippet cache rows keyed to the exact queries/URLs the voided `exp21_frozen_headline` and `expC_held_neg_licence` held-out runs touched (worktree DB only; backed up first), closing the stale-cache-reuse risk flagged for EXP-31. All DB changes are on this worktree's copy of `data/odmi.db` and are **not** committed; the canonical checkout needs the same registration + purge run before EXP-34/EXP-31 dispatch from there. Superseded by the 2026-07-13 canonical purge (see the entry above D64, run against `data/odmi.db` directly: 3,962 fetch / 11,014 SERP / 29,104 snippet rows, backup `data/odmi.db.bak-preheldoutpurge-20260713-153926`). |
| 2026-07-12 (D63: ablation table via replay; underlying data subsequently lost) | See D63 above. Ablation table (`no_adjudicator`/`researcher_only`) filled by zero-cost replay of the existing `trio_s46` run rather than a ~300-pair fresh dispatch; replay validated on 9 live-dispatched pairs (8/9 exact match, one miss traced to a cross-arm cache-sharing gap, not a logic error). The underlying 156-pair dataset was subsequently destroyed by an accidental `git checkout -- data/odmi.db` in the source worktree (discarded uncommitted work, no recovery path); this entry documents the finding from the in-session analysis, not a re-queryable result. New eval specs preserved: `exp28_ablation_s46_full.json`, `exp28_ablation_s46_20pct.json`, `exp28_ablation_live_check.json`, `exp29_s46_10pct_pilot.json`/`_25pct_`/`_50pct_`/`_100pct_cumulative`/`_100pct_final.json` (the incremental dispatch trail and the canonical 156-pair pair list for this experiment). |
| 2026-07-12 (post-D62 "regression" resolved as comparator artefact) | The EXP-29 4.6 battery (156 pairs, `trio_s46`, D62 user-turn transport, run 2026-07-10..12) looked like a commit-accuracy regression against each pair's most recent pre-July result (cov 0.46 -> 0.56, acc 0.76 -> 0.64). Root cause is the comparator rule, not the transport: the config-blind "most recent June row" gave all 52 NL pairs the late-June Opus-4-6 arms (expA/B/C; NL cov 0.46-0.60, acc 0.71-0.82) as their baseline, while Sonnet-4-6 has always run NL at cov 0.81-0.92 / acc 0.56-0.64 (eight June arms). Holding the comparator at `claude-sonnet-4-6`: June cov 0.603 / acc 0.646 vs now 0.559 / 0.645 (n=136, per-country flat, Wilson intervals overlapping). Folding bug, calibration drift and same-evidence verdict flips all ruled out (folded prompt dumps clean with the 0.6 floor and abstention rules intact; committed-answer confidence 0.733 vs 0.743, medians equal; 28 of 33 answer divergences cite different evidence, transitions symmetric). Script: `evaluation/exp29_transport_regression_check.py`; write-up in PROJECT_LOG 2026-07-12. Rule going forward: pre/post deltas compare like-for-like configs, model above all. Separately, the sleep/wake search hang (~26 pairs stuck at `search_start`, no error trail) got a 45s wall-clock guard on the Serper call (`SerperDeadlineError`, daemon thread - OS DNS resolution blocks before httpx's 20s timeout applies) and `dispatch_subtrios.py` now logs unknown child exit codes with a stderr tail instead of dropping them. |
| 2026-07-10 (closed-book baseline) | New dev-only probe `evaluation/closed_book_baseline.py`: with retrieval disabled, what share of the 2025 answers does bare `claude-sonnet-4-6` (D59) reproduce from parametric memory? No existing `pipeline_mode` arm approximates this (`researcher_only` still searches). Universe = 20% of the full dev set, dimension-stratified within NL/MT/NO/FR/AL, seed 20260709, 145 pairs; rows in `closed_book_answers` (full prompt + raw response for replay), `--db` targets the canonical DB, resumable. Run `cb_20260709` (£0.33, user-turn transport): match rate **0.493** vs an always-`yes` majority-class floor of **0.681** - the bare model scores BELOW the trivial floor, so it is not carrying the 2025 answer key (contamination bound low; replaces the "structurally impossible" overclaim with a number). Well-calibrated (self-report known=true 0.877, known=false 0.177; abstains 22.8%); weakest on Quality (0.267) and `change` golds (0.190). RQ1 head-to-head on the 69 cb pairs that have a main-run (`experiment_id IS NULL`) final: swarm 0.567 vs closed-book 0.478 (+0.089 retrieval gain), but both sit under this yes-heavy subset's 0.739 always-yes floor because both abstain - which is why the definitive RQ1 read belongs on the class-balanced 156-pair battery (majority floor ~0.5), not the natural-distribution sample. |
| 2026-07-10 (freeze-gate free items cleared) | Cleared the five zero-token freeze-gate items (`docs/EXPERIMENTS.md` gate table 1/2/4/5/6); only EXP-34 (item 3) and the D61 `system`-only verification call remain before the config can be frozen and EXP-31 dispatched. **EXP-19 (verifier counter-search, `analyze_phase1.py`):** keep `always`, config not flipped. The pooled rule mechanically favours `never` (acc 0.67 vs 0.63, FPR 0.30 vs 0.41, cheaper) but the never arm under-finalised on AL (5 vs 26 pairs), so the pooled marginal is composition-confounded by survivorship on the hard thin-web country; within-country never wins NL (0.71 vs 0.60) but loses MT (0.40 vs 0.70, FPR 0.67 vs 0.50) and is untested on AL, paired McNemar null (n=38, p=1.00). Inconclusive on the multi-country flip; keep `always`, consistent with EXP-14. **EXP-20 (retry chaining, `chaining_analysis.py` + `analyze_phase1.py`):** keep `baseline`, chaining not promoted. Against EXP-20's four-part promotion rule: bal_acc up (0.355 vs 0.320) but FPR not flat (0.387 vs 0.346, +0.041) and McNemar not significant (n=48, p=0.500), calls/resolved +7.5% (within +10%); two of four fail. The looser EXP-7 non-inferiority framing in `chaining_analysis.py` prints "passes" but does not govern. Result `evaluation/results/chaining_exp20_chaining_committing.json`. **EXP-18:** keep r5 (r10 rested on one NL run at +17% cost, never confirmed multi-country). **EXP-C / D50:** defer neg_licence, keep the full Researcher prompt. **Housekeeping:** SE catalogue route configured + verified (sparql on dataportal.se, 2026-06-10, D24-compliant); deny-list/leakage audit clean (244 committed pairs, 1 benign bundesregierung strategy-page candidate, matches prior baseline); resume behaviour verified (38 dispatch/resume tests pass). ARCHITECTURE.md freeze tag deliberately NOT yet applied. Net effect: no production config knob flips; EXP-31 dispatch remains gated on EXP-34 (re-pinned to 4.6) and the D61 verification call. All analyses zero-token, read-only against the worktree DB. |
| 2026-07-09 (pre-July transport restored, D61) | D61 added, completing D59: the July transport change (D55) is removed so the baseline matches the validated June runs exactly. Root cause was proxy-side, not the model: CLIProxyAPI 7.2.45's "cloak" feature disguises non-Claude-Code clients and rewrites the `system` prompt, so the D59 model revert left the July transport active and the 2026-07-09 pilot ran on the wrong config (Malta coverage 0.35 vs June 0.72; NL over-committing) and is discarded as a baseline. Fix: (1) `disable-claude-cloak-mode: true` in `cliproxyapi.conf` (backed up; 429-not-401 after the flip confirms Max auth still works), (2) reverted the D55 user-turn folding in `llm.py` to the pre-July `system`-param call shape (no test pinned the folding; 19 llm/model tests pass). Verification owed before any run: one `system`-only call must be honoured end to end once the Max quota recovers from the pilot's rate-limit cooldown. No experiment dispatches until that passes. |
| 2026-07-09 (deny-list gap closed, D60) | D60 added, extending D24: the `BLOCKED_PATH_FRAGMENTS` entry `/open-data-maturity` (leading slash) let a prefixed slug through `is_blocked`'s substring test, so `/article/2025-open-data-maturity-highlights-...` (a Malta national-portal page reporting the 2025 ODMI results) was used as a Researcher source and reached one finalised pair without the D24 audit flagging it. Broadened the fragment to bare `open-data-maturity` (removed the two subsumed longer variants); verified it blocks the leak and the europa.eu/croatia page while still passing generic open-data slugs, `data.gov.mt` datasets, Wikipedia `Open_data_*`, and the eur-lex HVD regulation. Two regression tests added, the pinned-fragment test updated; 41 deny-list tests pass. Found in the 2026-07-09 pilot pre-flight; 1 pilot pair retro-flagged and excluded/re-run. `check_data_leakage.py` inherits the fix as the EXP-31 pre/post gate. |
| 2026-07-09 (revert to Sonnet 4.6, D59) | D59 added, superseding D56: the official default reverts `claude-sonnet-5` -> `claude-sonnet-4-6` after EXP-28's `trio_s5` control (production architecture, model-only change) collapsed coverage to 0.27 (Malta 0.12 vs June 4.6 0.72) at ~3x cost, running retries to exhaustion and abstaining below the 0.65 floor. Reverted `DEFAULT_MODEL` (`agents/tools/llm.py`) and the `_read_default` fallback (`scripts/dispatch_subtrios.py`); reordered dashboard `MODEL_OPTIONS` so 4.6 is default-selected, 5 retained as a labelled comparison; set `model_defaults` to 4.6 for all three roles in the canonical and worktree DBs via the new idempotent `scripts/set_default_model.py`. Whole stack (incl. picker, which falls back to `DEFAULT_MODEL`) returns to 4.6. Sonnet 5 pricing row and `_rejects_temperature` retained. Caveat recorded: this reverts the model, not the D55 transport (instructions still travel in the user turn for all models), so the first 4.6 run is the model-vs-transport test; and 4.6 availability through CLIProxyAPI is unverified until the proxy re-authenticates (it was returning `auth_unavailable` at decision time, swarm idle since 2026-07-03). EXP-31..35 move to 4.6; the Sonnet 5 EXP-28 rows become a labelled characterisation. 34 model-related tests pass. |
| 2026-07-02 (EXP-35 pipeline mode built) | The `researcher_self_verify` pipeline_mode (the EXP-35 engineering precondition) is built: the Researcher answers as normal, then one self-critique call runs on the same model the Researcher attempt used, under the self-addressed disprove framing, with no independent counter-search (the EXP-14 `never` policy) and no Adjudicator ever. Upheld commits as `accepted_researcher_self_verify`; a rejection re-enters the existing `VerifierFeedback` retry path; exhaustion abstains as `abstained_researcher_self_verify` via the D54 finaliser. D35 abstention retries and the D37 0.65 floor are untouched, and trio / no_adjudicator / researcher_only are byte-identical (the new branches only activate on the new mode). Prompt registered as `phase2_verifier_disprove_self_critique` v1, a third `disprove_variant` alongside default/structured, so `prompt_versions` receipts hold. `phase2_final` CHECK widened via `scripts/migrate_self_verify_statuses.py` (two new statuses; owed against the canonical DB after merge). 5 new tests in `tests/test_pipeline_mode.py`; 772 pass. Spec written to `evaluation/specs/exp35_self_critique.json` (single arm `self_verify_s5`, the EXP-28 156-pair battery verbatim, all four models pinned `claude-sonnet-5`, budget_calls 8000 sized from EXP-28's observed ~51 calls/pair); dry-run preflight passed. Not dispatched. |
| 2026-07-02 (D57: held-out void + final-report experiment programme) | D57 added: prior held-out exposure (exp21 partial 301 finals on FI/HR/SE 2026-06-24; expC_held_neg_licence 627 finals on all eight 2026-06-27/28) voided for reporting; the headline run re-registered as `exp31_frozen_headline_v2` with eight per-country sub-batches and eight explicit freeze gates. EXP-31..35 pre-registered in `docs/EXPERIMENTS_FINAL_PROGRAMME.md` + the `experiments` table (headline v2; all-Haiku cost point vs EXP-28 trio_s5 control; tiered Haiku-researcher/Sonnet-5-checker per D18; EXP-23 retrieval-strategy redo on Sonnet 5, config-changing so it blocks the freeze; single-agent self-critique pipeline_mode completing the EXP-28 ladder and answering the "why not one self-critiquing agent" probe). EXP-9 closed as stalled and superseded by EXP-32/33; EXP-8 formally parked. Cost analyses rebuilt over live data (`evaluation/cost_report.py`, SVGs in `docs/figures/`), replacing the June Malta-batch numbers. |
| 2026-07-03 (D58: 503 auth_unavailable handled cleanly) | D58 added: a CLIProxyAPI 503 `auth_unavailable` (shared Claude Max auth-file pool exhausted under concurrent-window load) was crashing the coordinator subprocess uncaught mid-stage, silently orphaning `subtrio_status` rows with no `phase2_final` write — found live when the `researcher_only_s5` EXP-28 arm came back unhealthy (finalise_rate 0.353). `AuthUnavailableShutdown(RateLimitedShutdown)` added to `agents/errors.py`; `agents/tools/llm.py::call_for_structured` catches `anthropic.InternalServerError` alongside the existing `RateLimitError` catch and raises it; `scripts/run_coordinator.py` records an honest `final_failure_reason` (`auth_unavailable` vs `anthropic_rate_limit`). Reuses the whole 429 shutdown contract via subclassing, so `dispatch_subtrios.py`/`run_experiments.py` needed no changes. Verified live against the real proxy under load, not just mocked. 3 new tests, 770 pass. Mistral call path (EXP-9) knowingly left with the same gap, out of scope. |
| 2026-07-02 (Sonnet 5 default, code-level) | D56 added: `DEFAULT_MODEL` flipped `claude-sonnet-4-6` -> `claude-sonnet-5` in `agents/tools/llm.py`, `scripts/dispatch_subtrios.py::_read_default` fallback, and the dashboard `MODEL_OPTIONS` lists (Run Console, Models page), by Benjy's direct instruction rather than the EXP-29 pre-registered gate. Canonical DB `model_defaults` had already been updated by a parallel session the previous night; this lands the matching code change. 767 tests pass. |
| 2026-07-01 (overnight: EXP-28/29 + Claude 5 transport + audit tools) | D54 and D55 added. **D54**: `pipeline_mode` architecture-ablation knob (trio / no_adjudicator / researcher_only) threaded coordinator -> dispatcher -> orchestrator flag_map, with the `phase2_final` CHECK widened via `scripts/migrate_pipeline_mode_statuses.py` (three new terminal statuses; owed against canonical DB after merge) and 8 new tests. EXP-28 (architecture ablation ladder, 156-pair dev battery MT60+NL52+AL44, 78 negative golds, Sonnet 5 pinned) and EXP-29 (Sonnet 4.6 whole-stack contrast, adoption rule declared) pre-registered in `docs/EXPERIMENTS_ARCH_ABLATION.md` + the `experiments` table and dispatched overnight via the orchestrator (`evaluation/runs/exp28_arch_ablation_20260701/`). **D55**: CLIProxyAPI 7.2.45 (restarted to expose `claude-sonnet-5`) replaces the API `system` param with the Claude Code system prompt, silently discarding all agent instructions; instructions now travel in the user turn (`<instructions>` block), Claude 5 calls omit `temperature`, text blocks are joined explicitly past thinking blocks, and structured-call retries run at 4x budget on a `max_tokens` stop. Early-run verifier collapses (4 pairs, pre-fix) had their `phase2_final` rows deleted for re-run on fixed code. New analysis tools: `evaluation/leakage_fingerprint_audit.py` (FM-14 content-level answer-key audit; main results 244 committed pairs -> 1 benign candidate at >=8 shared words) and `evaluation/risk_coverage.py` (D37 selective-prediction sweep + dependency-free SVG; main results n=368: floor 0.65 -> coverage 0.620 at strict precision 0.904, floor 0.70 -> 0.473 at 0.960). Report work: `docs/REPORT_DIRECTION_MEMO.md` (engineering/adversarial reframe, verified numbers) and red-text scaffolding edits in `~/Downloads/Preliminary Report - Claude overnight edits.docx`. |
| 2026-06-29 (human_required -> unsupported) | D53 added: the third `LanguageRoute` value is renamed `human_required` -> `unsupported` (the route when neither native reading nor DeepL handles a source language; the pair then abstains, no human-translation stage). Never set in any logged run (all `language_route_used` rows are `native`), so a clean rename with no data migration and no legacy value retained. Touches `agents/models.py` (`LanguageRoute`), the `scripts/setup_sqlite.py` `language_confidence.routing_decision` CHECK, and `AGENT_DESIGN.md`. The empty canonical `language_confidence` table had its CHECK rebuilt in place. Housekeeping: the two D51/D52 canonical pre-migration backups were deleted after the migrations verified. 759 tests pass. |
| 2026-06-29 (escalated_* -> abstained_*) | D52 added: the abstention terminal statuses are renamed `escalated_captcha` -> `abstained_captcha` and `escalated_adjudicator` -> `abstained_adjudicator`. The system has no human-review stage; a pair commits an answer or abstains, and an abstention is terminal (the old `escalated_*` names implied a human queue that was never built). Supersedes the D51 note that `escalated_adjudicator` would stay. Touches `agents/models.py` (`TerminalStatus`), `scripts/run_coordinator.py`, the `scripts/setup_sqlite.py` CHECK (admits `abstained_*`, retains `escalated_*` as legacy), the dashboard (Home "Human queue" widget -> "Abstentions" view; Results/Run Console drop the "human" framing), and the evaluation scripts (`adjudicator_commit_policy.py` `.startswith` widened, `abstention_taxonomy.py` coalesces both). KNOWN_GAPS gap #3 (human-queue CSV writer) closed as not-a-gap; `flag_review` and the D22 disagreement glance kept (methodology, "human" dropped from prose). New `scripts/migrate_terminal_status_to_abstained.py` converts 313 `phase2_final` rows (+336 `subtrio_status` mirrors) to `abstained_adjudicator` (verified on a copy: 2,759 rows preserved, idempotent); owed against the canonical DB after merge. 759 tests pass. |
| 2026-06-29 (escalate_human -> abstain) | D51 added: the Adjudicator's fourth verdict is renamed `escalate_human` -> `abstain`. No human is ever in the loop, so an unsettleable case is an abstention (finalises `inconclusive` under the D37 floor; pair-level terminal status `escalated_adjudicator` unchanged). Label-only: meaning, the 0.6 auto-promotion floor, answer space and absence-of-evidence rule all unchanged. Touches `agents/models.py` (`AdjudicatorVerdict`), `agents/adjudicator.py` (`promoted_to_abstain` telemetry), the registered prompt (standard v5 -> v6, free arm v2 -> v3), `scripts/run_coordinator.py`, the `scripts/setup_sqlite.py` CHECK (admits `abstain`, retains `escalate_human` as legacy), and the evaluation scripts (coalesce the legacy string). New `scripts/migrate_escalate_human_to_abstain.py` converts the 313 canonical `escalate_human` rows to `abstain` (verified on a copy: 1,190 rows preserved, idempotent); owed against the canonical DB after merge, not committed from a worktree. 759 tests pass. |
| 2026-06-29 (config reconciliation + neg_licence decision) | D50 added: the EXP-C `neg_licence` Researcher variant is **favoured**, not adopted; the live `--prompt-variant` default stays `full`. NL dev (n=51/arm) is directional on all four endpoints and passes the joint non-inferiority rule but is underpowered (TN recall moves on one pair, 2/26 -> 3/26) and off-config (picker off, verifier_search never); the powered production-config signal is the partial held-out (149 pairs/arm, TN recall 34 -> 50%, neg-FPR flat), excluded from the adoption basis to keep the EXP-21 headline independent. Flip gated on a powered production-config dev confirm, currently blocked on run budget. Config alignment to D43: `--provider` default `auto` -> `diy` in `dispatch_subtrios.py` and `run_coordinator.py` (`auto` is an alias for `diy`, so behaviour-neutral), and the stale coordinator help string ("Default 'auto' = Tavily then Brave") corrected; `tavily`/`brave` kept in `choices` for EXP-1 reproduction. `ARCHITECTURE.md` reconciled: snippet-cap row -> kept (EXP-24 replay negative), retrieval-strategy row added (EXP-23 dispatched 2026-06-24 but Sonnet exhaustion left no canonical data; incumbent `narrow_then_wide` by default, no verdict), query-language row added (EXP-22 + L2 replay: language is not the binding constraint), Researcher prompt v3 -> V4, neg_licence favoured row, and an Adjudicator evidence-commit-gate row (EXP-25/27 null+harmful; the D37 floor remains the precision control). EXP-A (calibrated) and EXP-B (verifier `disprove_structured`) NL dev variants were run but are not adopted (defaults unchanged); full verdicts owed. No swarm behaviour change beyond the behaviour-neutral provider default. |
| 2026-06-26 (EXP number reconciliation) | D49 added. Two programmes both on `origin/main` had claimed EXP-22/23/24: language/retrieval (foreign-language ablation, narrow-then-widen, snippet-cap; run data) and the confidence-framework deep dive (entailment / self-consistency / argue-opposite / decomposed; null, no run data). Language/retrieval keeps 22/23/24; confidence framework renumbered to EXP-25/26/27/28 across the deep dive, `EXPERIMENTS.md`, this change log, `confidence_gates.py`, `nl_fp_audit.py`, and the renamed `exp25_entailment_smoke.py` (+ result jsonl). Canonical-DB `experiments` rows `exp22_entailment_gate` / `exp24_argue_opposite` renamed to `exp25_*` / `exp27_*` (not committed; DB diverges per worktree). |
| 2026-06-25 (Opus cost correction) | Corrected the Opus rate in `agents/tools/llm.py` `PRICING_USD_PER_M` from $15/$75 to $5/$25 per M input/output. The old figure was the Opus 3/4/4.1 rate; every Opus from 4.5 onward is $5/$25 (claude-api skill current-models table: Opus 4.6/4.7/4.8 all $5/$25). Both existing Opus entries (`claude-opus-4-6`, `claude-opus-4-5-20251101`) fixed and `claude-opus-4-7`/`claude-opus-4-8` added for forward safety; Sonnet ($3/$15) and Haiku ($1/$5) verified correct, unchanged. `estimated_cost_usd` is a notional API-equivalent under the flat CLIProxyAPI Max subscription (D1/Q9), not a real billing record, so historical rows are corrected rather than frozen, keeping the column reproducible from (tokens x rate). The swarm only ever logged `claude-opus-4-6` (637 rows on the canonical DB, was $37.95, becomes $12.65; the other 71k+ rows are Sonnet/Haiku and unaffected); per-experiment Opus costs in the dissertation were overstated 3x before this date. New idempotent `scripts/backfill_opus_pricing.py` recomputes the column from the rate table (dry-run by default, `--apply` to write); already run once against the canonical `data/odmi.db` (the binary DB diverges per worktree, so it is not committed). Doc table at D18 updated to $5/$25. New `tests/test_estimate_cost.py` pins the corrected rates and the 27-call batch arithmetic. SPEC doc fix only; no swarm behaviour change. This resolves the stale-Opus-pricing item flagged in the 2026-06-25 confidence-experiments entry below. |
| 2026-06-25 (confidence experiments + decision split) | Ran the pre-registered confidence experiments on production Sonnet (quota restored). **EXP-25 entailment gate and EXP-27 argue-the-opposite both NULL and harmful** (`evaluation/confidence_gates.py`, NL n=50, 25 committed negative golds): both *raise* the negative-gold FP rate (0.76 -> 1.00 for EXP-25, halving Youden's J) because the correct `no` commits are the low-entailment ones and abstain first while the confident FPs (entailment_for 0.74 vs correct 0.68) pass; the pre-registered adoption rule rejects both; McNemar caught 3/19 and 2/19 FPs (p=0.25, 0.50), 0 high-confidence. Confirms the deep dive's within-negative sign-flip end-to-end on the production model. **NL false-positive audit** (`evaluation/nl_fp_audit.py` + `nl_fp_audit_adversarial.py`, 22 questions over frozen evidence, two framings). Charitable pass: 1 genuine swarm error on Opus, 2 on Sonnet, rest definitional/self-report (~5-9%). Adversarial advocate pass (Opus told to argue the gold wrong): **0/22 gold_wrong** (swarm never vindicated), 11/22 over-reads (gold stands), 11/22 ambiguous. The genuine-error rate brackets ~5% (charitable) to ~50% (strict over-read), framing-dependent; robust finding is that no NL FP is the swarm-right-vs-stale-gold case, and the disagreements are strict-vs-loose question readings / self-report that no evidence gate resolves. **Decision taxonomy confirmed** against the official 2022/2024 ODMI methodology (2022 lists "Complement ... additional desk research" as a step; score/explanation signatures corroborate confirm/complement/change). **Decision-stratification shipped to the dashboard** (`dashboard/lib/db.py::accuracy_by_decision` + Analytics self-report split): all 6 production false positives sit on `confirm` golds. Pre-registered `exp25_entailment_gate` / `exp27_argue_opposite`; EXP-26/25 held (same null mechanism; EXP-28 spends the frozen held-out set). Reading: no evidence-grounded commit gate catches the confident FPs; the answer is decision-stratified reporting + D22 staleness adjudication, not a better gate. Flagged separately: `claude_usage_log` prices Opus at the stale $15/$75 per-Mtok rate (3x current), inflating dashboard GBP costs for Opus rows. Details in `docs/EXPERIMENTS.md` and `docs/CONFIDENCE_FRAMEWORK_DEEPDIVE.md`. |
| 2026-06-24 (EXP-23 design lock + picker_model knob) | Pre-registered EXP-23 (trusted-domain narrow-then-widen retrieval, multi-country), the first measured test of the SRCH-5/6/7 production decisions. Three arms over NL+MT+AL (~156 binary-balanced pairs each, 468 total), one variable (retrieval strategy): `baseline_narrow_then_wide` (production), `wide_only` (skip the trusted-domain include list, one wide pass), `narrow_only` (include list but never widen on empty, the attribution control). Adoption rule declared at dispatch: promote wide_only only if it cuts NL negative-gold FP by >= 5pp AND commit accuracy is non-inferior (delta >= -0.02); narrow_only is never adopted. Side-finding rule: wide_only >= 5pp AL candidate-recall lift confirms narrow was suppressing thin-web recall. Diagnostic: among each arm's FPs, the share whose cited source URL hits a trusted domain (direct test of the over-trust hypothesis). Spec at `evaluation/specs/exp23_narrow_then_widen.json`. Three new knobs threaded end to end and tested at every layer: `--search-strategy {narrow_then_wide, wide_only, narrow_only}` and `--picker-model <model>` (the snippet picker hardwired DEFAULT_MODEL, so under Sonnet exhaustion the picker 429s mid-pair; the knob pins Opus across all arms, constant -> no within-experiment confound). Orchestrator `flag_map` updated to forward both new knobs (an unforwarded knob silently no-ops; this footgun is now documented in memory). MT and AL trusted_domain lists first-authored for this experiment (NL is hand-curated production); committed with provenance notes. AL eval pair file built with the same seed/dimension-stratified rule as Malta (`scripts/build_al_eval_pairs.py`, 44 pairs, 22 yes / 22 no). Manipulation-check (`evaluation/manipulation_check_exp23.py`) + analysis (`evaluation/analyze_exp23.py`) scripts written for the post-dispatch read. Sonnet quota exhausted at run time so all roles + picker pinned to Opus 4.6 across every arm. |
| 2026-06-24 (D43 fetch-stage made per-pair; SPEC backfilled 2026-06-25) | Corrected the D43 fetch-stage rule: a stage that blows the 30s `DIY_FETCH_DEADLINE_S` ceiling is now a per-pair event, not a batch stop. `agents/tools/search_diy.py` abandons the hung futures and returns partial results instead of raising `BlockerShutdown` (commit `08629e4`, 2026-06-24 10:36), so one slow national portal can no longer halt a multi-country batch; the timeout is recorded in `fetch_stage_timeouts` via `_record_fetch_stall` for the systemic breaker. The fetch-stage-deadline test in `test_search_diy.py` was rewritten from `test_fetch_stage_deadline_raises_blocker` (assert raise) to `test_fetch_stage_deadline_returns_partial_no_blocker` (assert per-pair proceed, commit `6c1b09d`); the `BlockerShutdown` propagation test in `test_search_provider_arg.py` still stands (it covers Claude's 429 path, not the fetch stage). The D43 entry and heading were updated to record this revision, which had shipped in code on 2026-06-24 without a SPEC entry. Full suite 748 passing, 13 skipped. |
| 2026-06-23 (next-experiment designs + DIY-only correction) | Pre-registered four experiment designs in `docs/EXPERIMENTS_NEXT.md` and the `experiments` table (analysis plans locked, dispatch-ready, open to revision before spend). Three are confirmatory re-tests of decisions made on thin/unrepresentative samples: **EXP-18** breadth r5/r10 on FR+AL+NL (EXP-17 breadth was one NL run driving a +17% system-wide cost), **EXP-19** verifier never/always on NL+MT+AL (EXP-14 turned on a 0.62 vs 0.58 FP margin at NL n=51; spec ready at `evaluation/specs/exp19_verifier_search_multicountry.json`), **EXP-20** chaining baseline/chained on NL+AL (EXP-7 was underpowered on Malta). The fourth, **EXP-21**, is the whole-system test: the frozen production architecture end-to-end on the D47 held-out 8, balance-aware + three-outcome, no adoption rule (it is the reported headline), gated on a config freeze and run after the re-tests. All DIY-only. **Correction (D43 reaffirmed):** the provider question is closed, DIY only; the stale Tavily->DIY->Brave fallback row in `ARCHITECTURE.md` was removed and the multilingual lever reframed as a DIY-internal recall question, not a provider comparison. EXP-1/4/5 (provider comparisons) are dead and will not be re-run. No tokens spent. |
| 2026-06-23 (floor sweep, all countries) | Extended the EXP-10 floor sweep beyond Malta in response to the small-sample objection. New `evaluation/floor_sweep_all.py` pools the replay over every country with stored data (production rows for MT/NO/FR/EE/DE/RO + NL's production-config EXP-16 `standard` baseline for its 26 negative golds): pooled n=360 across 7 countries, 67 negative golds, 6x the Malta sample. **0.65 holds**: recovered-answer precision at 0.50 is 0.76 (vs Malta 0.75, so consistent), under the pre-registered 0.80 bar; negative-class FPR barely moves on lowering (0.37 -> 0.39). The three balanced countries (MT/NO/NL) all return 0.65; only yes-skewed FR/EE lean to 0.55, a base-rate artefact (no negatives to get wrong). `load_pairs` gained an optional `condition_label` arg to pull a single experiment arm as production-equivalent data; `ARCHITECTURE.md` floor row updated to the n=360 evidence. Free replay, no tokens. |
| 2026-06-23 (EXP-10 floor sweep, free) | EXP-10 Malta failure audit + confidence-floor sweep run (free replay, `evaluation/malta_failure_audit.py`, MT n=60). **Keep the 0.65 floor**: the pre-registered rule rejects lowering (0.50 recovers 6 correct but at 0.75 precision, under the 0.80 bar; negative-class FPR flat at 0.13 across 0.65/0.55/0.50, so the floor is not the false-positive driver). Phase A taxonomy of 28 non-matches: 17 fixable (7 fetch 4xx/5xx, 6 below-floor, 4 other), 11 genuine wrong, 0 structural; the largest fixable bucket is retrieval-side. Confirms the binding precision control is well-set and the open gains are retrieval-side, not reasoning-wiring-side. `ARCHITECTURE.md` floor row marked confirmed. No tokens spent. Details in `docs/EXPERIMENTS.md`. |
| 2026-06-23 (EXP-16 done + architecture ledger) | EXP-16 (Adjudicator standard vs free selection, NL n=51) finished: **null, keep standard**. `free` exercised the new `attempt_correct` capability on 16 of 52 pairs but gained nothing (commit acc 0.57 vs 0.58, McNemar p=1.00, FP and cost flat). Reading: the selection headroom is real (~10pt on NL, 74/44 on Malta) but free choice cannot bank it, the Adjudicator cannot tell which earlier attempt is correct from the evidence as presented (echoes the rec-3 confidence-ranking null); the ceiling needs a better per-attempt signal, not a wider choice set. New `docs/ARCHITECTURE.md`: a single living ledger of every component knob, its current adopted value, and the experiment/decision that set it, so the best-known configuration is one glance away rather than reconstructed from SPEC + EXPERIMENTS + findings docs. Future experiments append their verdict there. Details in `docs/EXPERIMENTS.md`. |
| 2026-06-23 (phase 1 dev runs + orchestrator hardening) | Two orchestrator fixes (extends D48): preflight now hard-fails on an experiment_id absent from the `experiments` table (R1 pre-registration enforced by construction, not memory; it had let EXP-14 and the EXP-17 picker arm start unregistered), and arm resume is idempotent (skips pairs already finalised for this experiment_id + condition_label, logs `already_finalised`/`remaining`, so a re-run neither re-spends nor writes duplicate finalisations). Runbook documents the canonical-row rule (latest `phase2_final` per (question, country, condition); dedup before reporting). 26 orchestrator tests. EXP-16 CHECK migration shipped: `scripts/migrate_adjudicator_verdict.py` widens `phase2_adjudications.adjudicator_verdict` to allow `attempt_correct` (idempotent, backs up, verifies; 305 live rows preserved), `setup_sqlite.py` matched, 5 tests. Results (NL dev, balance-aware, `evaluation/analyze_phase1.py`): **EXP-14** never vs always (n=51) is a null, keep `always`, removing the Verifier's live counter-search does not lift commit accuracy (0.61 vs 0.59, McNemar p=0.50) and raises the no-gold false-positive rate (0.62 vs 0.58); the EXP-12 clean-evidence J=0.42 advantage does not translate end-to-end, the live search earns its keep on the false-positive margin. **EXP-17 picker** on vs off (n=50) is a null, keep `picker_on`, but it refutes both reasons to cut the picker: candidate recall is unchanged (0.70 vs 0.72, so it does not bin the answer) and removing it raised cost ~57% (GBP 0.049 to 0.077, raw page-text heads enlarge context and the lower coverage 0.92 to 0.70 triggers more retries). The elective EXP-14 arm and the FR picker read are still owed. **EXP-16** (standard vs free adjudicator selection, NL) launched after the migration. Both new experiments pre-registered before results. Details in `docs/EXPERIMENTS.md`. |
| 2026-06-22 (experiment framework) | D48 added. `scripts/run_experiments.py` orchestrator + `docs/EXPERIMENT_RUNBOOK.md` + `.claude/skills/run-experiment/` skill, so multi-arm runs enforce the methodology by construction: forced `--no-cache` on retrieval/cost arms (cache-contamination catch), sequential arms at one global in-flight cap (search-ceiling catch), preflight hard-fail on held-out D47 countries / missing budget / unloadable deny-list / >1 variable per arm, self-pausing on budget or unhealthy-arm or dispatch error, manifest + JSONL log per run under `evaluation/runs/`. Verified: a valid NL dev spec dry-runs with `no_cache=True` forced; held-out SE, a two-variable arm, and a missing budget each hard-fail preflight. Example spec `evaluation/specs/exp17_funnel_example.json`. No experiment dispatched this entry. |
| 2026-06-22 (eval redesign) | D47 added, supersedes D42. The nine-country 3x3 maturity x language matrix is replaced by a base-rate-stratified held-out set after measuring ODMI score against binary yes-share at Pearson r = 0.98: maturity and base-rate balance are one axis, naive accuracy on a mature country just reproduces the ODMI ranking, and the negative golds that carry the false-positive claim sit in the Balkan/accession tail the matrix excluded. Dev set fixed at five in-sample countries (NL, MT, NO, FR, AL), with MT reclassified from held-out to in-sample (already burned by EXP-6/9/10 and the verifier programme). Held-out eval set fixed at eight by a pre-registered stratified rule: stratum A negative-rich low/mid-resource (BA, MK, ME, BG) + stratum B higher-resource balanced (FI, HR, SE, BE), ~1,144 pairs, ~368 negative golds, the two strata being the language contrast that replaces the matrix axis. Reporting locked as balance-aware (per-class rates, balanced accuracy, Youden's J vs majority baseline) and three-outcome (commit-accuracy / coverage / false-positive rate, risk-coverage curve over the D37 floor), stratified by dimension and shape, with a staleness adjudication band (D22) and France as a labelled degenerate contrast. All 36 deferred as the deployment-scale stretch. Follow-ups logged: language codes for the nine new countries, and the oversold Malta "English official" claim still in four other docs. No code or data changed this entry. |
| 2026-06-11 (verifier programme closed) | D45 added: the EXP-11/12/13 verifier investigation closes by retaining the incumbent design, with the full synthesis in `docs/VERIFIER_FINDINGS.md`. Four pre-registered attacks all returned null against the incumbent: the tristate verdict collapses (J 0.03 vs 0.41), the quote-gate strips real refutations, richer evidence does not raise discrimination (the verifier's own counter-search adds nothing; its value is cognitive, confirming D15), and relaxing the verdict wiring trades matches for committed-wrong one-for-one. Reframing finding: the verdict decides only 9 of 237 in-loop commits, so the D37 floor is the binding precision control and the verifier's influence flows through the Adjudicator (removing the layer costs 27 matches / +43 abstentions / -16 wrong, p < 0.002). Shipped: matcher v2 (per-snippet ellipsis-aware grounding gate, FM-11 + part of FM-02). Dropped pre-ship: absence confidence-ceiling and receipts check. `verifier_confidence` confirmed telemetry-only. Tristate apparatus stays in-tree, evaluation-only. EXP-13b (Sweden confirmatory) not run: its champion equalled the status quo. Open questions logged for separate pre-registration. 555 non-live tests passing. |
| 2026-06-10 (catalogue warm) | Pre-dispatch catalogue warm added to `dispatch_subtrios.dispatch` (on by default), an operational follow-on to D30/D46. A batch mixing web and catalogue questions previously let a cold-cache catalogue question harvest its country inside the Researcher, so the same slow portal (AT ~71k datasets) was harvested once per question and held a parallel slot for the whole harvest, starving the web questions. The warm step harvests each distinct catalogue country in the batch once, sequentially and fully, before the parallel loop, so every in-dispatch catalogue question is a cache replay of seconds. A usable cached snapshot is reused unless `--refresh-catalogue`; a failed harvest is logged and its pairs fall back to web. Confirmed that catalogue questions never reach the 30s DIY fetch-stage blocker (D43): the Researcher routes them at step 0, before query generation. New `_catalogue_countries_to_warm` (pure selector) and `warm_catalogue_snapshots` (injectable driver); flags `--no-warm-catalogue` / `--refresh-catalogue`; the Run Console inherits the default via the CLI. New `tests/test_dispatch_catalogue_warm.py` (11 cases). |
| 2026-06-10 (portal discovery) | D46 added, extends D30 under the D24 constraint. New `agents/tools/catalogue/discovery/` package (seeds / probes / verify / emit / run): a committed 36-country seed file with per-entry source annotations, stack fingerprinting (CKAN incl. `/data` prefix, uData, paged DCAT-AP feeds, SPARQL with results-JSON content negotiation, piveau, OpenDataSoft, data.json, hint-driven FDK), one-page sample verification with caveat auto-detection (HU/RO rdf-omits-licence fallback, FDK missing downloadURL, JSON-synthesised conformance, the data.gov.cy class-as-predicate producer bug), and registry emission in the hand-authored shape plus `discovery_method` / `discovery_evidence` / `caveats` / auto robots.txt summary. D24 hardened: the catalogue fetch layer refuses redirect chains landing on deny-listed hosts; seed loader, prober and emitter re-check the deny-list independently. 36-country experiment (one-page samples, no full harvests): on the pre-adapter probe set 14 verified, 5 stack-recognised-no-adapter, 17 failed (SPA stacks, WAFs, one malformed feed, one retired portal); FR / HU / NL re-discovered identically to their hand-authored registries, validating the prober. Two adapters built in response: `sparql_rdf` (CZ, HR, SE; one paged CONSTRUCT after the three-level shape timed out live) and `piveau_json` (AT). Final state 19 verified routes; registry coverage 6 -> 21 countries on this branch (+NO at merge), the 15 newly covered countries gaining a mean +6.5 points of open-web ceiling (83.0% -> 89.4%, `evaluation/discovery_ceiling.py`). New tests: fetch guard, probes, verify, emit, seeds, run, both adapters, ceiling lift. Docs: `docs/PORTAL_DISCOVERY.md`. |
| 2026-06-10 (EXP-11 stage 0, verifier redesign) | Ran stage 0 of the verifier-redesign programme (`docs/EXPERIMENTS_VERIFIER_REDESIGN.md`, the pre-registered runbook; proposals and Malta diagnosis in `docs/VERIFIER_REDESIGN.md`). Three free offline replays decided three knobs before any quota was spent. (1) **Matcher v2 shipped (P4).** `substring.contains_v2` matches a quote per snippet with ellipsis-aware fragments rather than against a `"\n\n"`-joined corpus, so a cross-snippet splice can no longer pass and a within-snippet elision no longer wrongly fails. Wired into `agents/verifier.py` `_run_substring_check` (snippet path; the live-fetch/catalogue path keeps v1). Replay over 639 researcher quotes: v2 rejects nothing v1 passed and rescues 8 wrongly-failed elisions (4 on correct answers); on verifier counter-quotes it catches a junction-stitch splice that v1 passed on a correct answer. 13 new tests (`tests/test_substring_v2.py`); 546 non-live passing. This is the FM-11/FM-02 deterministic gate hardening, shipped on its own receipt ahead of the rest of the redesign. (2) **Absence confidence-ceiling dropped (P3 lock 3).** A (pair, attempt) replay on MT+NO showed raising the ceiling above the 0.65 floor is net-negative: on Malta it defers 7 of 8 absence commits, all correct, to catch zero wrong; the absence-precision job moves to the live confirmation route (P2), to be measured in stage 1. (3) **Absence receipts check parked (P3 lock 1).** Near-inert as specified because the search templates already name the country; only a subject-term matcher (deferred) would discriminate. `verifier_confidence` audited: it gates nothing and stays telemetry (P6). Stages 1 (classifier ladder) and 2 (end-to-end on Sweden) are unstarted; they need quota, the tristate build, and the NL pinned dispatch. No numbered decision yet (D45 is reserved for adopting the full redesign after stage 2). |
| 2026-06-08 (false-positive register) | `docs/FAILURE_MODES.md` created: the exhaustive register of ways the swarm can commit a wrong answer while presenting it as confident, distinct from the operational deferrals in `KNOWN_GAPS.md`. Built from a five-pass code audit (Researcher, Verifier, Adjudicator, coordinator finalisation, deterministic gates, catalogue path). 34 failure modes (FM-01..FM-34) under a three-way cut: Caught (deterministic backbone we trust), LLM-only (deciding evidence is in the context window, accepted as prompt-tunable), and Structural (prompting cannot fix; the attack list). The structural set clusters as missing context (FM-02/05/09/34), loose deterministic gates (FM-10/11/13/17), answer-key leakage on allowed domains (FM-14), correlated or skipped adversary (FM-19/20/21/23/33), uncalibrated confidence (FM-22/26/27), and the catalogue path's non-independent recompute (FM-28..32). Indexed from the "Where to look for what" table and from `CLAUDE.md`. The with/without-Verifier ablation and four-strategy head-to-head are the experiments that would quantify which modes the Verifier actually closes. No code change this session; analysis artefact only. |
| 2026-06-09 (eval matrix) | D42 added, amends D7's Phase B sample. Evaluation sample fixed as a nine-country 3×3 maturity × language-resource matrix, one country per cell: FR / SK / EE (high maturity), DE / HU / SI (mid), SE / RO / MT (low), across high / mid / low-resource language tiers. Wealth dropped as an axis in favour of language-resource (RQ3). The nine are held out: the default pipeline is tuned only on development countries from the 27 outside the matrix (plus France, the legacy in-sample sandbox), then frozen by commit before the headline run. Pre-registered between-condition experiments (Verifier strategies EXP-6, cost-side Family 1, model variants Family 3) are permitted on the nine because they compare arms against a reported baseline; iterative optimisation of the default pipeline against these countries is not. Recorded wrinkles: France's cell is in-sample and base-rate-degenerate (report it as the dev point), and one-country cells are noisy so cell-level claims stay cautious. SK / SI / SE need language codes (sk / sl / sv) added to `run_coordinator.py` before dispatch; NL leaves the sample (shared the mid / high cell with DE). METHODOLOGY RQ3 and Section 6 updated to match. No code or data changed in this entry. |
| 2026-06-04 (bug-fix batch) | Codebase-wide bug hunt after the concurrent-branch merges; fourteen confirmed findings fixed, three left by choice, three flagged for a human glance. Headline correctness fixes, all in the evaluation path: (1) abstentions (`inconclusive`) were silently classified `differ` in `_MATCH_STATUS_SQL` and counted as wrong; they now have their own `abstained` status. Decision this session: an abstention is a failure to answer, so it stays in the accuracy denominator (accuracy unchanged, 0.645), but `accuracy_summary` now also returns `n_abstained` and `abstention_rate` (0.27 on current main), surfaced across Home/Results/Database/Analytics. (2) A bare `yes` falsely scored an exact match against a count_band gold like `yes, >9`; the `yes...` prefix match is now gated to binary questions (drops n_match 137 to 136). (3) near_match adjacency no longer treats sentinel labels (`not applicable`, `i don't know`, abstention/other) as adjacent bands. Crash/safety fixes: the Coordinator resume path raised `UnboundLocalError` (never bound `r_result`) and is now made uniform via a synthesised `ResearcherRunResult`; the Adjudicator could crash finalisation on a sub-`min_length` evidence quote (now falls back); `trust_score` corrupted hostnames with `lstrip("www.")`; the leakage deny-list was bypassable with a trailing-dot FQDN (`data.europa.eu.`). Stranded `loving-mendel` code cherry-picked: the canonical-row dedup that EXP-7/EXP-10 need (they were double-counting duplicate `phase2_final` rows), the EXP-6 `--workers` parallelism, the `max_retries=8` proxy-resilience cushion, and two test files. Smaller: reproducible DCAT-RDF snapshot hash, DIY-empty falls through to Brave, `cleanup_subtrios` PID-reuse guard, `harness.py run-pair` positional args, Verifier strategy descriptions V1 to V3, chained-evidence dedup on full snippet, `datetime.utcnow()` deprecation cleared. Left by choice: model-default write not read-only gated (single user), Holm step-down / even-n median labels, no `cycle_year` join filter. Flagged: Q2's `allowed_answers` leads with a stray `"1"` (loader artefact, shifts band indices); EXP-1's "decided" denominator includes per-orientation `both_fail` against the "excluded" prose (disclosure call, strengthens DIY either way, 89% to 93% under strict exclusion); per-country trusted lists load empty because the JSON key is `trusted_domains` but `validator._load_country_list` reads `trusted`. Tests: 523 passing (was 496), 13 skipped. |
| 2026-06-04 (concurrency correction) | D42 added, follows D40/D41. Fact-checked and corrected the recurring claim that concurrent runs must be sequenced because they "contend on one quota". They do not: concurrent Claude calls consume the one shared Max budget additively (linearly), with no super-linear penalty and no per-call slowdown; below the limit concurrency overlaps latency and finishes sooner, at the limit total time is budget-bound either way. The proxy strips all `anthropic-ratelimit-*` headers (Session 9 probe) so capacity is unobservable, and D40 already removed the soft limit as unmeasurable. The genuine reason to isolate two experiment arms is data-state cross-contamination (the resume path reusing one arm's Researcher rows), shown live by the 2026-06-04 EXP-6 / Malta-`v2` candidate-set collision, not the rate limit. Rewrote `EXPERIMENTS_PROTOCOL.md` section 10 (heading "Execution and concurrency") and the `EXPERIMENTS_CHAINING.md` section 10 note; no code change. |
| 2026-06-03 (answerability split) | Added a per-question answerability tag so results are reported separately by how an answer can be sourced, never excluded. `scripts/build_answerability.py` writes `data/questions/answerability.json`: `catalogue` (the 9 D30-computable questions, authoritative from `agents.tools.catalogue.compute.COMPUTABLE_QUESTIONS`), `self_report` (questionnaire-only internal practice, matched by a transparent keyword rule, reviewable first-pass), `web` (the rest). Split: 119 web / 9 catalogue / 15 self_report. On the Malta baseline the split is the point: web questions reach 79% committed accuracy (30/38), self_report only 40% (2/5) with 7 of 12 abstaining; catalogue questions are percentage-band so none fall in the binary Malta set. The keyword rule is a first pass for review (it missed PT15/PT28/PT45 and the `surveys?` pattern is broad); refine the generator, not the JSON by hand. WAF/CAPTCHA investigation recorded under the Malta entry and the `head_ok` / Playwright-hardening commits: data.gov.mt HTML clears via Playwright (hardened with anti-automation launch args + a Cloudflare-challenge settle), but portal.data.gov.mt walls its uData API even through a cleared browser, so the clean-API route that works for the other five D30 countries is unavailable for MT. |
| 2026-06-03 (abstain floor) | Extended the D37 commit-confidence floor (0.65) to the Adjudicator's terminal answer in `_finalise_after_adjudication`. Before this the floor only gated the in-loop Verifier-pass path, so at retry exhaustion the Adjudicator could finalise a sub-floor label, which on sparse evidence is usually a defensive `no` (and occasionally a weak `yes` false positive). A sub-0.65 Adjudicator commit is now downgraded to an honest `inconclusive` abstention: under the floor the swarm abstains rather than guessing `no`. On the Malta baseline this would convert the four 0.45-confidence commits (Q10, Q11, Q6 false-negative `no`s and the PT29 false-positive `yes`) into abstentions. Behaviour change for future runs; the committed Malta data predates it. New `tests/test_finalise_after_adjudication.py` cases (sub-floor downgrade, above-floor kept); 496 non-live passing. |
| 2026-06-03 (Malta dispatch, done) | Malta baseline swarm dispatch completed, the shared prerequisite for EXP-6/7/8/9 (protocol section 9 item 9). Canonical 60-pair set (`data/questions/malta_eval_pairs.json`, 30 `no` / 30 `yes`, seed 20260603) was already committed; verified no-gold coverage (all 30 present) and dimension balance. Dispatched the remaining pairs in four passes (provider auto, `condition_label` baseline, no `experiment_id`, batch `malta_baseline`): all 60 finalised, 43 committed yes/no plus 17 honest `inconclusive` abstentions (D37). Balance-aware (R4): 32/43 committed accuracy, no-gold recall (TNR) 0.87 with 3 false positives of 23 committed (I7, I8-b, PT29), yes-gold recall (TPR) 0.60, Youden's J 0.47, mean commit confidence 0.58; zero data-leakage; batch cost ~$4.98. Three faults found and fixed, none quota: a fresh worktree had no `.env` and the desktop app injected an empty `ANTHROPIC_AUTH_TOKEN`, making every LLM call a misleading `APIConnectionError` (`agents/tools/llm.py` drops a blank token at import); `_find_resumable_researcher` resumed from failed / `inconclusive` Researcher rows, stranding 11 pairs at 'researching' (`scripts/run_coordinator.py` now resumes only clean committed results); and `head_ok` reported Cloudflare-protected data.gov.mt as `url_unreachable`, which it now clears with a Playwright render on a WAF 403/429/503 (`agents/tools/fetch.py`), recovering the last two pairs I8-d and PT12 to `inconclusive`. The first pass also hit a genuine Claude 429 `model_cooldown` near the end and stopped cleanly. New Malta DB rows committed on this branch; 446 tests pass. SPEC current-status, `EXPERIMENTS.md`, `EXPERIMENTS_PROTOCOL.md` section 9 item 9, and `EXPERIMENTS_VERIFIER.md` updated. Failure-mode taxonomy drafted for EXP-10 (retrieval ceiling dominant; the data.gov.mt WAF block now mitigated). |
| 2026-06-03 (runaway guard) | D41 added, follows D40. Two runaway circuit breakers on `dispatch_subtrios.py`, keyed on real units and set far above any real run: a pre-flight refusal above `MAX_PAIRS_PER_DISPATCH = 500` pairs (on by default, overridable with `allow_large` / `--allow-large`; surfaced as a checkbox in the Run Console), and an opt-in mid-flight `--max-calls` breaker that stops spawning once the batch's logged calls (via new `_batch_call_count`) reach the cap. `DispatchResult` gains `aborted_oversize` and `calls_capped`. Replaces the deleted dollar budget with a "this is obviously broken, stop" guard rather than a per-run "may I spend this?". New `tests/test_dispatch_runaway_guard.py` (8 cases); 446 non-live passing. |
| 2026-06-03 (soft limit) | D40 added, supersedes D20 layers 1 and 2. Removed the local cost soft limit: `DEFAULT_SOFT_LIMIT_USD`, `LOW_WATER_FRACTION`, the `soft_limit_usd`/`force` params and `--soft-limit-usd`/`--force` flags on `dispatch_subtrios.py`, the `CostEstimate.soft_limit_usd`/`budget_remaining_usd` and `DispatchResult.aborted_due_to_budget` fields, the pre-flight refusal, and the per-spawn low-water stop. `harness.py` no longer passes `--soft-limit-usd`; the dashboard sidebar loses the soft-limit slider/progress and the Run Console loses the "Window soft limit" metric and "Force release" checkbox. Rolling 5-hour spend is still computed and shown (sidebar, Run Console, Costs) and the pre-flight estimate is still logged, but nothing blocks a dispatch now; the only ceiling is Claude Max's own rate limit (D20 layer 3, the clean resumable 429 shutdown, kept). The cap was a guessed arithmetic equivalent of a flat subscription, not a real balance, so it was friction without protection. Tests updated; 438 non-live passing. |
| 2026-06-03 (chaining) | D39 added: EXP-7 chained retry arm built behind `--chained` (default off, baseline byte-identical). New `EvidenceItem` model; `VerifierFeedback` gains `counter_evidence_quote` / `counter_source_url` (default None); `ResearcherInput.prior_evidence` and `AdjudicatorInput.evidence_corpus` added. Coordinator accumulates a de-duped, 40-capped evidence corpus across rounds when chained, feeds the Verifier's counter-evidence back to the Researcher, and adjudicates over the whole corpus; the D37 floor and abstention rules are untouched. Carried evidence rides in the user message, not the system prompt, so `prompt_versions` are stable and an empty corpus renders byte-for-byte as before. Flag threaded `dispatch_subtrios.py` → `run_coordinator.py`. Pre-registered in `docs/EXPERIMENTS_CHAINING.md` (Malta primary per R4, false-positive rate as a co-primary, paired McNemar/Wilcoxon, one confirmatory joint claim); EXP-7 status board updated. New `tests/test_chained_evidence.py` (18 cases); 418 non-live passing. Run gated only on the Malta dispatch (search quota) and Claude headroom. |
| 2026-06-03 (experiment rules) | D38 added: a universal experiment checklist (R1 to R12) in `EXPERIMENTS_PROTOCOL.md` section 0, headed by R4, the base-rate rule that bars a degenerate evaluation country and pins selection to minority-class share subject to a well-resourced-language constraint (Malta primary, Netherlands secondary; the No-share table is computed from `ground_truth` over binary yes/no golds). Pre-registered EXP-8 (Family 1 cost-side) and EXP-9 (Family 3 model variants) under the rules, with registry rows and Malta-dispatch / condition-threading pre-run requirements (items 9 to 11), all gated on search quota. Retargeted EXP-6 to Malta-primary (France/injected demoted to a robustness arm; `EXPERIMENTS_VERIFIER.md` and `evaluation/verifier_strategies.py` strata updated, the partial superseded not deleted). Added protocol section 12, a rubric audit that flags EXP-1's France E1 accuracy as base-rate degenerate (the E2 provider result stands) and EXP-3's Lithuania control as undiscriminating on binary. `build_candidates` verified to degrade gracefully (empty Malta primary, 82-candidate robustness arm) until the dispatch lands. No experiment runs in this change. |
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
| Known gaps and anticipated failure modes (operational)? | `docs/KNOWN_GAPS.md`. |
| False-positive / correctness failure modes (the attack list)? | `docs/FAILURE_MODES.md`. The 34-mode register. When the task is "attack the failure modes", start there. |
| Hand-mark CSVs (historical, superseded by D22)? | `data/hand_marks/`. |
| One-stop CLI for swarm ops (status, run, audit, purge)? | `scripts/harness.py`. Read-only by default; destructive ops need `--yes`. |
