#!/usr/bin/env bash
# EXP-7: retry chaining / evidence accumulation, baseline vs chained.
#
# Pre-registered in docs/EXPERIMENTS_CHAINING.md. Paired design: both arms run
# the identical frozen Malta pair draw (30 no-gold + 10 yes-gold, seed
# 20260603, evaluation/results/exp7_pairs_retry_chaining_mt_v1.json). One
# variable only (the --chained flag); every other knob pinned to the EXP-9
# baseline: provider diy (D43, explicit, never auto), cold cache (--no-cache,
# R9), verifier-disprove, 5 results/query, 3 retries, full prompt, default
# Sonnet models. Arms run sequentially (cleanliness, not throughput; the
# resume path is scoped by experiment_id + condition_label so no row crosses
# arms).
#
# Caveat recorded with the run: a verifier-redesign harness shares the Claude
# proxy during this window, so wall-clock latency is contention-inflated. The
# accuracy, false-positive, and calls-per-pair endpoints are count- and
# token-based and unaffected.
set -uo pipefail
cd "$(dirname "$0")/.."
export ODMI_SKIP_AUTO_PUBLISH=1

PAIRS=$(uv run python -c "import json;d=json.load(open('evaluation/results/exp7_pairs_retry_chaining_mt_v1.json'));print(' '.join(q+':MT' for q in d['question_ids']))")
echo "EXP-7: $(echo $PAIRS | wc -w) Malta pairs per arm"

run_arm () {
  local label="$1"; shift
  echo "=== $(date '+%H:%M:%S') EXP-7 arm $label ==="
  uv run python scripts/dispatch_subtrios.py \
    --pairs $PAIRS \
    --provider diy --no-cache \
    --strategy verifier-disprove \
    --max-results-per-query 5 --max-retries 3 \
    --parallel 2 \
    --experiment-id retry_chaining_mt_v1 \
    --condition-label "$label" \
    "$@"
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "!! arm $label exited $rc (42=rate-limit, 43=DIY blocker) - stopping EXP-7 driver"
    exit $rc
  fi
}

run_arm baseline
run_arm chained --chained

echo "=== $(date '+%H:%M:%S') EXP-7 both arms dispatched ==="
