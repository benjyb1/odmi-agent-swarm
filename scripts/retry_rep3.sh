#!/bin/bash
# Retry EXP-41 rep3 until the 5-hour Claude window has room.
#
# rep3's first attempt aborted at 0/156 because the window was saturated by
# rep1+rep2 back to back (all four opening pairs rate-limited). The overnight
# runner aborts cleanly on that (0 pairs, no partial data), so this just retries
# it on an interval until a run actually lands its pairs. Each attempt purges
# the cache and gates exactly as a first run would.
#
# Detached so it survives the session; a ScheduleWakeup check-in polls it, per
# the overnight-polling rule (a detached parent can be SIGKILLed silently).
set -u
cd /Users/benjyb/Desktop/MscProject
LOG=evaluation/runs/exp41_provenance/retry_rep3.log
DB=data/odmi.db
MAX=8
WAIT_S=2400   # 40 min between attempts

log(){ echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

log "retry wrapper started (max $MAX attempts, ${WAIT_S}s apart)"
# The window just rejected a dispatch, so cool down before the first real
# attempt rather than burning it on a saturated window.
log "initial cool-down 1800s before first attempt"
sleep 1800
for i in $(seq 1 $MAX); do
  # Skip straight to done if a prior attempt already completed rep3.
  n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM phase2_final WHERE experiment_id='exp41_stability_rep3';" 2>/dev/null || echo 0)
  if [ "${n:-0}" -ge 151 ]; then
    log "rep3 already at $n/156; nothing to do"; exit 0
  fi

  log "attempt $i/$MAX: launching overnight runner for rep3"
  uv run python scripts/run_exp41_overnight.py --replicates rep3 >> "$LOG" 2>&1
  rc=$?
  n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM phase2_final WHERE experiment_id='exp41_stability_rep3';" 2>/dev/null || echo 0)
  log "attempt $i finished rc=$rc, rep3 at $n/156"

  if [ "$rc" -eq 0 ] && [ "${n:-0}" -ge 151 ]; then
    log "rep3 complete at $n/156; running final analysis"
    uv run python evaluation/exp41_analysis.py --db "$DB" \
      --out evaluation/results/exp41_analysis.json >> "$LOG" 2>&1
    log "analysis written to evaluation/results/exp41_analysis.json"
    exit 0
  fi

  # Rate-limited or partial. Scrub any resumable half-state so the next attempt
  # is a clean draw (a rate-limited attempt-1 row would otherwise be replayed),
  # then wait for the window to cool.
  if [ "${n:-0}" -lt 151 ]; then
    sqlite3 "$DB" "DELETE FROM phase2_researcher_runs WHERE experiment_id='exp41_stability_rep3'; DELETE FROM phase2_verifier_runs WHERE experiment_id='exp41_stability_rep3'; DELETE FROM subtrio_status WHERE experiment_id='exp41_stability_rep3'; DELETE FROM phase2_final WHERE experiment_id='exp41_stability_rep3';" 2>>"$LOG"
    log "scrubbed rep3 partial state; sleeping ${WAIT_S}s before retry"
    sleep "$WAIT_S"
  fi
done
log "gave up after $MAX attempts; window may still be saturated. Re-run by hand."
exit 1
