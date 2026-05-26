"""Generate the snippet-quality fixture from accepted swarm runs.

For each (question, country) pair the swarm has finalised on, the
Verifier accepted a specific evidence_quote on a specific source_url.
That tuple is a free, validated training-set datapoint: "on this page,
this passage is a defensible answer to this question."

The DIY snippet picker is asserted against these -- if our picker finds
a chunk that overlaps with the historically-accepted quote, it has
methodologically the same quality as the Verifier-accepted output.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "odmi.db"
DEFAULT_OUTPUT = REPO_ROOT / "tests" / "fixtures" / "snippet_quality.jsonl"


_QUERY = """
SELECT
    pf.question_id,
    pf.country_code,
    prr.search_queries_used,
    prr.source_url,
    prr.evidence_quote,
    prr.retrieval_confidence
FROM phase2_final pf
JOIN phase2_researcher_runs prr ON pf.run_id = prr.run_id
WHERE pf.terminal_status IN ('accepted_by_verifier', 'accepted_by_adjudicator')
  AND prr.evidence_quote IS NOT NULL
  AND prr.source_url IS NOT NULL
  AND length(prr.evidence_quote) >= 30
ORDER BY pf.created_at DESC
LIMIT ?
"""


def build_fixtures(db_path: Path, output: Path, max_rows: int = 50) -> int:
    """Read accepted runs and write fixtures. Returns count written."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(_QUERY, (max_rows,)).fetchall()
    written = 0
    with output.open("w", encoding="utf-8") as f:
        for q, cc, queries_json, url, quote, conf in rows:
            # search_queries_used is a JSON array; take the first
            try:
                queries = json.loads(queries_json) if queries_json else []
            except (TypeError, json.JSONDecodeError):
                queries = []
            if not queries:
                continue
            f.write(json.dumps({
                "question_id": q,
                "country_code": cc,
                "query": queries[0],
                "source_url": url,
                "evidence_quote": quote,
                "retrieval_confidence": conf,
            }) + "\n")
            written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Build snippet-quality fixture")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-rows", type=int, default=50)
    args = parser.parse_args()

    n = build_fixtures(args.db, args.output, args.max_rows)
    print(f"Wrote {n} fixtures to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
