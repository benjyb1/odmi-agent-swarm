"""EXP-39 Part B: within-country evidence-language contrast (observational).

No translation, no LLM calls. Language-IDs the evidence behind every
finalised pair and asks, within each country, whether pairs resolved on
non-English evidence do worse than pairs resolved on English evidence.
Holding country fixed removes the web-estate and base-rate confounds that
make cross-country language comparisons circular; the residual confound
(non-English-evidence questions may be intrinsically harder) is why results
are read as a bracket, with a Mantel-Haenszel pool over ODMI-dimension
strata as the adjusted view.

Standalone: needs `langdetect` only (plus the repo for evaluation/stats.py).
Runs under the same side venv as exp39_translate.py:

  /tmp/exp39mt/bin/python evaluation/exp39_evidence_language_contrast.py \
      --db data/odmi.db                      # dev/main rows (default)
  ... --db <path> --experiment-id exp36_frozen_headline   # headline, later

Buckets: english / non_english / undetermined (quote too short or detector
error). langdetect lacks Maltese and the Serbo-Croatian variants, so the
primary contrast is deliberately english vs non-english, not per-language.

Outcomes per committed pair (canonical row = latest phase2_final per
question+country+condition): match / differ against ground_truth using the
same yes-family equivalence as the dashboard's _MATCH_STATUS_SQL.
Abstentions are bucketed by the latest researcher attempt's evidence quote
and reported as abstention rate by language (secondary).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from langdetect import DetectorFactory, detect

DetectorFactory.seed = 0
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from evaluation import stats  # noqa: E402

RESULTS = REPO / "evaluation" / "results"
MIN_DETECT_CHARS = 40

def match_status_sql() -> str:
    """Extract the dashboard's canonical match CASE verbatim.

    dashboard/lib/db.py cannot be imported here (it pulls streamlit), so the
    SQL constant is read out of the source text. Using the identical CASE
    guarantees this analysis scores pairs exactly as the dashboard and the
    accuracy queries do (yes-family, n/a handling, near_match bands).
    """
    src = (REPO / "dashboard" / "lib" / "db.py").read_text()
    start = src.index('_MATCH_STATUS_SQL = """') + len('_MATCH_STATUS_SQL = """')
    end = src.index('"""', start)
    return src[start:end]


def lang_bucket(text: str | None) -> str:
    if not text or len(text.strip()) < MIN_DETECT_CHARS:
        return "undetermined"
    try:
        return "english" if detect(text) == "en" else "non_english"
    except Exception:  # noqa: BLE001
        return "undetermined"


def mantel_haenszel(strata: list[tuple[int, int, int, int]]) -> float | None:
    """MH common odds ratio over (a, b, c, d) strata tables.

    a = english match, b = english differ, c = non-english match,
    d = non-english differ.
    """
    num = den = 0.0
    for a, b, c, d in strata:
        n = a + b + c + d
        if n == 0:
            continue
        num += a * d / n
        den += b * c / n
    if den == 0:
        return None
    return num / den


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(REPO / "data" / "odmi.db"))
    ap.add_argument("--experiment-id", default=None,
                    help="None = main production rows (experiment_id IS NULL)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    exp_clause = (
        "f.experiment_id IS NULL" if args.experiment_id is None
        else "f.experiment_id = :eid"
    )
    params = {} if args.experiment_id is None else {"eid": args.experiment_id}

    case_sql = match_status_sql()
    rows = conn.execute(
        f"""
        WITH canonical AS (
            SELECT ff.*, ROW_NUMBER() OVER (
                PARTITION BY ff.question_id, ff.country_code
                ORDER BY ff.id DESC
            ) rn
            FROM phase2_final ff
            WHERE {exp_clause.replace('f.', 'ff.')}
        )
        SELECT f.question_id, f.country_code, f.terminal_status,
               f.final_answer, f.final_evidence_quote,
               gt.response AS gold, q.dimension,
               {case_sql} AS match_status
        FROM canonical f
        LEFT JOIN ground_truth gt
          ON gt.question_id = f.question_id
         AND gt.country_code = f.country_code
        LEFT JOIN questions q ON q.question_id = f.question_id
        WHERE f.rn = 1
        """,
        params,
    ).fetchall()

    latest_attempt = {
        (r["question_id"], r["country_code"]): r["evidence_quote"]
        for r in conn.execute(
            """
            SELECT question_id, country_code, evidence_quote,
                   ROW_NUMBER() OVER (
                       PARTITION BY question_id, country_code
                       ORDER BY id DESC) rn
            FROM phase2_researcher_runs
            """
        )
        if r["rn"] == 1
    }
    conn.close()

    per_country = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # cc -> bucket -> [match, differ]
    strata = defaultdict(list)  # cc -> [(a,b,c,d) per dimension]
    dim_cells = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0])))
    abstain = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # cc -> bucket -> [abstained, total]

    for r in rows:
        cc = r["country_code"]
        ms = r["match_status"]
        committed = (r["terminal_status"] or "").startswith("accepted")
        if committed and ms in ("match", "differ", "near_match"):
            # near_match is scored as its own bucket by the dashboard; for
            # the binary contrast here it counts toward differ (it is not an
            # exact match), disclosed in the JSON.
            bucket = lang_bucket(r["final_evidence_quote"])
            cell = per_country[cc][bucket]
            cell[0 if ms == "match" else 1] += 1
            dim_cells[cc][r["dimension"] or "?"][bucket][0 if ms == "match" else 1] += 1
        elif ms in ("abstained",) or not committed:
            quote = latest_attempt.get((r["question_id"], cc))
            bucket = lang_bucket(quote)
            abstain[cc][bucket][1] += 1
            if ms == "abstained" or (r["terminal_status"] or "").startswith("abstained"):
                abstain[cc][bucket][0] += 1

    report = {"experiment_id": args.experiment_id, "db": args.db, "countries": {}}
    print(f"\nEXP-39 Part B: evidence-language contrast "
          f"({'main rows' if not args.experiment_id else args.experiment_id})")
    for cc in sorted(per_country):
        cinfo = {"committed": {}, "mh_odds_ratio_en_vs_nonen": None, "abstention": {}}
        print(f"\n{cc}:")
        for bucket in ("english", "non_english", "undetermined"):
            m, d = per_country[cc][bucket]
            n = m + d
            if n == 0:
                continue
            lo, hi = stats.wilson_interval(m, n)
            cinfo["committed"][bucket] = dict(
                match=m, differ=d, accuracy=m / n, wilson=[lo, hi])
            print(f"  {bucket:13} commit-acc {m}/{n} = {m/n:.2f} "
                  f"[{lo:.2f},{hi:.2f}]")
        tables = []
        for dim, cells in dim_cells[cc].items():
            a, b = cells["english"]
            c, d = cells["non_english"]
            tables.append((a, b, c, d))
        orx = mantel_haenszel(tables)
        cinfo["mh_odds_ratio_en_vs_nonen"] = orx
        if orx is not None:
            print(f"  MH odds ratio (english vs non-english, "
                  f"dimension-stratified): {orx:.2f}")
        for bucket, (ab, tot) in abstain[cc].items():
            if tot:
                cinfo["abstention"][bucket] = dict(abstained=ab, of=tot)
        report["countries"][cc] = cinfo

    out = Path(args.out) if args.out else RESULTS / (
        f"exp39_partB_{args.experiment_id or 'main'}.json"
    )
    out.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
