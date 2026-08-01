"""Regenerate EXP-6 candidate pairs whose Researcher evidence leaked the answer key.

Some legacy (pre-deny-list) Researcher rows cited the deny-listed answer-key
domains (data.europa.eu, incl. ODMI factsheet PDFs). Rather than drop those pairs
from the experiment, this driver re-dispatches the swarm on them with the deny-list
enforced, so each pair gets a fresh clean Researcher row. It loops until every
candidate pair's LATEST Researcher row is deny-list-clean (or a pair is stuck),
which is what makes the EXP-6 candidate set both leakage-free and complete.

- Provider pinned to Brave: Serper (DIY) is out of credits and Tavily's quota is
  exhausted, so Brave is the one working search provider; its results pass the
  same deny-list scrub.
- Tagged experiment_id so the regenerated phase2_final rows do NOT duplicate the
  baseline finals (the EXP-6 judge reads phase2_researcher_runs and takes the
  latest row per pair regardless of condition, so the fresh clean row wins).
- Stuck detection: if a pair cannot produce a clean answer-bearing row across two
  consecutive rounds (e.g. it can only be answered from the deny-listed source and
  now abstains/fails), it is reported and the loop stops rather than spinning.

Usage:
    uv run python scripts/regen_leaked_pairs.py --parallel 3
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
os.environ.setdefault("ODMI_SKIP_AUTO_PUBLISH", "1")

import dispatch_subtrios  # noqa: E402
from agents.tools.blocked_domains import is_blocked  # noqa: E402
from agents.tools.search_serper import check_serper_credits  # noqa: E402

# Sole, held-constant search provider for the experiment (no fallback).
PROVIDER = "diy"

DB = REPO / "data" / "odmi.db"
CANDIDATE_COUNTRIES = ["MT", "NL", "FR", "EE"]
EXPERIMENT_ID = "exp6_regen_clean"
COOLDOWN_S = 600
MAX_ROUNDS = 30
STUCK_LIMIT = 2


def _blocked(row: sqlite3.Row) -> bool:
    """True if the row cited, fetched or read a deny-listed URL (D24)."""
    urls = [row["source_url"] or ""]
    # Both columns hold free-form JSON written by several generations of the
    # dispatcher, so early rows carry shapes the current parse rejects. An
    # unparseable column contributes no URLs and the row is judged on the ones
    # that did parse. source_url sits outside the try and is always checked.
    try:
        urls += [u for u in json.loads(row["fetched_urls"] or "[]")]
    except Exception:
        pass
    try:
        for s in json.loads(row["search_snippets"] or "[]"):
            if isinstance(s, dict):
                urls.append(s.get("url") or "")
    except Exception:
        pass
    return any(u and is_blocked(u) for u in urls)


def leaked_latest_pairs() -> list[tuple[str, str]]:
    """Pairs whose latest answer-bearing Researcher row still leaks."""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        targets = []
        for cc in CANDIDATE_COUNTRIES:
            rows = con.execute(
                "select * from phase2_researcher_runs where country_code=? "
                "and answer is not null order by id", (cc,),
            ).fetchall()
            latest = {}
            for r in rows:
                latest[(r["question_id"], r["country_code"])] = r
            for k, r in latest.items():
                if _blocked(r):
                    targets.append(k)
        return targets
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--cooldown", type=int, default=COOLDOWN_S)
    args = ap.parse_args()

    ok, reason = check_serper_credits()
    if not ok:
        print(f"[regen] ABORTED: Serper (sole search provider) unavailable -> "
              f"{reason}. Top up Serper credits; no silent fallback.", flush=True)
        return 2

    prev = None
    stuck = 0
    for rnd in range(1, MAX_ROUNDS + 1):
        targets = leaked_latest_pairs()
        print(f"\n[regen] round {rnd}: {len(targets)} pairs still leaking "
              f"{dict(Counter(cc for _, cc in targets))}", flush=True)
        if not targets:
            print("[regen] all candidate pairs have a clean latest row. Done.",
                  flush=True)
            return 0

        result = dispatch_subtrios.dispatch(
            pairs=targets,
            provider=PROVIDER,
            parallel_limit=args.parallel,
            batch_id="exp6_regen",
            experiment_id=EXPERIMENT_ID,
            condition_label="regen_clean",
        )
        if result.rate_limited:
            print(f"[regen] rate-limited; cooling {args.cooldown}s then resuming.",
                  flush=True)
            time.sleep(args.cooldown)
            stuck = 0
            prev = None
            continue

        now = len(leaked_latest_pairs())
        if prev is not None and now >= prev:
            stuck += 1
            print(f"[regen] no progress ({now} still leaking); stuck={stuck}/{STUCK_LIMIT}",
                  flush=True)
        else:
            stuck = 0
        prev = now
        if stuck >= STUCK_LIMIT:
            still = leaked_latest_pairs()
            print(f"[regen] giving up after {stuck} stuck rounds. These pairs cannot "
                  f"produce a clean answer-bearing row (likely answerable only from "
                  f"the deny-listed source): {sorted(still)}", flush=True)
            print("[regen] they will be excluded by the candidate-build deny-list "
                  "filter, so the experiment stays fair; reported as a coverage gap.",
                  flush=True)
            return 1

    print("[regen] hit MAX_ROUNDS.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
