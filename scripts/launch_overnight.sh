#!/bin/bash
# Launch the overnight dissertation review, detached and caffeinated.
#
# Detached via setsid so it survives the terminal, the SSH session and the
# Claude Code session that started it. caffeinate -dimsu holds the machine
# awake for as long as the watchdog runs, and dies with it.
#
#   -d  no display sleep      -i  no idle sleep
#   -m  no disk sleep         -s  stay awake on mains
#   -u  declare user activity so the display-sleep timer resets
#
# The watchdog owns the supervisor and relaunches it on death, so this script
# only has to start one process and get out of the way.

set -euo pipefail

REPO="/Users/benjyb/Desktop/MscProject/.claude/worktrees/dissertation-review-agent-f6ad5c"
OUT="${1:-$REPO/build/overnight}"

cd "$REPO"
mkdir -p "$OUT"

if [ -f "$OUT/watchdog_status.json" ]; then
  RUNNING_PID=$(python3 -c "
import json,os,sys
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

setsid nohup caffeinate -dimsu \
  python3 scripts/overnight_watchdog.py --out "$OUT" \
  >> "$OUT/launcher.log" 2>&1 &

sleep 3
echo "launched. out=$OUT"
echo "watchdog log:   $OUT/watchdog.log"
echo "supervisor log: $OUT/supervisor.log"
echo "final report:   $OUT/findings/_FINAL_REPORT.md"
