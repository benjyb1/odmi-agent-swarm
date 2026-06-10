"""EXP-11 S0.1: replay the v1 and v2 substring matchers over stored runs.

Two corpora:

  (A) Researcher path (the one that ships): every researcher
      evidence_quote against its OWN search_snippets. This is the gate
      production runs at, so the ship decision rests here.
  (B) Verifier path (informs the stage-1 refute gate): every verifier
      counter_evidence_quote (fails only) against the verifier's
      independent_evidence plus the researcher's snippets.

For each row we record v1 (joined-corpus contains) and v2 (per-snippet,
ellipsis-aware), join to ground truth, and print a flip matrix split by
whether the researcher's answer was correct. The ship rule (S0.1) reads
the researcher-path flips: v2 must not newly admit a quote absent from
every individual snippet, and every audited flip must be explainable.

Read-only. Writes evaluation/results/substring_v2_replay.jsonl.

  uv run python evaluation/replay_substring_v2.py
  uv run python evaluation/replay_substring_v2.py --audit 10
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from agents.tools import substring
from agents.tools.substring import contains_v2

from evaluation._replay_common import (
    is_correct,
    parse_independent_evidence,
    parse_search_snippets,
    ro_connect,
)

RESULTS = Path(__file__).resolve().parent / "results"


def _v1(snippets: list[str], quote: str) -> bool:
    return substring.contains("\n\n".join(s for s in snippets if s), quote)


def _rows_researcher(conn):
    sql = """
        SELECT r.id, r.question_id, r.country_code, r.answer,
               r.evidence_quote, r.search_snippets, gt.response AS gold
        FROM phase2_researcher_runs r
        LEFT JOIN ground_truth gt
          ON gt.question_id = r.question_id
         AND gt.country_code = r.country_code
        WHERE r.answer IS NOT NULL
          AND r.evidence_quote IS NOT NULL
          AND r.search_snippets IS NOT NULL
          AND r.search_snippets <> '[]'
    """
    for row in conn.execute(sql):
        snippets = parse_search_snippets(row["search_snippets"])
        if not snippets:
            continue
        quote = row["evidence_quote"]
        v1 = _v1(snippets, quote)
        res = contains_v2(snippets, quote)
        corr = (
            is_correct(row["question_id"], row["answer"], row["gold"])
            if row["gold"] else None
        )
        yield {
            "corpus": "researcher",
            "id": row["id"],
            "question_id": row["question_id"],
            "country_code": row["country_code"],
            "answer": row["answer"],
            "correct": corr,
            "n_snippets": len(snippets),
            "v1": v1,
            "v2": res.matched,
            "v2_reason": res.reason,
            "v2_snippet_index": res.snippet_index,
            "n_fragments": res.n_fragments,
            "quote": quote,
        }


def _rows_verifier(conn):
    sql = """
        SELECT v.id, v.question_id, v.country_code, v.verdict,
               v.counter_evidence_quote, v.independent_evidence,
               r.answer AS r_answer, r.search_snippets, gt.response AS gold
        FROM phase2_verifier_runs v
        JOIN phase2_researcher_runs r ON r.id = v.researcher_run_id
        LEFT JOIN ground_truth gt
          ON gt.question_id = v.question_id
         AND gt.country_code = v.country_code
        WHERE v.verdict = 'fail'
          AND v.counter_evidence_quote IS NOT NULL
          AND TRIM(v.counter_evidence_quote) <> ''
    """
    for row in conn.execute(sql):
        snippets = (
            parse_independent_evidence(row["independent_evidence"])
            + parse_search_snippets(row["search_snippets"])
        )
        if not snippets:
            continue
        quote = row["counter_evidence_quote"]
        v1 = _v1(snippets, quote)
        res = contains_v2(snippets, quote)
        corr = (
            is_correct(row["question_id"], row["r_answer"], row["gold"])
            if row["gold"] else None
        )
        yield {
            "corpus": "verifier",
            "id": row["id"],
            "question_id": row["question_id"],
            "country_code": row["country_code"],
            "answer": row["r_answer"],
            "correct": corr,
            "n_snippets": len(snippets),
            "v1": v1,
            "v2": res.matched,
            "v2_reason": res.reason,
            "v2_snippet_index": res.snippet_index,
            "n_fragments": res.n_fragments,
            "quote": quote,
        }


def _flip_matrix(records, corpus, only_dev=False):
    dev = {"MT", "NO"}
    rows = [r for r in records if r["corpus"] == corpus]
    if only_dev:
        rows = [r for r in rows if r["country_code"] in dev]
    cells = Counter()
    for r in rows:
        key = ("v1" if r["v1"] else "x1", "v2" if r["v2"] else "x2", r["correct"])
        cells[key] += 1

    def c(v1, v2, corr):
        return cells[(v1, v2, corr)]

    scope = "DEV (MT+NO)" if only_dev else "ALL countries"
    print(f"\n=== {corpus} path, {scope} (n={len(rows)}) ===")
    print("                         correct=True  correct=False  correct=None(no gold)")
    for label, v1k, v2k in [
        ("v1 PASS / v2 PASS (agree)", "v1", "v2"),
        ("v1 PASS / v2 FAIL (newly rejected)", "v1", "x2"),
        ("v1 FAIL / v2 PASS (newly admitted)", "x1", "v2"),
        ("v1 FAIL / v2 FAIL (agree)", "x1", "x2"),
    ]:
        print(f"  {label:36s} {c(v1k,v2k,True):>10d}  {c(v1k,v2k,False):>12d}  "
              f"{c(v1k,v2k,None):>10d}")

    # Reason breakdown for v2 misses where v1 passed (the splices/short
    # fragments v2 newly catches) and the dangerous v1-fail/v2-pass cell.
    newly_rej = [r for r in rows if r["v1"] and not r["v2"]]
    newly_adm = [r for r in rows if not r["v1"] and r["v2"]]
    if newly_rej:
        print(f"  newly-rejected reasons: {dict(Counter(r['v2_reason'] for r in newly_rej))}")
    print(f"  newly-admitted count (must be ~0 and explainable): {len(newly_adm)}")
    return rows


def _audit_dump(records, corpus, n):
    rows = [r for r in records if r["corpus"] == corpus]
    newly_rej = [r for r in rows if r["v1"] and not r["v2"]][:n]
    newly_adm = [r for r in rows if not r["v1"] and r["v2"]][:n]
    print(f"\n----- AUDIT: {corpus} newly-REJECTED (v1 pass, v2 fail), up to {n} -----")
    for r in newly_rej:
        print(f"  [{r['country_code']} {r['question_id']} correct={r['correct']} "
              f"reason={r['v2_reason']} nfrag={r['n_fragments']}] "
              f"quote={r['quote'][:140]!r}")
    print(f"\n----- AUDIT: {corpus} newly-ADMITTED (v1 fail, v2 pass), up to {n} -----")
    for r in newly_adm:
        print(f"  [{r['country_code']} {r['question_id']} correct={r['correct']} "
              f"snip_idx={r['v2_snippet_index']}] quote={r['quote'][:140]!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=10,
                    help="dump this many flip examples per direction")
    args = ap.parse_args()

    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / "substring_v2_replay.jsonl"

    records = []
    with ro_connect() as conn:
        records.extend(_rows_researcher(conn))
        records.extend(_rows_verifier(conn))

    with out_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    print(f"Replayed {len(records)} rows -> {out_path}")
    for corpus in ("researcher", "verifier"):
        _flip_matrix(records, corpus, only_dev=False)
        _flip_matrix(records, corpus, only_dev=True)
    for corpus in ("researcher", "verifier"):
        _audit_dump(records, corpus, args.audit)


if __name__ == "__main__":
    main()
