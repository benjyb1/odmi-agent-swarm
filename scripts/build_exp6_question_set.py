"""Build the EXP-6 question selection (2026-06-06 design).

A single shared question list, used for both the NL natural arm and the FR
injected arm. Selection rule (R3, seeded, fixed in advance):

  - Binary questions only (the verifier is a binary classifier; injection flips
    a yes/no answer).
  - Self-report questions excluded (the narrow keyword rule in
    scripts/build_answerability.py).
  - Per dimension: ALL non-self-report binary Quality questions (14, the natural
    ceiling), plus a seeded sample of 19 each from Policy / Portal / Impact.
  - RNG seed 20260603; selected IDs written out so the draw is reproducible and
    not post hoc.

Output: data/questions/exp6_question_set.json

Usage:
    uv run python scripts/build_exp6_question_set.py
"""
from __future__ import annotations

import importlib.util
import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "odmi.db"
OUT = REPO / "data" / "questions" / "exp6_question_set.json"

SEED = 20260603
PER_DIM = {"Policy": 19, "Portal": 19, "Impact": 19, "Quality": 14}

# Reuse the canonical self-report regex.
_spec = importlib.util.spec_from_file_location(
    "ba", str(REPO / "scripts" / "build_answerability.py"))
_ba = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ba)


def _is_self_report(row: sqlite3.Row) -> bool:
    text = " ".join(str(row[k] or "") for k in
                    ("question_text", "indicator", "response_scoring"))
    return bool(_ba._SELF_RE.search(text))


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select question_id, dimension, answer_shape, question_text, "
        "indicator, response_scoring from questions where answer_shape='binary'"
    ).fetchall()
    conn.close()

    pool: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if _is_self_report(r):
            continue
        pool[r["dimension"]].append(r["question_id"])

    rng = random.Random(SEED)
    selected: list[dict] = []
    achieved = {}
    for dim, target in PER_DIM.items():
        ids = sorted(pool.get(dim, []))
        rng.shuffle(ids)
        pick = sorted(ids[:target])
        achieved[dim] = len(pick)
        for qid in pick:
            selected.append({"question_id": qid, "dimension": dim})

    by_dim = Counter(s["dimension"] for s in selected)
    doc = {
        "description": "EXP-6 shared question selection (NL natural arm + FR "
                       "injected arm). Binary, no self-report, dimension-"
                       "stratified, seeded.",
        "seed": SEED,
        "answer_shape": "binary",
        "selection_rule": (
            "All non-self-report binary Quality questions (14, the catalogue "
            "ceiling), plus a seeded sample of 19 each from non-self-report "
            "binary Policy/Portal/Impact, RNG seed 20260603. Self-report "
            "questions excluded per scripts/build_answerability.py."
        ),
        "target_per_dimension": PER_DIM,
        "achieved_per_dimension": dict(by_dim),
        "total": len(selected),
        "questions": selected,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {OUT}")
    print(f"  total={len(selected)}  by_dim={dict(by_dim)}")
    print(f"  pool sizes (non-SR binary): "
          f"{ {d: len(pool.get(d, [])) for d in PER_DIM} }")


if __name__ == "__main__":
    main()
