#!/usr/bin/env bash
#
# One-command launcher for the EXP-36 frozen headline run.
#
# Everything is prepared: the frozen code is tagged `exp36-config-freeze`, the
# dispatch DB is purged + registered, the spec is pinned. This script runs the
# full pre-dispatch gate then dispatches. It is RESUME-SAFE: if an EXP-36 run is
# already in progress in data/odmi.db it resumes rather than re-staging, so it
# is also the correct command to re-run after any interruption.
#
#   bash scripts/run_exp36.sh
#
# Abort anytime during the 15s countdown before the real dispatch.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
SPEC="evaluation/specs/exp36_frozen_headline.json"
DISPATCH_DB_SRC="/Users/benjyb/Desktop/MscProject/data/odmi.exp36-dispatch.db"
CANONICAL_ENV="/Users/benjyb/Desktop/MscProject/.env"

echo "== EXP-36 launcher =="
echo "repo: $ROOT"
echo "HEAD: $(git rev-parse --short HEAD)"

# 1. Freeze gate: HEAD must be the tagged config, tree clean (DB excepted).
echo "-- freeze gate --"
uv run python scripts/assert_freeze.py

# 2. .env must exist (llm.py auto-loads it from the checkout root; it is
#    git-ignored, so a fresh worktree has none and every call fails auth).
if [ ! -f .env ]; then
  echo "-- .env missing; copying canonical --"
  cp "$CANONICAL_ENV" .env
fi

# 3. Auth preflight: a couple of live 4.6 calls, fail fast if the proxy is down.
echo "-- auth / transport preflight --"
uv run python scripts/loadtest_proxy.py --n 2 --concurrency 2

# 4. Stage the dispatch DB, but only if a run is not already under way (so a
#    resume never wipes finalised pairs). "Under way" = EXP-36 registered here.
REG=$(uv run python -c "import sqlite3;print(sqlite3.connect('data/odmi.db').execute(\"SELECT COUNT(*) FROM experiments WHERE experiment_id='exp36_frozen_headline'\").fetchone()[0])")
if [ "$REG" = "0" ]; then
  echo "-- staging fresh dispatch DB (backup first) --"
  cp data/odmi.db "data/odmi.db.prerun-backup" 2>/dev/null || true
  cp "$DISPATCH_DB_SRC" data/odmi.db
else
  echo "-- EXP-36 already staged in data/odmi.db; resuming (no re-stage) --"
fi

# 5. Verify the staged DB is purged of held-out cache (the preflight enforces
#    this too for a headline spec, but check loudly here as well).
echo "-- held-out cache re-scan (expect 0/0/0) --"
uv run python scripts/purge_heldout_cache.py --db data/odmi.db | grep identified

# 6. Auto-publish OFF so the disposable dispatch DB is never committed to main.
export ODMI_SKIP_AUTO_PUBLISH=1

# 7. Dry-run, then dispatch.
echo "-- dry-run --"
uv run python scripts/run_experiments.py "$SPEC" --dry-run

echo ""
echo ">>> Pre-flight clean. Dispatching EXP-36 (the one-shot held-out run) in 15s."
echo ">>> Ctrl-C now to abort. Stratum B (FI SE BE HR) runs first; watch FI."
sleep 15
uv run python scripts/run_experiments.py "$SPEC"

echo ""
echo "== EXP-36 dispatch returned. Next: export finals + FM-14 audit (runbook step 6-7). =="
