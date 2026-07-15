"""Assert the working tree is frozen at the EXP-36 config tag before dispatch.

The freeze tag (`exp36-config-freeze`) certifies the exact commit the headline
run dispatched under. A stray edit between tagging and dispatch would silently
desync that certificate. Run this in the dispatch checkout immediately before
`run_experiments.py`; it exits non-zero unless:

  - the freeze tag exists and HEAD is exactly that commit, and
  - the working tree has no uncommitted changes to tracked files, except the
    DB copies (`data/odmi.db*`), which the dispatch legitimately writes to.

  uv run python scripts/assert_freeze.py            # default tag
  uv run python scripts/assert_freeze.py --tag exp36-config-freeze
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def _git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", default="exp36-config-freeze")
    args = ap.parse_args()

    rc, tag_commit = _git("rev-parse", "--verify", f"{args.tag}^{{commit}}")
    if rc != 0:
        print(f"NOT FROZEN: tag {args.tag!r} does not exist; apply it before "
              f"dispatch (git tag -a {args.tag} ...)")
        return 1

    _, head = _git("rev-parse", "HEAD")
    if head != tag_commit:
        print(f"NOT FROZEN: HEAD ({head[:12]}) is not the freeze tag "
              f"{args.tag} ({tag_commit[:12]}). Check out the tagged commit "
              f"before dispatch.")
        return 1

    # Working tree must be clean except the DB copies the run writes to.
    _, status = _git("status", "--porcelain")
    dirty = [
        line for line in status.splitlines()
        if line.strip() and not line[3:].startswith("data/odmi.db")
    ]
    if dirty:
        print("NOT FROZEN: uncommitted changes to tracked files:")
        for line in dirty:
            print(f"  {line}")
        return 1

    print(f"FROZEN: HEAD is at {args.tag} ({tag_commit[:12]}), tree clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
