#!/usr/bin/env python3
"""EXP-42 progress checkpoint: separate real results from operational failures.

Run at each 10% of the battery. The question it answers is narrow: is anything
going wrong that is the *machinery's* fault rather than the web's or the
question's?

The distinction that matters:

  * An **abstention** is a result. The corroborative verifier found no support
    and the pair declined to commit. That is the system working.
  * An **operational failure** is not. A crashed agent, a schema-invalid model
    response, a fetch timeout, a WAF block, a rate-limit interruption. These say
    nothing about verifier stance and must not be left sitting in the data as if
    they were abstentions.

Operational failures are recoverable: the orchestrator is resume-safe per pair,
so re-running the spec re-dispatches anything with no `phase2_final` row. This
script reports what would be recovered, so a sweep can be judged worthwhile
before it is spent.

Usage:
    uv run python evaluation/exp42_checkpoint.py
    uv run python evaluation/exp42_checkpoint.py --experiment-id exp42_pilot_heldout
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter

COUNTRIES = ["FI", "BE", "HR", "BG", "ME", "MK", "BA", "SE"]
PER_COUNTRY = 143
TARGET = len(COUNTRIES) * PER_COUNTRY

# Terminal statuses that are a real outcome, not a malfunction.
LEGITIMATE = {"accepted_cooperative", "abstained_cooperative"}

# failure_mode values that mean "the machinery broke", as opposed to
# "the evidence was not there". Anything matching is worth a retry.
TRANSIENT_HINTS = (
    "timeout", "blocker", "rate_limit", "schema_invalid", "http", "fetch",
    "connection", "crash", "unexpected", "empty", "parse", "5xx", "429", "403",
)


def completed_arms(eid: str) -> set[str]:
    """Country codes whose arm the orchestrator has reported done.

    Read from the run's own event log rather than inferred from row counts: an
    arm that finished at 141/143 is complete-with-gaps, which is exactly the
    case worth reporting, and a count-based guess cannot tell that apart from
    an arm still in flight.
    """
    import json
    from pathlib import Path

    path = Path("evaluation/runs") / eid / "events.jsonl"
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text().splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("event") == "arm_done" and ev.get("condition_label"):
            done.add(ev["condition_label"])
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/odmi.db")
    ap.add_argument("--experiment-id", default="exp42_stance_heldout")
    args = ap.parse_args()
    eid = args.experiment_id
    c = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=20)

    print("=" * 70)
    print(f"EXP-42 CHECKPOINT  ({eid})")
    print("=" * 70)

    # ---------- progress ----------
    per_cc = dict(c.execute(
        "SELECT country_code, COUNT(*) FROM phase2_final WHERE experiment_id=? "
        "GROUP BY 1", (eid,)))
    total = sum(per_cc.values())
    print(f"\nfinalised {total}/{TARGET}  ({total / TARGET:.1%})")
    for cc in COUNTRIES:
        n = per_cc.get(cc, 0)
        bar = "#" * int(n / PER_COUNTRY * 24)
        print(f"  {cc} {n:>4}/{PER_COUNTRY} |{bar:<24}|")

    # ---------- outcomes ----------
    print("\n--- terminal statuses ---")
    statuses = Counter(dict(c.execute(
        "SELECT terminal_status, COUNT(*) FROM phase2_final WHERE experiment_id=? "
        "GROUP BY 1", (eid,))))
    bad_status = 0
    for st, n in statuses.most_common():
        tag = "" if st in LEGITIMATE else "   <-- OPERATIONAL"
        if st not in LEGITIMATE:
            bad_status += n
        print(f"  {st:<28} {n:>5}{tag}")

    # ---------- agent-side failures ----------
    print("\n--- agent failure_mode (researcher / verifier rows) ---")
    any_fm = False
    retryable_pairs = set()
    for table, who in (("phase2_researcher_runs", "researcher"),
                       ("phase2_verifier_runs", "verifier")):
        rows = c.execute(
            f"SELECT failure_mode, COUNT(*) FROM {table} "
            f"WHERE experiment_id=? AND failure_mode IS NOT NULL "
            f"AND failure_mode != '' GROUP BY 1 ORDER BY 2 DESC", (eid,)
        ).fetchall()
        if not rows:
            print(f"  {who}: none")
            continue
        any_fm = True
        for fm, n in rows:
            transient = any(h in (fm or "").lower() for h in TRANSIENT_HINTS)
            print(f"  {who:<11} {fm:<34} {n:>5}"
                  f"{'   <-- retryable' if transient else ''}")
        # which pairs do those failures belong to, and did they still finalise?
        for q, cc in c.execute(
            f"SELECT DISTINCT question_id, country_code FROM {table} "
            f"WHERE experiment_id=? AND failure_mode IS NOT NULL "
            f"AND failure_mode != ''", (eid,)
        ):
            retryable_pairs.add((q, cc))
    if not any_fm:
        print("  (no agent failure_mode recorded)")

    # ---------- the real recovery target ----------
    # A pair only needs retrying if it has NO terminal row. Everything else
    # already has an outcome, transient failures included, because the retry
    # loop absorbed them.
    done = {(q, cc) for q, cc in c.execute(
        "SELECT question_id, country_code FROM phase2_final WHERE experiment_id=?",
        (eid,))}
    # Only an arm the orchestrator has FINISHED can have missing pairs. An arm
    # still dispatching has pending pairs, which are not failures and must not
    # be counted as a recovery target, or every checkpoint mid-arm reads as a
    # fault.
    finished_cc = completed_arms(eid)
    missing_in_started = []
    for cc in COUNTRIES:
        if cc not in finished_cc:
            continue
        allq = {q for (q,) in c.execute(
            "SELECT DISTINCT question_id FROM ground_truth WHERE country_code=?",
            (cc,))}
        for q in sorted(allq):
            if (q, cc) not in done:
                missing_in_started.append((q, cc))

    print("\n--- recovery target ---")
    print(f"  pairs with a failure_mode logged somewhere : {len(retryable_pairs)}")
    print(f"  of those, already finalised anyway         : "
          f"{len(retryable_pairs & done)}")
    print(f"  MISSING a terminal row, in a started arm   : "
          f"{len(missing_in_started)}   <-- what a resume sweep recovers")
    if missing_in_started:
        shown = ", ".join(f"{q}:{cc}" for q, cc in missing_in_started[:18])
        more = "" if len(missing_in_started) <= 18 else \
            f"  (+{len(missing_in_started) - 18} more)"
        print(f"    {shown}{more}")

    # ---------- duplicates ----------
    # A resume can re-dispatch a pair it should have skipped. `finalised_pairs`
    # in the orchestrator identifies done pairs by joining phase2_final to
    # phase2_researcher_runs for the condition_label, so a final with no
    # researcher row is invisible to it and gets run twice. Harmless to the
    # answer when both rows agree, but it inflates counts past 143 and must be
    # deduped on (question_id, country_code) before any analysis, exactly as
    # EXP-36 does.
    print("\n--- duplicate finals ---")
    dupes = c.execute(
        "SELECT question_id, country_code, COUNT(*) n FROM phase2_final "
        "WHERE experiment_id=? GROUP BY 1,2 HAVING n>1 ORDER BY n DESC", (eid,)
    ).fetchall()
    at_risk = c.execute(
        "SELECT COUNT(*) FROM phase2_final f WHERE f.experiment_id=? "
        "AND NOT EXISTS (SELECT 1 FROM phase2_researcher_runs r "
        "WHERE r.pair_run_id=f.pair_run_id AND r.condition_label=f.country_code)",
        (eid,)
    ).fetchone()[0]
    print(f"  finals invisible to the resume skip-set : {at_risk}"
          f"   (each can be re-run once per sweep)")
    if dupes:
        disagree = 0
        for q, cc, _n in dupes:
            outcomes = {
                (st, (ans or "").strip().lower()) for st, ans in c.execute(
                    "SELECT terminal_status, final_answer FROM phase2_final "
                    "WHERE experiment_id=? AND question_id=? AND country_code=?",
                    (eid, q, cc))
            }
            if len(outcomes) > 1:
                disagree += 1
        print(f"  duplicated pairs: {len(dupes)}  "
              f"({', '.join(f'{q}:{cc}' for q, cc, _ in dupes[:8])})")
        print(f"  of those, DISAGREEING on the outcome: {disagree}"
              f"{'   <-- must be resolved by hand' if disagree else '  (all agree)'}")
    else:
        print("  duplicated pairs: 0")

    # ---------- verdict ----------
    print("\n" + "=" * 70)
    problems = []
    if dupes:
        problems.append(f"{len(dupes)} duplicated pair(s); dedup before analysis")
    if bad_status:
        problems.append(f"{bad_status} pair(s) with a non-result terminal status")
    if missing_in_started:
        problems.append(f"{len(missing_in_started)} pair(s) missing in a started arm")
    if problems:
        print("ATTENTION: " + "; ".join(problems))
        print("A resume sweep (re-run the same spec) recovers the missing pairs.")
    else:
        print("CLEAN: every started pair has a real outcome; nothing to retry.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
