"""EXP-11 S0.3: shadow-replay the absence receipts check.

P3 lock 1 would require an absence answer ('no', bottom band) to show,
in the Researcher's logged search_queries_used, at least RECEIPTS_N
distinct queries that name the search target (the country or its
portal/government domain). An absence answer backed by too few targeted
queries is treated as under-searched and retried rather than committed.

This replay does not gate anything. It measures, over every stored
absence answer, what fraction would be flagged as under-searched at N
in {2, 3, 4}, split by whether the answer was correct, so we can pick
the largest N whose flag rate on CORRECT absence answers stays at or
under 10% (the retry burden we are willing to add to catch the
unsupported negatives).

Subject-term matching (naming the question's topic) is deferred: it
needs per-question keyword extraction that risks being arbitrary. The
deterministic core here is country/domain naming, reported as a lower
bound on how targeted the search was.

Read-only. Writes evaluation/results/absence_receipts_replay.jsonl.

  uv run python evaluation/replay_absence_receipts.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from evaluation._replay_common import (
    is_absence_class,
    is_correct,
    ro_connect,
)

RESULTS = Path(__file__).resolve().parent / "results"
NS = [2, 3, 4]
COUNTRIES = ["MT", "NO"]

# Country / portal / government-domain tokens. No countries table
# exists, so the dev strata are hardcoded; extend before using this on
# a new country. Tokens are matched case-insensitively as substrings.
TOKENS = {
    "MT": ["malta", "maltese", "gov.mt", "data.gov.mt"],
    "NO": ["norway", "norge", "norwegian", "gov.no", "norge.no", "digdir"],
}


def _names_target(query: str, tokens) -> bool:
    q = query.lower()
    return any(t in q for t in tokens)


def _targeted_count(queries, tokens) -> int:
    seen = set()
    for q in queries:
        if isinstance(q, str) and _names_target(q, tokens):
            seen.add(q.strip().lower())
    return len(seen)


def _analyse_country(conn, country):
    tokens = TOKENS[country]
    sql = """
        SELECT r.question_id, r.answer, r.search_queries_used,
               gt.response AS gold
        FROM phase2_researcher_runs r
        JOIN ground_truth gt
          ON gt.question_id = r.question_id AND gt.country_code = r.country_code
        WHERE r.country_code = ?
          AND r.answer IS NOT NULL
          AND gt.response IS NOT NULL AND TRIM(gt.response) <> ''
    """
    records = []
    for row in conn.execute(sql, (country,)):
        if not is_absence_class(row["question_id"], row["answer"]):
            continue
        try:
            queries = json.loads(row["search_queries_used"] or "[]")
        except (json.JSONDecodeError, TypeError):
            queries = []
        tc = _targeted_count(queries, tokens)
        records.append(dict(
            country=country, question_id=row["question_id"],
            answer=row["answer"],
            correct=is_correct(row["question_id"], row["answer"], row["gold"]),
            n_queries=len(queries), targeted=tc,
        ))
    return records


def main():
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "absence_receipts_replay.jsonl"
    all_records = []
    with ro_connect() as conn:
        for country in COUNTRIES:
            all_records.extend(_analyse_country(conn, country))

    with out.open("w") as f:
        for r in all_records:
            f.write(json.dumps(r) + "\n")

    print(f"Replayed {len(all_records)} absence answers -> {out}")
    for country in COUNTRIES:
        recs = [r for r in all_records if r["country"] == country]
        corr = [r for r in recs if r["correct"]]
        wrong = [r for r in recs if not r["correct"]]
        print(f"\n=== {country}: {len(recs)} absence answers "
              f"({len(corr)} correct, {len(wrong)} wrong) ===")
        print(f"  targeted-query count distribution: "
              f"{dict(sorted(Counter(r['targeted'] for r in recs).items()))}")
        print(f"  {'N':>2} {'flag_rate_correct':>18} {'flag_rate_wrong':>16}")
        for N in NS:
            fc = sum(1 for r in corr if r["targeted"] < N)
            fw = sum(1 for r in wrong if r["targeted"] < N)
            rc = fc / len(corr) if corr else 0.0
            rw = fw / len(wrong) if wrong else 0.0
            print(f"  {N:>2} {rc:>17.3f} {rw:>16.3f}")

    # Decision: largest N whose flag rate on CORRECT absence answers
    # (pooled MT+NO) is <= 0.10.
    corr_all = [r for r in all_records if r["correct"]]
    print("\n=== DECISION (largest N with flag-rate on CORRECT <= 0.10, pooled) ===")
    chosen = None
    for N in NS:
        fc = sum(1 for r in corr_all if r["targeted"] < N)
        rc = fc / len(corr_all) if corr_all else 0.0
        wrong_all = [r for r in all_records if not r["correct"]]
        fw = sum(1 for r in wrong_all if r["targeted"] < N)
        rw = fw / len(wrong_all) if wrong_all else 0.0
        ok = rc <= 0.10
        print(f"  N={N}: flag_rate_correct={rc:.3f} flag_rate_wrong={rw:.3f} ok={ok}")
        if ok:
            chosen = N
    print(f"  -> RECEIPTS_N = {chosen if chosen is not None else 'none clears 10%; lock 1 not viable as specified'}")


if __name__ == "__main__":
    main()
