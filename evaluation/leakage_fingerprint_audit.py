#!/usr/bin/env python3
"""FM-14 content-level leakage audit: fingerprint ODMI answer text in evidence.

The D24 deny-list stops the swarm fetching ODMI's own publications by domain.
It cannot stop a third party republishing the answer key on an allowed domain
(FM-14: a consultancy PDF, a news write-up, a national report quoting the
ODMI country factsheet). This audit attacks that gap at the content level:

For every finalised committed pair, compare the committed evidence quote
against the ODMI ground-truth `explanation` text for the same (question,
country). A long shared word n-gram means the swarm's evidence and
Capgemini's evidence contain the same passage. That is not automatically
leakage: both may quote the same primary source (a portal page, a statute),
which is legitimate corroboration. So the audit surfaces candidates with
their overlap and source URL for human review; it does not auto-classify.

Usage:
    uv run python evaluation/leakage_fingerprint_audit.py
    uv run python evaluation/leakage_fingerprint_audit.py --experiment-id exp28_arch_ablation
    uv run python evaluation/leakage_fingerprint_audit.py --min-ngram 10 --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "odmi.db"

# Committed statuses: rows whose evidence quote backs a real answer.
COMMITTED = (
    "accepted_by_verifier",
    "accepted_by_adjudicator",
    "accepted_researcher_only",
)


def _normalise(text: str) -> list[str]:
    """Lowercase word tokens, punctuation stripped, for n-gram comparison."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def longest_shared_ngram(a: str, b: str) -> tuple[int, str]:
    """Length (in words) and text of the longest shared word n-gram."""
    ta, tb = _normalise(a), _normalise(b)
    if not ta or not tb:
        return 0, ""
    # Classic DP over token sequences; quotes are <=600 chars so this is cheap.
    best_len, best_end = 0, 0
    prev = [0] * (len(tb) + 1)
    for i in range(1, len(ta) + 1):
        cur = [0] * (len(tb) + 1)
        for j in range(1, len(tb) + 1):
            if ta[i - 1] == tb[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best_len:
                    best_len, best_end = cur[j], i
        prev = cur
    return best_len, " ".join(ta[best_end - best_len:best_end])


def audit(db_path: Path, experiment_id: str | None, min_ngram: int):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    where = "f.terminal_status IN (%s)" % ",".join("?" for _ in COMMITTED)
    params: list = list(COMMITTED)
    if experiment_id:
        where += " AND f.experiment_id = ?"
        params.append(experiment_id)
    else:
        where += " AND f.experiment_id IS NULL"
    rows = conn.execute(
        f"""
        SELECT f.question_id, f.country_code, f.final_answer,
               f.final_evidence_quote, f.final_source_url, f.experiment_id,
               gt.explanation, gt.decision, gt.response
        FROM phase2_final f
        JOIN ground_truth gt
          ON gt.question_id = f.question_id
         AND gt.country_code = f.country_code
        WHERE {where}
          AND f.final_evidence_quote IS NOT NULL
          AND LENGTH(TRIM(f.final_evidence_quote)) >= 20
          AND gt.explanation IS NOT NULL
          AND LENGTH(TRIM(gt.explanation)) >= 40
        """,
        params,
    ).fetchall()

    hits = []
    for r in rows:
        n, shared = longest_shared_ngram(
            r["final_evidence_quote"], r["explanation"]
        )
        if n >= min_ngram:
            hits.append({
                "question_id": r["question_id"],
                "country_code": r["country_code"],
                "experiment_id": r["experiment_id"] or "",
                "decision": r["decision"],
                "swarm_answer": r["final_answer"],
                "gold_response": r["response"],
                "shared_ngram_words": n,
                "shared_text": shared[:300],
                "source_url": r["final_source_url"],
            })
    return len(rows), hits


def main() -> int:
    ap = argparse.ArgumentParser(description="FM-14 content-level leakage audit")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--experiment-id", default=None,
                    help="Audit one experiment's rows; default audits "
                         "main-results rows (experiment_id IS NULL).")
    ap.add_argument("--min-ngram", type=int, default=8,
                    help="Minimum shared word n-gram length to flag "
                         "(default 8 words).")
    ap.add_argument("--csv", type=Path, default=None,
                    help="Write flagged candidates to this CSV.")
    args = ap.parse_args()

    scanned, hits = audit(args.db, args.experiment_id, args.min_ngram)
    scope = args.experiment_id or "main results"
    print(f"scanned {scanned} committed pairs ({scope}); "
          f"{len(hits)} candidates at >= {args.min_ngram} shared words")
    for h in sorted(hits, key=lambda x: -x["shared_ngram_words"]):
        print(f"  {h['question_id']}/{h['country_code']} "
              f"[{h['decision']}] {h['shared_ngram_words']}w "
              f"{h['source_url']}\n    \"{h['shared_text'][:120]}\"")
    if args.csv and hits:
        with args.csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(hits[0].keys()))
            w.writeheader()
            w.writerows(hits)
        print(f"wrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
