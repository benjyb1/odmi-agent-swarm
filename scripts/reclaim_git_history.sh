#!/bin/bash
# Reclaim the ~21GB of .git bloat caused by committing data/odmi.db (218MB) across
# main's history. This REWRITES HISTORY and FORCE-PUSHES, so it is destructive and
# desyncs every other clone/worktree/branch. Run it ONLY when EXP-21 (and any other
# run) is finished and the working tree is clean.
#
# Strategy: strip data/odmi.db from ALL history, then re-add the current DB as one
# fresh commit so HEAD still carries it (the Streamlit deploy, D23, keeps working).
# The history bloat is gone; the DB will slowly re-grow on future batch commits, so
# the permanent fix is to stop tracking it (git rm --cached + .gitignore) and deploy
# the DB to Streamlit another way - that is a workflow decision for Benjy.
#
# Usage: CONFIRM_REWRITE=yes bash scripts/reclaim_git_history.sh
set -euo pipefail
cd /Users/benjyb/Desktop/MscProject

# --- Safety guards (refuse unless genuinely safe) ---
[ "${CONFIRM_REWRITE:-}" = "yes" ] || { echo "Refusing: set CONFIRM_REWRITE=yes to proceed (this force-pushes rewritten history)."; exit 1; }
if pgrep -f overnight_driver.sh >/dev/null || pgrep -f "run_experiments.py" >/dev/null; then
  echo "Refusing: an experiment is still running. Stop it first so the DB is not mid-write."; exit 1
fi
if lsof data/odmi.db >/dev/null 2>&1; then
  echo "Refusing: data/odmi.db is open by a live process. Close all swarm processes first."; exit 1
fi
if [ -n "$(git status --porcelain | grep -v '^??')" ]; then
  echo "Refusing: working tree not clean. Commit or set aside changes (incl. odmi.db) first."; exit 1
fi
command -v git-filter-repo >/dev/null || { echo "Install git-filter-repo first: 'brew install git-filter-repo' or 'uv pip install git-filter-repo'."; exit 1; }

echo "Backing up the current DB to /tmp/odmi.db.prerewrite.bak ..."
cp data/odmi.db /tmp/odmi.db.prerewrite.bak

echo "Size before: $(du -sh .git | cut -f1)"
echo "Stripping data/odmi.db from all history (filter-repo) ..."
git filter-repo --path data/odmi.db --invert-paths --force

echo "Re-adding the current DB as one fresh commit so HEAD keeps it ..."
cp /tmp/odmi.db.prerewrite.bak data/odmi.db
git add data/odmi.db
git commit -q -m "chore: re-add current odmi.db after history reclaim (drops ~21GB of DB blobs)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"

git reflog expire --expire=now --all
git gc --prune=now --aggressive
echo "Size after: $(du -sh .git | cut -f1)"

echo "Re-adding origin remote (filter-repo drops it) and force-pushing ..."
git remote get-url origin >/dev/null 2>&1 || git remote add origin git@github.com:benjyb1/odmi-agent-swarm.git
echo ">>> Review the size above. To publish the rewrite, run:  git push --force origin main"
echo ">>> (left as a manual step on purpose: force-push rewrites public history)."
