"""Provider-clean dispatch of the EXP-6 candidate pools (2026-06-06 design).

Runs the Researcher pass for the two EXP-6 arms on a single pinned provider
(Serper-DIY, no fallback) with cold cache, so the search provider is held
constant within and across the sets (the constant-provider rule). The old
auto-provider MT/NL/FR phase2_* rows were purged first (DB backed up to
data/odmi.db.bak-pre-exp6-purge); Malta is dropped entirely.

Arms (shared question selection data/questions/exp6_question_set.json, 71 binary
non-self-report questions, 19 each Policy/Portal/Impact + 14 Quality):
  - NL natural:   the 71 questions on the Netherlands (Dutch, high-resource).
  - FR injected:  the 71 questions on France; correct binary answers are flipped
                   by the harness at candidate-build time (INJ_TARGET=71).

Total: 142 pairs (71 NL + 71 FR).

Usage:
    uv run python scripts/dispatch_exp6_clean.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.dispatch_subtrios import dispatch

REPO = Path(__file__).resolve().parent.parent
QSET = REPO / "data" / "questions" / "exp6_question_set.json"
DB = REPO / "data" / "odmi.db"


def _already_finalised() -> set[tuple[str, str]]:
    """(question_id, country_code) pairs that already have a phase2_final row.

    The dispatcher has no skip-if-finalised guard and the resume path only
    rescues pairs that died before finalising, so re-running a finalised pair
    would duplicate it and waste credits. We exclude them here to make the
    launcher idempotent: re-run as often as you like, only the unfinished
    pairs (and orphaned/interrupted ones, which the coordinator resumes) run.
    """
    conn = sqlite3.connect(DB)
    done = {(q, c) for q, c in conn.execute(
        "select distinct question_id, country_code from phase2_final "
        "where country_code in ('NL','FR')")}
    conn.close()
    return done


def main() -> None:
    qids = [q["question_id"] for q in json.loads(QSET.read_text())["questions"]]
    all_pairs = [(q, "NL") for q in qids] + [(q, "FR") for q in qids]

    done = _already_finalised()
    pairs = [p for p in all_pairs if p not in done]
    print(f"{len(done)} pairs already finalised (skipped); "
          f"dispatching {len(pairs)} of {len(all_pairs)} remaining "
          f"on pinned DIY, cold cache")
    if not pairs:
        print("nothing to dispatch — all pairs finalised.")
        return

    result = dispatch(
        pairs=pairs,
        provider="diy",
        no_cache=True,
        condition_label="exp6_clean_diy",
        batch_id="exp6_clean_diy_nlfr",
        parallel_limit=6,
        max_retries=3,
        allow_large=False,  # 142 < 500 guard
    )
    print("=== DISPATCH COMPLETE ===")
    print("batch_id:", result.batch_id)
    print("jobs:", len(result.jobs))
    print("rate_limited:", getattr(result, "rate_limited", None))
    for m in (result.messages or []):
        print("  ", m)


if __name__ == "__main__":
    main()
