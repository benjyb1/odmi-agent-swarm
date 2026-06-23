#!/bin/bash
# Heartbeat watcher for the overnight driver. Exits (notifying the parent) on:
# driver exit, EXP-21 stall (~30 min no new finalised), or a 90-min heartbeat.
cd /Users/benjyb/Desktop/MscProject
cnt(){ uv run python -c "import sqlite3;print(sqlite3.connect('data/odmi.db').execute(\"SELECT COUNT(DISTINCT question_id||country_code) FROM phase2_final WHERE experiment_id='exp21_frozen_headline'\").fetchone()[0])" 2>/dev/null || echo -1; }
start=$SECONDS; last=-1; stuck=0
while true; do
  if ! pgrep -f overnight_driver.sh >/dev/null 2>&1; then echo "REASON: DRIVER EXITED"; break; fi
  n=$(cnt)
  if [ "${n:-0}" -gt 0 ]; then
    if [ "$n" = "$last" ]; then stuck=$((stuck+1)); else stuck=0; last=$n; fi
    if [ "$stuck" -ge 3 ]; then echo "REASON: EXP-21 STALLED ~30min at $n"; break; fi
  fi
  if [ $((SECONDS-start)) -ge 5400 ]; then echo "REASON: 90min heartbeat"; break; fi
  sleep 600
done
echo "=== SNAPSHOT $(date '+%m-%d %H:%M') ==="
echo "exp21 finalised: $(cnt)/1144"
pgrep -f overnight_driver.sh >/dev/null && echo "driver: ALIVE" || echo "driver: GONE"
tail -5 /tmp/overnight_driver.log 2>/dev/null