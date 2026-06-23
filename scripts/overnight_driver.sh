#!/bin/bash
# Overnight autonomous driver: finish EXP-20, then run EXP-21 to completion.
# Resilient to the D43 fetch blocker, rate-limit pauses, and budget pauses on the
# thin-web held-out countries: it simply re-runs the spec (idempotent resume) until
# the target is hit or progress dries up. Run under caffeinate.
cd /Users/benjyb/Desktop/MscProject
DB=data/odmi.db
log(){ echo "$(date '+%m-%d %H:%M:%S') | $*"; }

cnt(){ # distinct finalised pairs for an experiment_id
  uv run python -c "import sqlite3;print(sqlite3.connect('$DB').execute(\"SELECT COUNT(DISTINCT question_id||country_code) FROM phase2_final WHERE experiment_id='$1'\").fetchone()[0])" 2>/dev/null || echo 0
}

# ---- Phase 1: ensure EXP-20 (phase2_retests) is complete ----
# Wait for the in-flight EXP-20 orchestrator to exit, then resume up to 4x. A
# resume that finalises nothing new (delta 0) means it is done or genuinely stuck.
log "PHASE 1: EXP-20 finish"
while pgrep -f "run_experiments.py evaluation/specs/phase2_retests.json" >/dev/null 2>&1; do sleep 60; done
for i in $(seq 1 4); do
  before=$(cnt exp20_chaining_committing)
  uv run python scripts/run_experiments.py evaluation/specs/phase2_retests.json >> /tmp/exp20_driver.log 2>&1
  after=$(cnt exp20_chaining_committing)
  log "EXP-20 resume pass $i: chained $before -> $after"
  [ "$((after - before))" -lt 1 ] && { log "EXP-20 no new progress; treating as done"; break; }
done

# ---- Phase 2: EXP-21 frozen headline to completion ----
log "PHASE 2: EXP-21 frozen headline (target 1144)"
TARGET=1144
stall=0
for pass in $(seq 1 50); do
  before=$(cnt exp21_frozen_headline)
  log "EXP-21 pass $pass START finalised=$before/$TARGET"
  uv run python scripts/run_experiments.py evaluation/specs/exp21_frozen_headline.json >> /tmp/exp21_driver.log 2>&1
  after=$(cnt exp21_frozen_headline)
  delta=$((after - before))
  log "EXP-21 pass $pass DONE finalised=$after (+$delta)"
  [ "$after" -ge "$TARGET" ] && { log "EXP-21 COMPLETE ($after/$TARGET)"; break; }
  if [ "$delta" -lt 2 ]; then stall=$((stall+1)); else stall=0; fi
  if [ "$stall" -ge 4 ]; then log "EXP-21 STALLED ($stall passes <2 new); stopping for diagnosis"; break; fi
  sleep 5
done
log "DRIVER DONE exp21=$(cnt exp21_frozen_headline)/$TARGET"
