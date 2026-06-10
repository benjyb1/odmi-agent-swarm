# Malta orchestration state (autonomous run, 2026-06-03)

Scratch file for the autonomous orchestration Benjy handed off at ~21:20 on
2026-06-03. NOT a permanent doc; delete when the run is finished and results are
committed. Purpose: survive context summarisation across the long wait.

## The job (Benjy's instructions)

1. Wait autonomously until all 60 canonical Malta pairs are finalised.
2. Then fire, in parallel, every Malta-gated experiment that is not yet done.
3. Run one extra QA agent scrutinising data quality, impartiality, and rubric
   adherence across the lot.
4. Write results, update docs, commit AND push on this branch. Benjy is away.

Decisions he locked before leaving:
- Scope: any experiment not already complete (he thought EXP-7 might be done; it
  is NOT - only its code is built, no results exist).
- Dispatch: launch the quota-heavy re-dispatches autonomously (overrides the
  standing "Benjy runs dispatch himself" memory for this session).
- Trigger: all experiments in parallel once data is in. Completion rule: all 60
  terminal, else proceed after a stall (~45 min no new finalised pair) flagging
  gaps.
- Output: write results + update docs (EXPERIMENTS.md / SPEC / PROJECT_LOG),
  commit and push.

## Critical infra fact: the live DB is in ANOTHER worktree

DB path resolves CWD/worktree-relative (`agents/tools/db.py`:
`Path(__file__).resolve().parents[2]/"data"/"odmi.db"`). Each worktree has its
own `data/odmi.db`. The LIVE Malta data is being written to:

    /Users/benjyb/Desktop/Msc Project/.claude/worktrees/hungry-noether-31d9aa/data/odmi.db

My worktree (loving-mendel-c93a2b) has a STALE 22 MB copy. The baseline dispatch
ran with `ODMI_SKIP_AUTO_PUBLISH=1`, so the DB is NOT being committed/pushed.

Plan: complete the baseline in hungry-noether's DB, then SNAPSHOT it into my
worktree (cp) and run all experiment work from my branch against the snapshot.
Heavy re-dispatch experiments (EXP-7/8/9) write to MY DB (coherent, isolated).

## State as of handoff (~21:21, 2026-06-03)

- Canonical set: 60 pairs, `data/questions/malta_eval_pairs.json` (30 no-gold +
  30 yes-gold, seed 20260603). EXP-6/7/8/9 reuse this identical list.
- LIVE DB: 49/60 finalised, 11 missing. No dispatch/coordinator process running.
- The 11 missing are all `superseded` (stale ~20:12-20:14), the stubborn ones:
  8 no-gold + 3 yes-gold. Heavy Portal/Quality. Rate limits were biting
  (`interrupted_rate_limit`).
  Missing: I7, I8-d, PT12, PT16, PT27, PT29, PT6, Q19 (no-gold);
           Q23, Q6, Q9 (yes-gold).

## Baseline dispatch config (replicate EXACTLY for the canonical run)

CWD = hungry-noether-31d9aa worktree. Env `ODMI_SKIP_AUTO_PUBLISH=1`.
`scripts/dispatch_subtrios.py --pairs <QID:MT ...> --parallel 3
  --batch-id malta_baseline --soft-limit-usd 50
  --strategy verifier-disprove
  --researcher-model claude-sonnet-4-6
  --verifier-model claude-sonnet-4-6
  --adjudicator-model claude-sonnet-4-6
  --max-results-per-query 5 --max-retries 3 --prompt-variant full --provider auto`
(strategy/max-results/retries/variant/provider are the argparse defaults; models
passed explicitly to match the original wave.)

## Experiments to run (none are done; verified no result files, only EXP-6
## registered in `experiments` table)

- EXP-6  Verifier strategy discrimination. Frozen-evidence analysis.
         Harness `evaluation/verifier_strategies.py` (resumable). Reads DB. No new dispatch.
- EXP-10 Malta failure-mode audit + confidence-floor sweep.
         Harness `evaluation/malta_failure_audit.py` (TO BUILD per
         docs/EXPERIMENTS_MALTA_FAILURES.md). Deterministic + free floor sweep.
- EXP-7  Retry chaining. Re-dispatch 60 pairs: baseline vs `--chained`. Heavy.
         Pre-reg docs/EXPERIMENTS_CHAINING.md.
- EXP-8  Cost-side knobs: baseline / prompt-compressed (`--prompt-variant compressed`) /
         retrieval-tight (`--num-queries`/`--max-results-per-query` low) /
         cache-hot vs `--no-cache` / model-fallback (`--researcher-escalation-model`
         etc.). Re-dispatch. Pre-reg EXPERIMENTS_PROTOCOL.md section 7.
- EXP-9  Model variants: model-haiku / model-sonnet (baseline) / model-opus /
         model-tiered (Haiku draft, Sonnet verify, Opus adjudicate). Re-dispatch.
         Pre-reg EXPERIMENTS_PROTOCOL.md section 7.
- QA     One agent scrutinising data quality + each experiment's impartiality and
         rubric adherence against the pre-registered protocols.

Universal rules live in `docs/EXPERIMENTS_PROTOCOL.md` section 0 (R1-R9):
balance-aware reading (R4), reproducible frozen sets (R2/R3), cost-with-retries
(R9). All endpoints read balance-aware because Malta is base-rate balanced.

## Refined execution plan (decided after reading the full protocol)

Protocol §10 is binding: every dispatch and every judge/verifier LLM call draws
on ONE shared Claude quota (Claude Max via CLIProxyAPI). "Parallel" helps
orchestration, not throughput; firing all heavy jobs at once just contends and
corrupts the R9 per-pair cost measurement. Rate limits already bit the baseline.
So: parallel where free, sequenced where quota-bound. Honour the user's "in
parallel if you can" - the "if you can" is the out the quota gives me.

Baseline reuse (big saver): the existing 60-pair `malta_baseline` run (prompt
full, sonnet x3, max-results 5, provider auto, independent retries, --chained
off) IS the reference arm for:
  - EXP-7 `baseline`   (independent retries)        -> only the `chained` arm is new
  - EXP-8 `baseline`   (full prompt/retrieval)      -> only 4 lean arms are new
  - EXP-9 `model-sonnet`                            -> only haiku/opus/tiered new
Caveat to flag: R9 wants cost arms cold-cache; the baseline was not guaranteed
cold. Note it; the EXP-8 lean arms still run cold via --no-cache. The QA agent
must check this.

Order (each step monitored; report partials honestly, never fake completion):
  P1. Finish baseline 60 (11 stragglers dispatched, in progress). DONE-GATE.
  P2. Snapshot hungry-noether DB -> my worktree data/odmi.db. All later work here.
  P3. Fire in parallel (subagents):
        - EXP-10 agent: malta_failure_audit.py --country MT --floors 0.65 0.55 0.50
          [--llm for residual]. Free/cheap, finishes fast. experiment_id malta_failure_audit_v1.
        - EXP-6 agent: verifier_strategies.py (auto MT-primary). 368 verifier calls,
          self-throttling/resumable. experiment_id verifier_strategy_disc_v1.
        - QA agent: scrutinise the 60-pair data quality + EXP-6/EXP-10 outputs +
          experiment setup vs the pre-registration (R1-R12). Light Claude use.
  P4. Sequenced re-dispatch (one background queue, NOT concurrent), then analyse:
        - EXP-7: dispatch chained arm (60 pairs, --chained, experiment-id
          retry_chaining_v1 [register first], condition-label chained), then
          chaining_analysis.py vs the baseline 60.
        - EXP-8: 4 lean arms (prompt-compressed / retrieval-tight / cache-hot /
          model-fallback), experiment-id cost_side_optim_mt, ~40 dim-stratified
          pairs each, --no-cache except cache-hot. Then cost/accuracy analysis.
        - EXP-9: haiku / opus / tiered arms, experiment-id model_variants_mt.
          Opus arm is the costliest single thing in the whole plan.
      These are ~370 new swarm runs combined. On Claude Max with rate limits this
      is many hours to days. Likely will NOT all finish in one window; grind and
      report partials. QA agent re-reviews each as it lands.
  P5. Update EXPERIMENTS.md / SPEC.md / PROJECT_LOG.md, regen slides if warranted,
      commit + push on this branch. Delete this scratch file.

Harness invocations (from my worktree, after snapshot):
  EXP-6 : uv run python evaluation/verifier_strategies.py          (--limit N to smoke)
  EXP-10: uv run python evaluation/malta_failure_audit.py --country MT --floors 0.65 0.55 0.50 --llm
  EXP-7 : (dispatch chained arm) then  uv run python evaluation/chaining_analysis.py ...
Register experiments in the `experiments` table before each run (R12). EXP-6 and
EXP-10 ids already in protocol §8: verifier_strategy_disc_v1, malta_failure_audit_v1,
cost_side_optim_mt, model_variants_mt. EXP-7 needs an id (use retry_chaining_v1).

## QA findings (agent a87cbeee, 2026-06-03) + actions

QA verdict: EXP-6 GO-WITH-CAVEATS; EXP-10 NO-GO as it would re-run (a BLOCKER),
data set otherwise clean and well-controlled.

BLOCKER (FIXED): phase2_final had 72 rows for 60 distinct MT questions. Two
patterns: (A) stale exp6_malta agent_failure rows superseded by real
malta_baseline finalisations; (B) concurrent double-finalisations tonight, two
of which conflict (Q6 yes/no, PT29 inconclusive/yes). malta_failure_audit.load_pairs
counted all 72 -> negative-gold denominator 40 not 30 -> corrupted Phase-B
false-positive rate. FIX: load_pairs now selects the canonical row per
(question,country) = highest id, experiment_id IS NULL for main runs / =? for a
named experiment, mirroring the dashboard's ROW_NUMBER rule (dashboard/lib/db.py
match matrix). This is the project's own accepted, answer-blind rule, not a new
one. Verified: 60 rows, 30/30 gold balance. Q6->no, PT29->yes (both honestly
wrong vs gold; the dedup does NOT cherry-pick the gold-matching row). Pinned by
2 new regression tests (tests/test_malta_failure_audit.py, now 18 pass).
TODO at EXP-7: apply the same canonical dedup to chaining_analysis.load_outcomes,
but partitioned per (question, country, ARM) since it derives arm from
phase2_researcher_runs.condition_label. Not yet done.

EXP-6 caveats to apply AT WRITEUP (run not re-done, the between-arm comparison is
valid since all 4 arms share identical frozen evidence):
 - Frozen evidence is generated by a LIVE diy search per candidate then shared
   across arms; the harness records n_independent_snippets but not the snippet
   TEXT, so absolute J is not bit-replayable from logs. Document as a
   reproducibility limitation (soft breach). Do NOT re-run to fix (wastes ~368
   calls); the comparison between strategies is unaffected.
 - Print the 69% Malta majority baseline beside any accuracy figure (R4a).
 - Report Malta-natural Youden's J ALONGSIDE injected-J: 7 of 24 MT should_fail
   are Quality no-researcher/yes-gold (self-report/stale-gold ceiling), so
   natural-J alone is fragile. QA confirmed MT primary stratum = 48 candidates,
   24 should_fail / 24 should_pass.
EXP-10 caveat: the --llm residual judge prompt leans conservative ("default to
genuine_error unless evidence supports the swarm"), i.e. AGAINST the swarm, so it
under-credits stale-gold and cannot flatter results. Name it in the writeup.
Data set PASSes: gold balance 30/30, evidence integrity (63/64 grounded; P22 a
paraphrase), deny-list (0 data.europa.eu sources), stats module matches scipy.

## When EXP-6 completes (the gate) - do this:
1. Collect EXP-6 results (the agent afa338fc returns them; or run
   `uv run python evaluation/verifier_strategies.py --analyse-only <jsonl>`).
   Note the winning strategy by Youden's J (with Wilson CI), per-class rates,
   token cost (Wilcoxon), Malta-natural J vs injected J, print 69% baseline.
   Commit the EXP-6 result JSONL (excluded from the first checkpoint as it was
   mid-write).
2. EXP-7: register done. Apply EXP-6's winning verifier strategy to BOTH arms
   (else verifier-disprove); record the choice. Dispatch ~40 dim-stratified MT
   pairs (seed 20260603) BOTH arms cold under experiment_id=retry_chaining_mt_v1:
     baseline arm: --no-cache --condition-label baseline  (NO --chained)
     chained  arm: --no-cache --condition-label chained --chained
   Run from MY worktree (writes my DB). Then
   `uv run python evaluation/chaining_analysis.py --experiment-id retry_chaining_mt_v1`.
3. EXP-8 then EXP-9, sequenced (each ~150-160 runs; Opus arm in EXP-9 is the
   costliest). These + EXP-7 are ~370 fresh runs = many hours/days on the shared
   Claude Max quota which is already rate-limiting EXP-6 hard. Launch, grind,
   commit partials, report honestly. Do NOT fake completion. If quota is clearly
   being exhausted, pause and leave resumable state + a clear handoff for Benjy
   rather than starving his quota unattended.

## PARALLELISM + QUOTA EXHAUSTION (later, ~22:30)

Benjy asked to run experiments in parallel. Built the mechanism:
- agents/tools/llm.py: `_make_client` now uses `max_retries=8` (was SDK default 2).
  The CLIProxyAPI front end drops connections under concurrency
  (APIConnectionError); the SDK now retries those + 5xx + transient 429 with
  backoff, while a SUSTAINED 429 still surfaces as RateLimitError -> D41 shutdown.
- evaluation/verifier_strategies.py: added `--workers N` (ThreadPoolExecutor over
  candidates, write under a lock, resume-safe, per-candidate errors caught and
  retried on resume). Default 1 (unchanged behaviour).

THEN HIT THE UPSTREAM WALL. Diagnosed conclusively:
- proxy (localhost:8317, pid live) is UP and serving HTTP (banner + instant 401
  on /v1/models), but authenticated Anthropic message calls reset the connection
  -> APIConnectionError, even a single minimal call, even after `brew services
  restart cliproxyapi`.
- timeline: 300+ calls SUCCEEDED during the 5-worker EXP-6 burst, then ALL calls
  began failing. cliproxyapi.conf has an explicit `quota-exceeded` section.
- conclusion: the Claude Max allowance is exhausted. Caused by my aggressive
  burst: the earlier 80-coordinator spawn (a mistake) + the 5-worker run firing
  300+ calls in minutes. Nothing code-side fixes it; it recovers when the Max
  window resets.

State at the wall:
- DONE + committed: baseline 60/60, EXP-10, QA, dedup fixes, EXP-7/8/9 registered.
- EXP-6: partial, 27/130 candidates (full 24 Malta should_fail + into should_pass),
  JSONL intact + resumable. NOT yet analysable (needs the full primary stratum).
- EXP-7/8/9: not started. retry_chaining_mt_v1 junk rows cleaned (0).
- All my dispatch/verifier/coordinator processes killed; nothing hammering.

PAUSED AT BENJY'S REQUEST (~22:50). At 88% of the 5x Max plan, so little headroom
left this window. Decision: WRAP UP NOW. Drop EXP-7/8/9 for the moment. Recovery
probe killed; nothing running. EXP-6 left paused at 27/130 (resumable any time).
Caching note from Benjy: when work resumes, be stringent with caching to stretch
quota. The search layer already caches (search_cache_serp/snippet/fetch); EXP-6's
resume run should NOT pass --no-cache so its freeze-evidence searches reuse cache.
LLM calls themselves are not cached, so the main lever is the resume logic (skip
done candidates) + search cache + not re-running completed work.

RESUME PLAN when quota returns (do NOT burst):
1. Gently probe the proxy with ONE minimal call. Only proceed when it succeeds.
2. Resume EXP-6 at MODEST concurrency: `uv run python evaluation/verifier_strategies.py
   --workers 3` (resumes from 27). Watch claude_usage_log rate_limited.
3. Then EXP-7 both arms (the cleaned retry_chaining_mt_v1, ~40 pairs each), then
   EXP-8/9 - but note the TOTAL remaining workload (EXP-6 remainder ~515 calls +
   EXP-7 ~400 + EXP-8/9 thousands) likely EXCEEDS one Max window. Parallelism
   reaches the cap faster, it does not raise the ceiling. Pace across windows or
   get Benjy's call on scope.

## Progress log (append as I go)

- 21:21 handoff. Re-dispatching the 11 stragglers next.
- 21:30 straggler dispatch live (bg task b86syjk1e, 11 pairs, hungry-noether,
  ODMI_SKIP_AUTO_PUBLISH=1). Read full protocol; refined plan above. Waiting on
  dispatch-completion notification, then verify 60/60 and fan out.
- 21:40 straggler dispatch exited clean (exit 0, no rate-limit abort). LIVE DB
  60/60 canonical finalised (31 accepted_adj / 17 escalated_adj / 16 accepted_ver
  / 8 agent_failure across the canonical rows). Snapshotted hungry-noether DB ->
  my worktree data/odmi.db via sqlite3 .backup (consistent, 38MB). Verified 60/60
  in my DB. A redundant Q9 retry coordinator was still winding down in
  hungry-noether at snapshot time; harmless (Q9 already final), excluded from my
  snapshot.
- 21:45 P3 fired: 3 background agents in parallel.
    EXP-6  agentId afa338fc5cf4ca0fe  (verifier_strategies.py full run)
    EXP-10 agentId a485683074c252369  (malta_failure_audit.py --country MT --floors 0.65 0.55 0.50 --llm)
    QA     agentId a87cbeee39a1919bd  (data-quality + rubric/impartiality audit, read-only)
  GATING for the heavy re-dispatch (EXP-7/8/9): wait for EXP-6 to finish (it is
  the quota-heavy one, ~368 calls). Starting EXP-7's dispatch while EXP-6 runs
  would thrash the shared rate limit and confound EXP-7's recovery + calls/pair
  endpoints with quota-induced failures. EXP-10 and QA are light; not the gate.

## EXP-7 dispatch mechanics (verified from chaining_analysis.py + dispatch_subtrios.py)
- chaining_analysis.py: --experiment-id (default `retry_chaining_mt_v1`), loads
  BOTH arms from phase2_final WHERE experiment_id=?, arm = COALESCE(
  phase2_researcher_runs.condition_label, 'baseline'). Endpoints: balanced acc,
  per-class rates, false-positive rate (co-primary), calls/resolved pair (from
  claude_usage_log keyed on subtrio_id==pair_run_id), paired McNemar + Wilcoxon,
  one joint confirmatory (bal-acc non-decrease AT non-raised FP rate).
- dispatch_subtrios.py has --chained, --experiment-id, --condition-label.
- The existing 60 `malta_baseline` pairs are experiment_id=NULL -> NOT picked up
  by the analyser. So EXP-7 needs BOTH arms dispatched fresh under
  experiment_id=retry_chaining_mt_v1 (paired, symmetric, cold): 
    baseline arm: no --chained, --condition-label baseline
    chained  arm: --chained,   --condition-label chained
  = 120 runs. Confirm against docs/EXPERIMENTS_CHAINING.md before running (it may
  permit retro-tagging the existing baseline to halve it). Read that doc in the
  EXP-7 step. Register experiments row retry_chaining_mt_v1 first (R12).
- EXP-7 country set: all 60 canonical MT pairs (no-gold-rich; FR barred). France
  barred per R4. NL is the secondary, deferred.
