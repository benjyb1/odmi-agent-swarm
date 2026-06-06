"""Provider-clean dispatch of the EXP-6 candidate pools (2026-06-06 design).

Runs the Researcher pass for the two EXP-6 arms on a single pinned provider
(Serper-DIY, no fallback) with cold cache, so the search provider is held
constant within and across the sets (the constant-provider rule). The old
auto-provider MT/NL/FR phase2_* rows were purged first (DB backed up to
data/odmi.db.bak-pre-exp6-purge); Malta is dropped entirely.

Arms (shared question selection data/questions/exp6_question_set.json, 71 binary
non-self-report questions, 19 each Policy/Portal/Impact + 14 Quality):
  - NL natural   : the 71 questions on the Netherlands (Dutch, high-resource).
  - FR injected  : the 71 questions on France; correct binary answers are flipped
                   by the harness at candidate-build time (INJ_TARGET=71).

Total: 142 pairs (71 NL + 71 FR).

Usage:
    uv run python scripts/dispatch_exp6_clean.py
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.dispatch_subtrios import dispatch

REPO = Path(__file__).resolve().parent.parent
QSET = REPO / "data" / "questions" / "exp6_question_set.json"


def main() -> None:
    qids = [q["question_id"] for q in json.loads(QSET.read_text())["questions"]]
    pairs = [(q, "NL") for q in qids] + [(q, "FR") for q in qids]
    print(f"dispatching {len(pairs)} pairs ({len(qids)} NL + {len(qids)} FR) "
          f"on pinned DIY, cold cache")

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
