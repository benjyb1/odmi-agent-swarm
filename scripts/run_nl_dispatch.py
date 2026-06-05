"""Unattended NL dispatch driver for EXP-6 (secondary stratum).

Dispatches the swarm over data/questions/nl_eval_pairs.json and runs it to
completion. Each round it computes the pairs that do NOT yet have a finalised
phase2_final row under the baseline condition (experiment_id IS NULL) and
dispatches only those, so:
  - a rate-limit cooldown resumes cleanly (only the unfinished pairs re-run), and
  - already-finalised pairs are never re-run, which would both waste Claude Max
    budget and create duplicate phase2_final rows (the Malta dedup hazard).

An abstention (`inconclusive`) is a terminal phase2_final row (D37), so an
abstaining pair counts as done and is not retried forever. A pair that writes no
phase2_final at all (e.g. a hard search-empty failure) is retried; if the
remaining count stops shrinking across STUCK_LIMIT non-rate-limited rounds, the
driver stops and reports the stuck pairs rather than looping.

Usage:
    uv run python scripts/run_nl_dispatch.py --parallel 6
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

# Belt-and-suspenders: never auto-commit/push odmi.db mid-dispatch. The branch
# guard in publish_to_main already skips off main, this just makes it explicit.
os.environ.setdefault("ODMI_SKIP_AUTO_PUBLISH", "1")

import dispatch_subtrios  # noqa: E402

PAIRS_FILE = REPO / "data" / "questions" / "nl_eval_pairs.json"
DB = REPO / "data" / "odmi.db"
COOLDOWN_S = 600          # wait after a rate-limit before resuming
STUCK_LIMIT = 2           # consecutive non-progress rounds before giving up
MAX_ROUNDS = 300


def _finalised_qids() -> set[str]:
    """NL question_ids that already have a baseline phase2_final row."""
    con = sqlite3.connect(DB)
    try:
        rows = con.execute(
            "select distinct question_id from phase2_final "
            "where upper(country_code) = 'NL' and experiment_id is null"
        ).fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--strategy", default="verifier-disprove")
    ap.add_argument("--provider", default="auto")
    ap.add_argument("--cooldown", type=int, default=COOLDOWN_S)
    args = ap.parse_args()

    doc = json.loads(PAIRS_FILE.read_text())
    all_pairs = [(p["question_id"], p["country_code"]) for p in doc["pairs"]]
    print(f"[nl-driver] {len(all_pairs)} NL pairs in {PAIRS_FILE.name}", flush=True)

    prev_remaining = None
    stuck = 0
    for rnd in range(1, MAX_ROUNDS + 1):
        done = _finalised_qids()
        remaining = [(q, c) for (q, c) in all_pairs if q not in done]
        n_done = len(all_pairs) - len(remaining)
        print(f"\n[nl-driver] round {rnd}: {n_done}/{len(all_pairs)} finalised, "
              f"{len(remaining)} remaining", flush=True)
        if not remaining:
            print("[nl-driver] all pairs finalised. Done.", flush=True)
            return 0

        result = dispatch_subtrios.dispatch(
            pairs=remaining,
            strategy=args.strategy,
            parallel_limit=args.parallel,
            provider=args.provider,
            batch_id="nl_baseline",
        )

        if result.rate_limited:
            print(f"[nl-driver] rate-limited; cooling down {args.cooldown}s "
                  f"then resuming the remaining pairs.", flush=True)
            time.sleep(args.cooldown)
            stuck = 0          # a rate limit is not a stuck pair
            prev_remaining = None
            continue

        # Non-rate-limited round: check progress to avoid an infinite loop on
        # pairs that keep failing to finalise.
        now_remaining = len(
            [(q, c) for (q, c) in all_pairs if q not in _finalised_qids()]
        )
        if prev_remaining is not None and now_remaining >= prev_remaining:
            stuck += 1
            print(f"[nl-driver] no progress this round "
                  f"({now_remaining} still remaining); stuck={stuck}/{STUCK_LIMIT}",
                  flush=True)
        else:
            stuck = 0
        prev_remaining = now_remaining
        if stuck >= STUCK_LIMIT:
            still = [q for (q, c) in all_pairs if q not in _finalised_qids()]
            print(f"[nl-driver] giving up after {stuck} non-progress rounds. "
                  f"Stuck pairs (no phase2_final): {still}", flush=True)
            return 1

    print("[nl-driver] hit MAX_ROUNDS; stopping.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
