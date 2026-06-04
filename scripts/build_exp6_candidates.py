"""EXP-6a: freeze the verifier-strategy candidate dataset into `exp6_candidates`.

This is the dataset EXP-6b (the four-arm verifier comparison) consumes. It is a
frozen, pinned snapshot, so a concurrent dispatch rewriting `phase2_researcher_runs`
can never shift the set under the judge run (the snapshot-pinning fix; no live
"latest id wins" at judge time). Each row pins the source
`phase2_researcher_runs.id` it was taken from.

What goes in (medium target, ~120 candidates):
  - Natural MT (primary) and NL (secondary): the latest committed Researcher
    answer for every pair in the canonical worklists
    (data/questions/{malta,nl}_eval_pairs.json), labelled should_pass /
    should_fail against ODMI gold. Latest id wins, so a finished v2 re-run is the
    one frozen. Abstentions (inconclusive / not_applicable) and no-gold pairs are
    EXCLUDED: the classifier question is only defined on a committed answer with a
    reference.
  - Injected flips (robustness): correct FR/EE binary candidates with the label
    flipped yes<->no, wrong by construction. They need no new research run, they
    reuse existing correct runs. A separate stratum, role `robustness`, NEVER
    folded into the primary J. Seeded draw, target set by --inj-target (default 35).

Idempotent: clears and rebuilds rows for EXPERIMENT_ID. Deterministic (seed 20260603).

Run EXP-6a in order:
  1. uv run python scripts/build_nl_eval_pairs.py          # once, the NL worklist
  2. dispatch the swarm over data/questions/nl_eval_pairs.json   # the long bit
  3. uv run python scripts/build_exp6_candidates.py        # freeze (this script)

Re-run step 3 whenever the underlying runs change; it is safe to repeat.

Usage:
    uv run python scripts/build_exp6_candidates.py
    uv run python scripts/build_exp6_candidates.py --inj-target 35
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "odmi.db"
QDIR = REPO / "data" / "questions"

SEED = 20260603
EXPERIMENT_ID = "verifier_strategy_disc_v1"
DIM_ORDER = ["Policy", "Portal", "Impact", "Quality"]

# Roles, per the R4 base-rate rule (mirrors evaluation/verifier_strategies.py).
PRIMARY_WORKLIST = ("MT", QDIR / "malta_eval_pairs.json")
SECONDARY_WORKLIST = ("NL", QDIR / "nl_eval_pairs.json")
INJECTION_COUNTRIES = ["FR", "EE"]


DDL = """
CREATE TABLE IF NOT EXISTS exp6_candidates (
    cand_id           TEXT NOT NULL,
    experiment_id     TEXT NOT NULL,
    stratum           TEXT NOT NULL,          -- NAT-fail | NAT-pass | INJ-fail
    role              TEXT NOT NULL,          -- primary | secondary | robustness
    gold_label        TEXT NOT NULL,          -- should_pass | should_fail
    question_id       TEXT NOT NULL,
    country_code      TEXT NOT NULL,
    dimension         TEXT,
    answer_shape      TEXT,
    allowed_answers   TEXT,                   -- JSON list
    researcher_answer TEXT NOT NULL,          -- possibly flipped (INJ)
    gold_response     TEXT NOT NULL,
    source_row_id     INTEGER NOT NULL,       -- pinned phase2_researcher_runs.id
    injected          INTEGER NOT NULL DEFAULT 0,
    seed              INTEGER,
    frozen_at         TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (experiment_id, cand_id)
);
"""


def _label(answer: str, gold: str) -> str:
    """should_pass / should_fail / abstain / no_gt. Mirrors
    evaluation/verifier_strategies.py._label and _MATCH_STATUS_SQL: exact match,
    the yes-prefix rule, the plain `no` rule; anything else (incl. an adjacent
    band) is a fail."""
    if gold is None or gold.strip() == "":
        return "no_gt"
    a = (answer or "").strip().lower()
    g = gold.strip().lower()
    if a in ("inconclusive", "not_applicable", ""):
        return "abstain"
    if a == g:
        return "should_pass"
    if a == "yes" and g.startswith("yes"):
        return "should_pass"
    if a == "no" and g == "no":
        return "should_pass"
    return "should_fail"


def _load_meta(conn):
    """question_id -> (dimension, answer_shape, allowed_answers)."""
    meta = {}
    for r in conn.execute(
        "select question_id, dimension, answer_shape, allowed_answers from questions"
    ):
        meta[r["question_id"]] = {
            "dim": r["dimension"],
            "shape": r["answer_shape"] or "binary",
            "allowed": json.loads(r["allowed_answers"]) if r["allowed_answers"] else ["yes", "no"],
        }
    return meta


def _load_gold(conn):
    gold = {}
    for r in conn.execute("select question_id, country_code, response from ground_truth"):
        gold[(r["question_id"], r["country_code"])] = (r["response"] or "")
    return gold


def _latest_runs(conn, countries):
    """Latest committed Researcher row per (question_id, country_code) for the
    given countries: max id wins, so a finished v2 re-run is the one returned."""
    placeholders = ",".join("?" for _ in countries)
    rows = [dict(r) for r in conn.execute(
        f"""select * from phase2_researcher_runs
            where country_code in ({placeholders}) and answer is not null
            order by id""",
        countries,
    )]
    latest = {}
    for r in rows:                       # ordered by id asc, so last write wins
        latest[(r["question_id"], r["country_code"])] = r
    return latest


def _worklist_pairs(path):
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    return {(p["question_id"], p["country_code"]) for p in doc["pairs"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inj-target", type=int, default=35,
                    help="number of injected label-flips to mint (robustness arm)")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)

    meta = _load_meta(conn)
    gold = _load_gold(conn)
    rng = random.Random(SEED)

    cands = []          # list of dict rows for exp6_candidates
    excluded = Counter()
    skipped_examples = defaultdict(list)

    # ---- Natural strata: MT primary, NL secondary ----
    for role, (cc, path) in (("primary", PRIMARY_WORKLIST),
                             ("secondary", SECONDARY_WORKLIST)):
        worklist = _worklist_pairs(path)
        if worklist is None:
            print(f"  [skip] {role} {cc}: no worklist at {path.name} (not built yet)")
            continue
        latest = _latest_runs(conn, [cc])
        for (qid, c) in sorted(worklist):
            r = latest.get((qid, c))
            if r is None:
                excluded[f"{cc}:no_run"] += 1
                skipped_examples[f"{cc}:no_run"].append(qid)
                continue
            g = gold.get((qid, c), "")
            lab = _label(r["answer"], g)
            if lab in ("abstain", "no_gt"):
                excluded[f"{cc}:{lab}"] += 1
                skipped_examples[f"{cc}:{lab}"].append(qid)
                continue
            m = meta.get(qid, {"dim": None, "shape": "binary", "allowed": ["yes", "no"]})
            cands.append(dict(
                cand_id=f"{'NATF' if lab == 'should_fail' else 'NATP'}::{qid}::{c}",
                stratum="NAT-fail" if lab == "should_fail" else "NAT-pass",
                role=role, gold_label=lab, question_id=qid, country_code=c,
                dimension=m["dim"], answer_shape=m["shape"],
                allowed_answers=json.dumps(m["allowed"]),
                researcher_answer=r["answer"], gold_response=g,
                source_row_id=r["id"], injected=0,
            ))

    # ---- Injected flips (robustness): flip correct FR/EE binary candidates ----
    inj_latest = _latest_runs(conn, INJECTION_COUNTRIES)
    inj_pool = []
    for (qid, c), r in inj_latest.items():
        m = meta.get(qid)
        if not m or m["shape"] != "binary":
            continue
        a = (r["answer"] or "").strip().lower()
        if a not in ("yes", "no"):
            continue
        g = gold.get((qid, c), "")
        if _label(r["answer"], g) != "should_pass":   # only flip a correct answer
            continue
        inj_pool.append((qid, c, r, g, m))
    inj_pool.sort(key=lambda x: (x[1], x[0]))          # deterministic order
    rng.shuffle(inj_pool)
    inj_take = inj_pool[: args.inj_target]
    for (qid, c, r, g, m) in inj_take:
        flipped = "no" if (r["answer"] or "").strip().lower() == "yes" else "yes"
        cands.append(dict(
            cand_id=f"INJF::{qid}::{c}",
            stratum="INJ-fail", role="robustness", gold_label="should_fail",
            question_id=qid, country_code=c, dimension=m["dim"],
            answer_shape=m["shape"], allowed_answers=json.dumps(m["allowed"]),
            researcher_answer=flipped, gold_response=g,
            source_row_id=r["id"], injected=1,
        ))

    # ---- Write (idempotent for this experiment_id) ----
    conn.execute("delete from exp6_candidates where experiment_id = ?", (EXPERIMENT_ID,))
    conn.executemany(
        """insert into exp6_candidates
           (cand_id, experiment_id, stratum, role, gold_label, question_id,
            country_code, dimension, answer_shape, allowed_answers,
            researcher_answer, gold_response, source_row_id, injected, seed)
           values (:cand_id, :experiment_id, :stratum, :role, :gold_label,
            :question_id, :country_code, :dimension, :answer_shape,
            :allowed_answers, :researcher_answer, :gold_response, :source_row_id,
            :injected, :seed)""",
        [dict(c, experiment_id=EXPERIMENT_ID, seed=SEED) for c in cands],
    )
    conn.execute(
        """insert into experiments (experiment_id, name, description, conditions)
           values (?, ?, ?, ?)
           on conflict(experiment_id) do update set description = excluded.description""",
        (EXPERIMENT_ID, "Verifier strategy discrimination",
         "EXP-6: four-arm verifier signal detection over a frozen candidate set "
         "(MT primary, NL secondary, FR/EE injected robustness).",
         json.dumps(STRATEGY_CONDITIONS)),
    )
    conn.commit()

    # ---- Report ----
    by_role = Counter((c["role"], c["gold_label"]) for c in cands)
    by_stratum = Counter(c["stratum"] for c in cands)
    by_country = Counter(c["country_code"] for c in cands)
    nat_fail = sum(1 for c in cands if c["stratum"] == "NAT-fail")
    nat_pass = sum(1 for c in cands if c["stratum"] == "NAT-pass")
    inj = sum(1 for c in cands if c["stratum"] == "INJ-fail")
    print(f"\nfroze {len(cands)} candidates into exp6_candidates ({EXPERIMENT_ID})")
    print(f"  natural: {nat_fail} should_fail + {nat_pass} should_pass")
    print(f"  injected: {inj} (target {args.inj_target})")
    print(f"  by stratum: {dict(by_stratum)}")
    print(f"  by country: {dict(by_country)}")
    print(f"  by (role, label): {dict(by_role)}")
    if excluded:
        print(f"  excluded (abstentions / no gold / no run): {dict(excluded)}")
    if inj < args.inj_target:
        print(f"  [warn] injected pool short: {inj} < {args.inj_target}; need more "
              f"FR/EE correct binary runs.")
    conn.close()


STRATEGY_CONDITIONS = [
    {"condition_label": s} for s in
    ["verifier-disprove", "verifier-negation", "verifier-steelman", "verifier-blind"]
]


if __name__ == "__main__":
    main()
