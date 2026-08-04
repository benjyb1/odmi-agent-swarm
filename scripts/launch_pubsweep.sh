#!/bin/bash
# Launch the publication-hygiene sweep, detached and caffeinated.
#
# Same shape as launch_overnight.sh: the watchdog owns the supervisor and
# relaunches it on death, holds its own caffeinate assertion tied to its pid,
# and daemonises itself because macOS has no setsid(1).
#
# The deterministic layer must have run first, into --qa.

set -euo pipefail

REPO="/Users/benjyb/Desktop/MscProject/.claude/worktrees/dissertation-review-agent-f6ad5c"
OUT="${1:-$REPO/build/pubsweep}"
QA="${2:-$REPO/build/pub}"

cd "$REPO"
mkdir -p "$OUT"

if [ -f "$OUT/watchdog_status.json" ]; then
  RUNNING_PID=$(python3 -c "
import json,os
try:
    p = json.load(open('$OUT/watchdog_status.json')).get('watchdog_pid')
    os.kill(int(p), 0)
    print(p)
except Exception:
    print('')
" 2>/dev/null || true)
  if [ -n "$RUNNING_PID" ]; then
    echo "already running, watchdog pid $RUNNING_PID"
    exit 0
  fi
fi

python3 scripts/overnight_watchdog.py --out "$OUT" --daemon \
  --script scripts/publication_sweep.py --extra --qa "$QA" \
  >> "$OUT/launcher.log" 2>&1

sleep 5
echo "launched. out=$OUT"
echo "watchdog log:   $OUT/watchdog.log"
echo "supervisor log: $OUT/supervisor.log"
echo "findings:       $OUT/findings/"
