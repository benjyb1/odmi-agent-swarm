"""Build the canonical Netherlands evaluation pair set for EXP-6 (secondary stratum).

Mirrors scripts/build_malta_eval_pairs.py exactly, only the country changes. The
EXP-6 pre-registration (docs/EXPERIMENTS_VERIFIER.md, stratum NAT-NL) names the
Netherlands as the secondary balanced country: Dutch is well-resourced and NL has
a real minority class (binary gold ~95 `yes` / ~26 `no`), so a false positive can
occur and Youden's J is defined on the secondary arm. No NL-specific count is laid
down in the protocol, so the rule follows Malta: take the whole minority class and
size-match the majority, which is the balanced "enough for the samples" choice and
keeps the secondary arm comparable to the primary.

Selection (deterministic, RNG seed 20260603; rules R2/R3/R4 in
docs/EXPERIMENTS_PROTOCOL.md section 0):
  - ALL NL binary questions with a `no` gold (the minority class; never sampled
    down).
  - A dimension-stratified, size-matched sample of `yes`-gold binary questions,
    drawn round-robin across Policy/Portal/Impact/Quality with the fixed seed.

Questions whose ODMI gold is not exactly `yes`/`no` are excluded: no usable binary
label. Output is data/questions/nl_eval_pairs.json, holding the seed, the rule, the
(question_id, country_code) list, and achieved per-class / per-dimension counts, so
the draw is reproducible and verifiably not post hoc.

Usage:
    uv run python scripts/build_nl_eval_pairs.py
"""
from __future__ import annotations

import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "odmi.db"
OUT = REPO / "data" / "questions" / "nl_eval_pairs.json"

SEED = 20260603
COUNTRY = "NL"
DIM_ORDER = ["Policy", "Portal", "Impact", "Quality"]


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """select gt.question_id qid, q.dimension dim, lower(trim(gt.response)) g
           from ground_truth gt join questions q on q.question_id = gt.question_id
           where q.answer_shape = 'binary' and gt.country_code = ?""",
        (COUNTRY,),
    ).fetchall()
    conn.close()

    no_set = []
    yes_by_dim: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["g"] == "no":
            no_set.append((r["qid"], r["dim"]))
        elif r["g"].startswith("yes"):
            yes_by_dim[r["dim"]].append((r["qid"], r["dim"]))

    no_set.sort()

    # Deterministic shuffle: iterate dimensions in a fixed order so the RNG is
    # consumed identically on every run regardless of dict ordering.
    rng = random.Random(SEED)
    for d in DIM_ORDER:
        yes_by_dim[d].sort()
        rng.shuffle(yes_by_dim[d])

    # Round-robin across dimensions, size-matched to the no-gold set.
    target = len(no_set)
    yes_pick = []
    progressing = True
    while len(yes_pick) < target and progressing:
        progressing = False
        for d in DIM_ORDER:
            if yes_by_dim[d]:
                yes_pick.append(yes_by_dim[d].pop())
                progressing = True
                if len(yes_pick) >= target:
                    break

    pairs = []
    for qid, dim in sorted(no_set):
        pairs.append({"question_id": qid, "country_code": COUNTRY,
                      "gold_class": "no", "dimension": dim})
    for qid, dim in sorted(yes_pick):
        pairs.append({"question_id": qid, "country_code": COUNTRY,
                      "gold_class": "yes", "dimension": dim})

    by_class = Counter(p["gold_class"] for p in pairs)
    by_dim = Counter(p["dimension"] for p in pairs)
    doc = {
        "description": "Canonical Netherlands evaluation pair set for EXP-6 "
                       "(secondary stratum; R2/R3/R4, mirrors the Malta rule).",
        "seed": SEED,
        "country_code": COUNTRY,
        "answer_shape": "binary",
        "selection_rule": (
            "All NL binary `no`-gold questions (minority class, not sampled), "
            "plus a dimension-stratified, size-matched sample of `yes`-gold binary "
            "questions drawn round-robin across Policy/Portal/Impact/Quality with "
            f"RNG seed {SEED}. Golds not exactly yes/no are excluded."
        ),
        "counts": {
            "total": len(pairs),
            "by_class": dict(by_class),
            "by_dimension": dict(by_dim),
        },
        "pairs": pairs,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {OUT}")
    print(f"  {len(pairs)} pairs  by_class={dict(by_class)}  by_dim={dict(by_dim)}")


if __name__ == "__main__":
    main()
