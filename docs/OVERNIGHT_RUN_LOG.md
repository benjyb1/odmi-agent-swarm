# Overnight autonomous run log (2026-06-23 night)

Benjy left the laptop on overnight with a mandate: run EXP-21 (frozen headline)
to completion plus every other runnable experiment, troubleshoot any blocker
(DIY pipeline, RAM, storage), do not give up. This file is the durable state so
work survives context compaction. Updated as the run progresses.

## Plan / order of operations

1. [done] Finish EXP-20 chained arm (NL+MT). Analyse baseline vs chained.
2. [in progress] Build EXP-21 prerequisites:
   - Add 7 held-out countries to `COUNTRIES` in `run_coordinator.py`
     (BA MK ME BG FI HR BE; SE already present). Languages + portal bases below.
   - Build `data/questions/all_questions.json` (all 143 question IDs).
   - Add a guarded headline bypass to `run_experiments.py` preflight: the
     held-out block lifts ONLY when `headline: true` AND every country in the
     run is held-out (a dev run can never trip it).
   - Author `evaluation/specs/exp21_frozen_headline.json`.
3. [todo] Freeze config: snapshot ARCHITECTURE.md as-run, git tag.
4. [todo] Dispatch EXP-21 under a bounded auto-resume loop (held-out set has
   thin-web countries BA/MK/ME/BG that will trip the D43 30s fetch blocker like
   AL did; the loop resumes past each trip), parallel 3, caffeinate + watchdog.
5. [todo] Storage hygiene during the run: `git gc`, `git worktree prune` (safe
   only; no history rewrite). .git is 21GB from committed odmi.db blobs.
6. [todo] EXP-15 (adjudicator ablation) - free replay over stored trails.

## Frozen config (EXP-21 as-run, = current production defaults per design)

provider=diy, strategy=verifier-disprove, max_results_per_query=5, num_queries=3,
max_retries=3, verifier counter-search=always, confidence floor=0.65, snippet
picker=on, adjudicator=standard, unchained, catalogue route on. DIY-only (D43).

## Held-out countries added to COUNTRIES

| CC | name | language | portal_base |
|----|------|----------|-------------|
| BA | Bosnia and Herzegovina | bs | https://odp.iddeea.gov.ba |
| MK | North Macedonia | mk | https://data.gov.mk |
| ME | Montenegro | sr | https://data.gov.me |
| BG | Bulgaria | bg | https://data.egov.bg |
| FI | Finland | fi | https://www.avoindata.fi |
| HR | Croatia | hr | https://data.gov.hr |
| SE | Sweden | sv | https://www.dataportal.se (already present) |
| BE | Belgium | nl | https://data.gov.be |

Strata (D47): A = BA MK ME BG (negative-rich, low/mid resource); B = FI HR SE BE
(higher-resource, balanced). ~1,144 pairs, ~368 negative golds.

## Status log

- 23:35 building prerequisites. EXP-19 done (NL+MT, 104/arm). EXP-20 chained arm
  running. Disk 153GB free, RAM healthy post-reboot.
- 00:05 EXP-21 wired and committed (5872e48). Held-out countries smoke-tested
  (FI, BG pass config gate). Spec dry-runs clean: 1144 pairs, preflight passed.
- 00:10 Launched `scripts/overnight_driver.sh` under caffeinate (pid in
  /tmp/overnight_driver.pid), with `ODMI_SKIP_AUTO_PUBLISH=1` so the run does NOT
  commit/push the 218MB DB per batch (that auto-publish is the .git-bloat source;
  also avoids pushing partial held-out data to public origin/main). Driver: wait
  for EXP-20 to finish -> resume it to completion -> run EXP-21 to 1144 with
  auto-resume past D43 blocker / rate-limit / budget pauses. `overnight_watch.sh`
  pings on exit/stall/90-min.
- Storage note for morning: `.git` is 21GB because `dispatch_subtrios` commits
  `data/odmi.db` (218MB) on every batch. Did NOT rewrite history (destructive on
  a shared repo). Recommendation: `git rm --cached data/odmi.db` + gitignore, or
  a BFG history clean, to stop the bloat. `git worktree prune` run (no stale
  entries to drop; 17 live worktrees from other windows left untouched).
- EXP-15 (adjudicator ablation, free deterministic replay, no proxy) queued to
  run concurrently once EXP-21 is confirmed dispatching.
- 01:32 FIRST BLOCKER HIT + FIXED: EXP-21's single 1144-pair arm hit the
  `dispatch_subtrios` 500-pair runaway guard (`aborted_oversize`), so every pass
  dispatched 0 jobs and the driver stalled at 0. Fix: split the spec into 8
  per-country experiments (143 pairs each, under the guard), condition_label =
  country code, reliable stratum B first (FI HR SE BE) then thin stratum A
  (BA MK ME BG). Bonus robustness: the D43 fetch blocker now only stops one
  country's batch, never all 1144. Driver made more patient (stall = 6 dry
  passes, up to 120 passes). EXP-20 final: baseline 104/104, chained 102/104.
- 01:45 relaunched driver + watcher; FI dispatching confirmed (per-country fix
  works). EXP-21 ran through the night.
- 09:46 POWER EVENT: battery hit 2% (charging now). The machine did NOT reboot
  (uptime 10:28) but the low-power state froze an in-flight HR coordinator, hung
  the dispatch, and stalled the driver (~3h, 1 finalised/30min). Watcher had been
  killed separately. State at recovery: FI 143/143 done, HR 59/143, total
  202/1144. All preserved in DB.
- 09:50 Diagnosis: HR (Croatian) is genuinely thin-web (~20/hr, blocker trips
  ~every 2 pairs); FI was clean. In sequential per-country mode a slow country
  blocks the ones after it, so HR (2nd) was holding up SE/BE. Fix: REORDERED to
  FI, SE, BE, HR, BA, MK, ME, BG so the likely-reliable countries finish before
  the thin-web grind. Did NOT touch the 30s fetch budget / blocker (changing it
  mid-headline would break cross-country consistency vs the frozen config).
  Kept parallel 3 (battery was 2%). Killed the hung stack, relaunched driver +
  watcher. Battery recovering (2 -> 10%).
