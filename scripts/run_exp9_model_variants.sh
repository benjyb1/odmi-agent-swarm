#!/usr/bin/env bash
# EXP-9 (Family 3): model-variant dispatch over the canonical Malta 60-pair set.
#
# One variable only: the model. Every other knob is pinned identically across
# arms (the no-confound rule, D38; "never dispatch an arm on --provider auto"):
#   provider diy (D43, explicit), cold cache (--no-cache, R9), verifier-disprove,
#   5 results/query, 3 retries, full prompt (no --prompt-variant), unchained.
# All arms share experiment_id=model_variants_mt; one condition_label per arm.
#
# Caveat recorded in EXPERIMENTS.md: this run may overlap the Norway dev sweep,
# so the wall-clock latency endpoint can be inflated by machine contention. The
# headline token-cost endpoint and the accuracy comparison are unaffected (arms
# run sequentially under roughly constant background load). The 30s DIY blocker
# (D43) is robust to contention because each per-URL fetch is bounded to <=26s.
#
# Arms run sequentially (so they do not contend with each other). The driver
# stops if any arm exits non-zero (a 429 shutdown, a DIY blocker, or an error),
# so a partial arm is never silently left half-run.
set -uo pipefail
cd "$(dirname "$0")/.."
export ODMI_SKIP_AUTO_PUBLISH=1

HAIKU=claude-haiku-4-5-20251001
SONNET=claude-sonnet-4-6
OPUS=claude-opus-4-6   # served by the proxy; matches the pre-registration
MISTRAL=mistral-large-latest

PAIRS=$(uv run python -c "import json;print(' '.join(p['question_id']+':MT' for p in json.load(open('data/questions/malta_eval_pairs.json'))['pairs']))")
echo "EXP-9: $(echo $PAIRS | wc -w) Malta pairs per arm"

run_arm () {
  local label="$1" r="$2" v="$3" a="$4"
  echo "=== $(date '+%H:%M:%S') EXP-9 arm $label : R=$r V=$v A=$a ==="
  uv run python scripts/dispatch_subtrios.py \
    --pairs $PAIRS \
    --provider diy --no-cache \
    --strategy verifier-disprove \
    --max-results-per-query 5 --max-retries 3 \
    --parallel 2 \
    --experiment-id model_variants_mt \
    --condition-label "$label" \
    --researcher-model "$r" --verifier-model "$v" --adjudicator-model "$a"
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "!! arm $label exited $rc (42=rate-limit, 43=DIY blocker) - stopping EXP-9 driver"
    exit $rc
  fi
}

run_arm model-haiku   "$HAIKU"  "$HAIKU"  "$HAIKU"
run_arm model-sonnet  "$SONNET" "$SONNET" "$SONNET"
run_arm model-opus    "$OPUS"   "$OPUS"   "$OPUS"
run_arm model-tiered  "$HAIKU"  "$SONNET" "$OPUS"
run_arm model-mistral "$MISTRAL" "$MISTRAL" "$MISTRAL"

echo "=== $(date '+%H:%M:%S') EXP-9 all five arms dispatched ==="
