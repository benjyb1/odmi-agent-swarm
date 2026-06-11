"""Counterfactual replay: what does the Verifier gate buy us?

Replays three commit policies over the stored Researcher attempts and compares
them with the observed pipeline outcome, per country. No API calls; pure replay
of rows already in the DB, so the comparison is exact on the same pairs.

Policies:
  P0 observed   The pipeline as it ran (phase2_final).
  P1 solo       No Verifier, no retries: commit the attempt-0 Researcher answer
                iff it is definite and answer_confidence >= 0.65, else abstain.
                This is the world where the Verifier and the retry loop do not
                exist; later attempts are excluded because they only exist when
                a Verifier rejects.
  P1b solo-any  Sensitivity: commit the FIRST definite answer with
                confidence >= 0.65 across all stored attempts (the retry loop
                exists but the Verifier never blocks a commit).
  P2 oracle     Upper bound: a perfect Verifier that rejects exactly the
                gold-wrong candidates. Commit the first gold-correct definite
                candidate at any confidence; abstain if none was ever produced.
                This is the headroom available from candidates the Researcher
                already generated.

Metrics per policy and country: committed share, committed accuracy, false
positives on negative golds (binary 'no' gold), abstention rate. Read MT as
primary (base-rate balanced, R4); FR is majority-yes and flatters commit-happy
policies, which is exactly what the comparison is designed to expose.

Usage:
  uv run python evaluation/verifier_counterfactual.py --countries MT NO FR EE
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.stack_attribution import answers_match, is_definite, _wilson_str

DB_PATH = REPO_ROOT / "data" / "odmi.db"
FLOOR = 0.65


def replay(conn: sqlite3.Connection, countries: list[str]) -> dict:
    ph = ",".join("?" for _ in countries)
    qshape = {
        r["question_id"]: r["answer_shape"]
        for r in conn.execute("SELECT question_id, answer_shape FROM questions")
    }
    gold = {
        (r["question_id"], r["country_code"]): r["response"]
        for r in conn.execute(
            f"SELECT question_id, country_code, response FROM ground_truth "
            f"WHERE country_code IN ({ph}) AND response IS NOT NULL AND TRIM(response) <> ''",
            countries,
        )
    }
    attempts = defaultdict(list)
    for r in conn.execute(
        f"""SELECT pair_run_id, question_id, country_code, retry_count, answer,
                   answer_confidence
            FROM phase2_researcher_runs
            WHERE country_code IN ({ph}) AND experiment_id IS NULL
            ORDER BY pair_run_id, retry_count, id""",
        countries,
    ):
        attempts[r["pair_run_id"]].append(dict(r))
    finals = [
        dict(r)
        for r in conn.execute(
            f"""SELECT pair_run_id, question_id, country_code, final_answer,
                       terminal_status
                FROM phase2_final
                WHERE country_code IN ({ph}) AND experiment_id IS NULL""",
            countries,
        )
    ]

    def decide(policy: str, f: dict) -> str | None:
        """Return the committed answer under the policy, or None for abstain."""
        ats = attempts.get(f["pair_run_id"], [])
        shape = qshape.get(f["question_id"])
        g = gold[(f["question_id"], f["country_code"])]
        if policy == "observed":
            a = f["final_answer"]
            return a if is_definite(a) and f["terminal_status"] in (
                "accepted_by_verifier", "accepted_by_adjudicator"
            ) else None
        if policy == "solo":
            if not ats:
                return None
            a0 = ats[0]
            if is_definite(a0["answer"]) and (a0["answer_confidence"] or 0) >= FLOOR:
                return a0["answer"]
            return None
        if policy == "solo_any":
            for a in ats:
                if is_definite(a["answer"]) and (a["answer_confidence"] or 0) >= FLOOR:
                    return a["answer"]
            return None
        if policy == "oracle":
            for a in ats:
                if is_definite(a["answer"]) and answers_match(a["answer"], g, shape):
                    return a["answer"]
            return None
        raise ValueError(policy)

    out: dict = {}
    for cc in countries:
        rows = [f for f in finals if f["country_code"] == cc
                and (f["question_id"], cc) in gold]
        if not rows:
            continue
        out[cc] = {"n_pairs": len(rows)}
        for policy in ("observed", "solo", "solo_any", "oracle"):
            committed = correct = fp_neg = neg_committed = 0
            n_neg = 0
            for f in rows:
                g = gold[(f["question_id"], cc)]
                shape = qshape.get(f["question_id"])
                neg = shape == "binary" and g.strip().lower() == "no"
                n_neg += neg
                a = decide(policy, f)
                if a is None:
                    continue
                committed += 1
                ok = answers_match(a, g, shape)
                correct += ok
                if neg:
                    neg_committed += 1
                    fp_neg += not ok
            out[cc][policy] = {
                "committed": f"{committed}/{len(rows)}",
                "committed_accuracy": _wilson_str(correct, committed),
                "overall_accuracy_incl_abstain": _wilson_str(correct, len(rows)),
                "fp_on_negative_golds": _wilson_str(fp_neg, n_neg) if n_neg else "n/a",
                "abstention_rate": round(1 - committed / len(rows), 2),
            }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", default=["MT", "NO", "FR", "EE"])
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    report = replay(conn, args.countries)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text)


if __name__ == "__main__":
    main()
