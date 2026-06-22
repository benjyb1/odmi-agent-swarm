# Session handoff — 2026-06-22

Branch `claude/magical-ride-e5f029`. Everything below is committed.

## First, when you reopen: the proxy

The CLIProxyAPI Max auth was re-logged-in this session, but it is served by a
**manual `nohup` instance that dies when the laptop closes**, and the brew/launchd
service is stuck in an "other" state. If swarm LLM calls fail
(`auth_unavailable` or connection refused), restart it:

```bash
nohup /opt/homebrew/bin/cliproxyapi -config /opt/homebrew/etc/cliproxyapi.conf > /tmp/cp.log 2>&1 &
disown
```
If that still reports no auth, re-login: `cliproxyapi -claude-login`. Verify:
```bash
curl -s http://localhost:8317/v1/messages -H "x-api-key: odmi-local-proxy-key" \
  -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":10,"messages":[{"role":"user","content":"OK"}]}'
```
The brew service needs a proper fix for durable management (separate task). The
worktree also needs `.env` (`cp /Users/benjyb/Desktop/MscProject/.env .env` if
missing — git worktrees do not copy it).

## What shipped this session

- **D47 (eval redesign).** Supersedes the D42 matrix. ODMI score = binary yes-share
  (r=0.98), so maturity and base-rate balance are one axis. Dev set: **NL, MT, NO,
  FR, AL**. Held-out eval set (**NEVER touch in any experiment**): **BA, MK, ME, BG,
  FI, HR, SE, BE**. Reporting is balance-aware + three-outcome.
- **D48 (experiment framework).** `scripts/run_experiments.py` (orchestrator) +
  `docs/EXPERIMENT_RUNBOOK.md` + `.claude/skills/run-experiment/`. Forces
  `--no-cache` on retrieval/cost arms, runs arms sequentially at one global search
  cap, preflight hard-fails on held-out countries / missing budget / >1 variable,
  self-pauses on budget or unhealthy arm, manifest + JSONL log per run. 21 tests.
- **Phase 0 (LLM-free, done):** candidate-recall audit (16% pooled selection
  headroom, 25pt on MT); adjudicator ablation (net +28, commit precision 0.72,
  net-negative on NO); counter-evidence independence (54% of Verifier
  counter-evidence re-cites the Researcher's exact URL). Scripts in `evaluation/`.
- **EXP-17 breadth (done):** results/query 5 -> 10 on NL (n=52) lifts candidate
  recall .67 -> .76, commit accuracy .45 -> .56, **no-gold recall .04 -> .20**,
  false positives **18 -> 12**, at +17% cost. Confirms "widen breadth". Analysis:
  `evaluation/analyze_breadth.py`.
- **Knob builds merged + tested (711 passing):**
  - EXP-14 `--verifier-search never|always` (elective stubbed): never = Verifier
    reasons over the Researcher's evidence only, no own web search.
  - EXP-16 `--adjudicator-selection standard|free`: free = Adjudicator can commit
    ANY of the up-to-4 Researcher attempts (new `attempt_correct` verdict).
  - EXP-17 `--snippet-picker on|off`, `--max-snippet-chars`, `--picker-max-chunks`,
    `--page-text-cap`. All flag-gated, defaults byte-identical.

## To resume

**Combined run was stopped partway** (laptop closing). `EXP-14 always` has 16/52
finalised; `never` and the EXP-17 picker arms did not start. Re-run the same spec
to resume — `dispatch_subtrios` skips already-finalised pairs:
```bash
uv run python scripts/run_experiments.py evaluation/specs/phase1_verifier_picker_nl.json
```
(~2.5 hr, ~10-12k Claude calls. Needs the proxy up.) This runs EXP-14 (no-search
verifier, the highest-value confirmation: EXP-12 found J 0.10 live -> 0.42 clean)
and EXP-17 picker (does the LLM picker bin the answer).

**EXP-16 not yet runnable.** The `free` arm needs an additive migration first:
`phase2_adjudications.adjudicator_verdict` has a CHECK constraint that excludes
`attempt_correct`. Write a table-recreate migration (SQLite cannot ALTER a CHECK)
to widen it, then spec `standard` vs `free` on NL. Targets the 74/44 selection
headroom.

**Still queued after those:** EXP-17 truncation (`--max-snippet-chars` 600 vs
1200/2000) and page-text-cap arms.

## Known minor issues

- `run_experiments.py` `arm_health` blocker_rate is experiment-wide
  (`subtrio_status` has no condition_label); the finalised count is per-arm.
- `smoke_nl` and the partial `exp14_verifier_search_nl` rows are tagged
  test/partial data, isolated from production (production = `experiment_id IS NULL`).
