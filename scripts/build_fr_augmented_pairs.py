"""Build the augmented France robustness set for EXP-6 (50% label-flip injection).

France is the worked example of a base-rate problem: its binary ODMI gold runs
~99% `yes` (121 `yes` / 1 `no`), so natural Researcher errors barely exist on the
minority class and Youden's J cannot take hold on the natural FR arm (the reason
EXP-6 was retargeted to Malta; docs/EXPERIMENTS_VERIFIER.md). The fix for a *robustness*
read on FR is injection: take correct FR binary candidates and flip half of their
labels (yes<->no), wrong by construction. The result is a class-balanced set,
half `should_pass` / half `should_fail`, i.e. an FR answer column that is half
`yes` and half `no`, on which J is defined and the ODMI-staleness confound is
removed (a flipped label is wrong regardless of whether the gold is one cycle old).

This is a robustness artefact, reported separately and never folded into the Malta
primary (EXP-6 design, section 3 / section 6).

Selection (deterministic, RNG seed 20260603; rules R2/R3 in
docs/EXPERIMENTS_PROTOCOL.md section 0):
  - The candidate pool is every distinct FR binary `should_pass` Researcher answer
    in phase2_researcher_runs (answer == ODMI gold under the _MATCH_STATUS_SQL
    yes-prefix / no rule), latest row per (question_id, answer) winning, so each
    record points at a real Researcher row with persisted evidence + snippets the
    EXP-6 harness can replay.
  - 60 candidates are drawn round-robin across Policy/Portal/Impact/Quality.
  - Exactly half (30) are flipped to `should_fail` (yes->no / no->yes); the other
    30 are kept as `should_pass`. The flip assignment is itself dimension-balanced:
    candidates are ordered (dimension, question_id) and every other one is flipped,
    so neither half is skewed to a dimension.

Output: data/questions/fr_augmented_eval_pairs.json, holding the seed, the rule,
achieved per-class / per-dimension / per-flip counts, and one record per candidate
(question_id, country_code, dimension, source_row_id, original_answer,
researcher_answer after any flip, flipped flag, gold_response, gold_label), so the
draw is reproducible and the EXP-6 apparatus can rebuild each ResearcherOutput from
source_row_id.

Usage:
    uv run python scripts/build_fr_augmented_pairs.py
"""
from __future__ import annotations

import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "data" / "odmi.db"
OUT = REPO / "data" / "questions" / "fr_augmented_eval_pairs.json"

SEED = 20260603
COUNTRY = "FR"
DIM_ORDER = ["Policy", "Portal", "Impact", "Quality"]
TARGET = 60          # total candidates
FLIP_FRACTION = 0.5  # half flipped to should_fail


def _evidence_blocked(row: dict) -> bool:
    """True if the Researcher row cited/fetched/read a deny-listed URL (D24).
    Excludes leaked legacy rows from the injection pool."""
    from agents.tools.blocked_domains import is_blocked
    urls = [row.get("source_url") or ""]
    try:
        urls += [u for u in json.loads(row.get("fetched_urls") or "[]")]
    except Exception:
        pass
    try:
        for s in json.loads(row.get("search_snippets") or "[]"):
            if isinstance(s, dict):
                urls.append(s.get("url") or "")
    except Exception:
        pass
    return any(u and is_blocked(u) for u in urls)


def _is_should_pass(answer: str, gold: str) -> bool:
    """Mirror _MATCH_STATUS_SQL / verifier_strategies._label for the pass case."""
    a = (answer or "").strip().lower()
    g = (gold or "").strip().lower()
    if not g or a in ("inconclusive", "not_applicable", ""):
        return False
    if a == g:
        return True
    if a == "yes" and g.startswith("yes"):
        return True
    if a == "no" and g == "no":
        return True
    return False


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    qmeta = {
        r["question_id"]: ((r["answer_shape"] or "binary"), r["dimension"])
        for r in conn.execute("select question_id,answer_shape,dimension from questions")
    }
    gold = {
        (r["question_id"], r["country_code"]): (r["response"] or "")
        for r in conn.execute("select question_id,country_code,response from ground_truth")
    }
    rows = [
        dict(r) for r in conn.execute(
            "select * from phase2_researcher_runs "
            "where answer is not null and country_code = ? order by id",
            (COUNTRY,),
        )
    ]
    conn.close()

    # Fairness guards: drop deny-listed (leaked) rows, then dedupe by
    # question_id keeping the latest clean row, so the injection pool is one
    # canonical clean candidate per FR question (no leaked answer-key evidence,
    # no double-dispatch contradictions).
    rows = [r for r in rows if not _evidence_blocked(r)]
    distinct = {}
    for r in rows:
        distinct[r["question_id"]] = r

    # Build the should_pass binary pool, grouped by dimension.
    by_dim: dict[str, list] = defaultdict(list)
    for qid, r in distinct.items():
        ans = (r["answer"] or "").strip().lower()
        shape, dim = qmeta.get(qid, ("binary", None))
        if shape != "binary":
            continue
        g = gold.get((qid, COUNTRY), "")
        if not _is_should_pass(ans, g):
            continue
        by_dim[dim].append({
            "question_id": qid, "country_code": COUNTRY, "dimension": dim,
            "source_row_id": r["id"], "original_answer": (r["answer"] or "").strip().lower(),
            "gold_response": g,
        })

    rng = random.Random(SEED)
    for d in DIM_ORDER:
        by_dim[d].sort(key=lambda x: x["question_id"])
        rng.shuffle(by_dim[d])

    # Round-robin draw across dimensions to TARGET.
    picked = []
    progressing = True
    while len(picked) < TARGET and progressing:
        progressing = False
        for d in DIM_ORDER:
            if by_dim[d]:
                picked.append(by_dim[d].pop())
                progressing = True
                if len(picked) >= TARGET:
                    break

    if len(picked) < TARGET:
        print(f"  ! only {len(picked)} should_pass FR candidates available "
              f"(< {TARGET}); building with what exists.")

    # Dimension-balanced flip assignment: order (dimension, qid), flip every other.
    picked.sort(key=lambda x: (DIM_ORDER.index(x["dimension"]) if x["dimension"] in DIM_ORDER else 9,
                               x["question_id"]))
    n_flip = round(len(picked) * FLIP_FRACTION)
    records = []
    flipped_count = 0
    for i, b in enumerate(picked):
        flip = (i % 2 == 0) and flipped_count < n_flip
        if flip:
            flipped_count += 1
        orig = b["original_answer"]
        researcher_answer = ("no" if orig == "yes" else "yes") if flip else orig
        records.append({
            "question_id": b["question_id"],
            "country_code": COUNTRY,
            "dimension": b["dimension"],
            "source_row_id": b["source_row_id"],
            "original_answer": orig,
            "researcher_answer": researcher_answer,
            "flipped": flip,
            "gold_response": b["gold_response"],
            "gold_label": "should_fail" if flip else "should_pass",
        })

    records.sort(key=lambda r: (0 if r["gold_label"] == "should_fail" else 1,
                                r["dimension"], r["question_id"]))

    by_label = Counter(r["gold_label"] for r in records)
    by_dim_count = Counter(r["dimension"] for r in records)
    by_answer = Counter(r["researcher_answer"] for r in records)
    flip_by_dim = Counter(r["dimension"] for r in records if r["flipped"])
    doc = {
        "description": "Augmented France robustness set for EXP-6: 50% label-flip "
                       "injection to balance the classes on a 99%-yes-gold country. "
                       "Robustness arm only, never folded into the Malta primary.",
        "seed": SEED,
        "country_code": COUNTRY,
        "answer_shape": "binary",
        "selection_rule": (
            "Distinct FR binary should_pass Researcher candidates (latest row per "
            "(question_id, answer)); 60 drawn round-robin across "
            "Policy/Portal/Impact/Quality with RNG seed "
            f"{SEED}; exactly half flipped (yes<->no) to should_fail, the flip set "
            "itself dimension-balanced (order by (dimension, qid), flip every other)."
        ),
        "counts": {
            "total": len(records),
            "by_label": dict(by_label),
            "by_answer_post_flip": dict(by_answer),
            "by_dimension": dict(by_dim_count),
            "flipped_by_dimension": dict(flip_by_dim),
        },
        "pairs": records,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {OUT}")
    print(f"  {len(records)} records  by_label={dict(by_label)}  "
          f"answers_post_flip={dict(by_answer)}")
    print(f"  by_dim={dict(by_dim_count)}  flipped_by_dim={dict(flip_by_dim)}")


if __name__ == "__main__":
    main()
