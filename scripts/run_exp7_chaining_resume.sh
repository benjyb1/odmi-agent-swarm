#!/usr/bin/env bash
# EXP-7 resumable driver. Same pinned knobs as scripts/run_exp7_chaining.sh,
# but each iteration dispatches only the frozen-draw pairs that do not yet
# have a phase2_final row in the given arm, then loops. This is resume after a
# D43 DIY-blocker stop, not selective re-running: a pair that finalised as
# agent_failure keeps its row and is never re-rolled (R11).
#
# The D43 blocker (any DIY fetch >30s halts the batch) fires readily while the
# verifier-redesign harness loads the machine, so the loop sleeps between
# attempts and gives up after MAX_ATTEMPTS per arm. Exit 42 (rate limit)
# aborts outright.
set -uo pipefail
cd "$(dirname "$0")/.."
export ODMI_SKIP_AUTO_PUBLISH=1

EXPERIMENT_ID=retry_chaining_mt_v1
MAX_ATTEMPTS=15
SLEEP_BETWEEN=90

remaining_pairs () {
  local label="$1"
  uv run python - "$label" <<'PY'
import json, sqlite3, sys
label = sys.argv[1]
draw = json.load(open("evaluation/results/exp7_pairs_retry_chaining_mt_v1.json"))
conn = sqlite3.connect("data/odmi.db")
# A pair is done if it has ANY finalised row in this arm. Do NOT require a
# retry_count=0 researcher row: the coordinator's resume path can pick up an
# orphaned 'researching' row from a prior dispatch attempt and resume at
# retry_count=1, so a perfectly finalised pair may have no attempt-0 row. The
# earlier retry_count=0 join missed exactly those pairs (P6/PT18/PT9), declared
# them unfinished, and re-dispatched them forever (2026-06-11). Matching on any
# condition_label-tagged researcher row for the finalised pair_run_id is the
# correct completion test, and mirrors how chaining_analysis.load_outcomes
# attributes a final to an arm.
done = {
    row[0]
    for row in conn.execute(
        """SELECT DISTINCT f.question_id
           FROM phase2_final f
           JOIN phase2_researcher_runs r
             ON r.pair_run_id = f.pair_run_id
           WHERE f.experiment_id = ? AND f.country_code = 'MT'
             AND r.condition_label = ?""",
        ("retry_chaining_mt_v1", label),
    )
}
print(" ".join(q + ":MT" for q in draw["question_ids"] if q not in done))
PY
}

run_arm () {
  local label="$1"; shift
  for attempt in $(seq 1 $MAX_ATTEMPTS); do
    PAIRS=$(remaining_pairs "$label")
    if [ -z "$PAIRS" ]; then
      echo "=== $(date '+%H:%M:%S') EXP-7 arm $label complete (all pairs finalised) ==="
      return 0
    fi
    echo "=== $(date '+%H:%M:%S') EXP-7 arm $label attempt $attempt: $(echo $PAIRS | wc -w | tr -d ' ') pairs remaining ==="
    uv run python scripts/dispatch_subtrios.py \
      --pairs $PAIRS \
      --provider diy --no-cache \
      --strategy verifier-disprove \
      --max-results-per-query 5 --max-retries 3 \
      --parallel 2 \
      --experiment-id "$EXPERIMENT_ID" \
      --condition-label "$label" \
      "$@"
    rc=$?
    if [ $rc -eq 42 ]; then
      echo "!! arm $label hit the rate limit (42) - aborting driver"
      exit 42
    fi
    if [ $rc -ne 0 ]; then
      echo "-- arm $label attempt $attempt exited $rc (43=DIY blocker); sleeping ${SLEEP_BETWEEN}s and resuming"
      sleep $SLEEP_BETWEEN
    fi
  done
  echo "!! arm $label still incomplete after $MAX_ATTEMPTS attempts - reporting partial (R11)"
  return 1
}

run_arm baseline
baseline_rc=$?
run_arm chained --chained
chained_rc=$?

echo "=== $(date '+%H:%M:%S') EXP-7 driver done (baseline rc=$baseline_rc chained rc=$chained_rc) ==="
exit $(( baseline_rc || chained_rc ))
