#!/bin/bash
# Overnight EXP-A / B / C chain wrapper, designed to be run detached.
#
# Each phase runs once; on non-zero exit the script exits with that code so
# the agent's poll loop can decide whether to relaunch. The orchestrator's
# resume is idempotent, so re-launching this script picks up wherever it
# stopped without re-running finished pairs.

set -u
export ODMI_SKIP_AUTO_PUBLISH=1
cd /Users/benjyb/Desktop/MscProject
LOG=/tmp/odmi_overnight.log

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

run_phase() {
  local name=$1
  local spec=$2
  echo "=== $name start $(stamp) ===" | tee -a "$LOG"
  uv run --no-project python scripts/run_experiments.py "$spec" >>"$LOG" 2>&1
  local code=$?
  echo "=== $name exit=$code $(stamp) ===" | tee -a "$LOG"
  return $code
}

run_phase EXP-A evaluation/specs/expA_calibration_anchors_nl.json || exit $?
run_phase EXP-B evaluation/specs/expB_verifier_fit_check_nl.json || exit $?
run_phase EXP-C evaluation/specs/expC_neg_evidence_licence_nl.json || exit $?

echo "=== ALL THREE DONE $(stamp) ===" | tee -a "$LOG"
exit 0
