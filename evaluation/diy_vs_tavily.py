"""Adjudicated DIY-vs-Tavily search evaluation.

Measures whether the DIY pipeline retrieves evidence that answers ODMI
questions at least as well as Tavily, judged by a higher-order Opus
adjudicator rather than by string overlap with a historically-accepted
quote (which penalises a different-but-valid passage).

For each (question, country) pair in a dimension-stratified sample of the
swarm's finalised pairs:
  1. fetch top-k evidence from DIY and from Tavily for the same query,
  2. show both sets BLIND (System A / System B) to the adjudicator, with
     the verified ODMI answer as the gold standard,
  3. run the judge twice with positions swapped to control position bias,
  4. combine into one verdict (diy / tavily / tie / both_fail).

Headline metric: DIY "not worse than Tavily" rate = (diy wins + ties) / n.
Evidence sets, both raw verdicts, and reasoning are written to a JSONL so
every judgement is auditable (receipts per the dissertation standard).

Usage:
    uv run python evaluation/diy_vs_tavily.py --limit 40
    uv run python evaluation/diy_vs_tavily.py --limit 2   # smoke test
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "odmi.db"
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"
CACHE_PATH = REPO_ROOT / "evaluation" / ".cache_diy_vs_tavily.json"

GOLD_EXPLANATION_CAP = 800


# ===========================================================================
# Pure logic (unit-tested in tests/test_diy_vs_tavily_eval.py)
# ===========================================================================

def dimension_of(question_id: str) -> str:
    """Leading alpha prefix of a question id: I / P / PT / Q."""
    m = re.match(r"^[A-Za-z]+", question_id)
    return m.group(0) if m else "?"


def stratify_pairs(pairs: List[dict], limit: int) -> List[dict]:
    """Dedupe by (question, country), then round-robin across ODMI
    dimensions so a sample spans Policy/Portal/Quality/Impact evenly."""
    seen = set()
    uniq = []
    for p in pairs:
        key = (p["question_id"], p["country_code"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)

    groups: dict[str, list] = defaultdict(list)
    for p in uniq:
        groups[dimension_of(p["question_id"])].append(p)

    out: List[dict] = []
    dims = list(groups.keys())
    idx = {d: 0 for d in dims}
    while len(out) < limit:
        progressed = False
        for d in dims:
            if idx[d] < len(groups[d]):
                out.append(groups[d][idx[d]])
                idx[d] += 1
                progressed = True
                if len(out) >= limit:
                    break
        if not progressed:
            break
    return out


Frame = Literal["diy", "tavily", "tie", "both_fail"]


def orientation_to_diy(winner: str, *, diy_is: Literal["A", "B"]) -> Frame:
    """Map a blind A/B/tie/both_fail verdict into the DIY frame."""
    if winner in ("tie", "both_fail"):
        return winner  # type: ignore[return-value]
    return "diy" if winner == diy_is else "tavily"


_SCORE = {"diy": 1, "tavily": -1, "tie": 0, "both_fail": 0}


def combine_orientations(o1: Frame, o2: Frame) -> dict:
    """Combine the two position-swapped verdicts into one.

    Pure both_fail in both orientations => both_fail. Otherwise sum a
    DIY-signed score: positive => diy, negative => tavily, zero => tie.
    A diy/tavily disagreement (pure position flip) nets to a tie and is
    flagged inconsistent.
    """
    if o1 == "both_fail" and o2 == "both_fail":
        return {"verdict": "both_fail", "consistent": True}
    s = _SCORE[o1] + _SCORE[o2]
    verdict = "diy" if s > 0 else "tavily" if s < 0 else "tie"
    return {"verdict": verdict, "consistent": o1 == o2}


def aggregate(verdicts: List[dict]) -> dict:
    """Counts and headline rates over a list of combined verdicts."""
    n = len(verdicts)
    counts = {"diy": 0, "tavily": 0, "tie": 0, "both_fail": 0}
    consistent = 0
    for v in verdicts:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
        if v.get("consistent"):
            consistent += 1
    decisive = n - counts["both_fail"]
    return {
        "n": n,
        **counts,
        "decisive": decisive,
        "diy_not_worse_rate": (counts["diy"] + counts["tie"]) / n if n else 0.0,
        # Head-to-head among pairs where at least one system found the answer.
        # both_fail (question unanswerable from the open web / answer on the
        # deny-listed domain) is uninformative about relative quality.
        "diy_not_worse_decisive": (counts["diy"] + counts["tie"]) / decisive if decisive else 0.0,
        "diy_win_rate": counts["diy"] / n if n else 0.0,
        "consistency_rate": consistent / n if n else 0.0,
    }


# ===========================================================================
# Live harness (network + DB + LLM)
# ===========================================================================

# Join researcher runs to finals on pair_run_id, the per-(question,country)
# attempt key. NB: run_id is a BATCH id shared across many questions, so
# joining on it mis-associates queries with questions (every prr row in the
# batch matches). pair_run_id is unique to one pair's attempt, so the query
# always belongs to the right question.
_PAIR_QUERY = """
SELECT pf.question_id, pf.country_code, prr.search_queries_used,
       q.question_text, q.dimension, gt.response, gt.explanation
FROM phase2_final pf
JOIN phase2_researcher_runs prr ON pf.pair_run_id = prr.pair_run_id
JOIN questions q ON q.question_id = pf.question_id
LEFT JOIN ground_truth gt
       ON gt.question_id = pf.question_id AND gt.country_code = pf.country_code
WHERE pf.terminal_status IN ('accepted_by_verifier', 'accepted_by_adjudicator')
  AND prr.search_queries_used IS NOT NULL
GROUP BY pf.question_id, pf.country_code
ORDER BY pf.created_at DESC
"""


def _first_query(queries_json: str) -> Optional[str]:
    try:
        qs = json.loads(queries_json) if queries_json else []
    except (TypeError, json.JSONDecodeError):
        return None
    return qs[0] if qs else None


def _trim_question(text: str) -> str:
    # Drop the questionnaire's "For Explanation: ..." filler addressed to the
    # human respondent; keep only the question itself.
    return re.split(r"For Explanation", text)[0].strip()


def _gold(response: Optional[str], explanation: Optional[str]) -> Optional[str]:
    """Gold standard for the judge: the ANSWER label first (this is what D22
    scores), then ODMI's justification flagged as context only so the judge
    does not treat it as a checklist."""
    if not response:
        return None
    exp = (explanation or "").strip()[:GOLD_EXPLANATION_CAP]
    gold = f"ANSWER: {response}"
    if exp:
        gold += (
            "\n\nODMI's justification (context only, the evidence need not "
            f"repeat these specifics): {exp}"
        )
    return gold


def build_eval_set(db_path: Path) -> List[dict]:
    """Read finalised pairs with a query and ground truth. No stratify yet."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(_PAIR_QUERY).fetchall()
    out = []
    for qid, cc, queries_json, qtext, dim, resp, expl in rows:
        query = _first_query(queries_json)
        gold = _gold(resp, expl)
        if not query or not gold:
            continue  # cannot search or cannot judge against truth
        out.append({
            "question_id": qid,
            "country_code": cc,
            "dimension": dim,
            "query": query,
            "question_text": _trim_question(qtext or qid),
            "gold": gold,
        })
    return out


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")


def get_evidence(query: str, provider: str, *, max_results: int, cache: dict) -> List[dict]:
    """Top-k evidence for one query/provider, cached to disk so the run is
    re-playable and Tavily quota is spent at most once per query."""
    from agents.tools.search import search

    key = f"{provider}::{max_results}::{query}"
    if key in cache:
        return cache[key]
    results = search(query, max_results=max_results, provider=provider)
    evidence = [
        {"url": r.url, "snippet": r.snippet, "title": r.title, "score": r.score}
        for r in results
    ]
    cache[key] = evidence
    return evidence


def judge_pair(pair: dict, *, max_results: int, model: str, cache: dict) -> dict:
    """Fetch both providers' evidence and run the position-swapped judge."""
    from agents.tools.search_adjudicator import adjudicate

    diy_ev = get_evidence(pair["query"], "diy", max_results=max_results, cache=cache)
    tav_ev = get_evidence(pair["query"], "tavily", max_results=max_results, cache=cache)

    # Orientation 1: A = DIY, B = Tavily
    v1, _ = adjudicate(
        question_text=pair["question_text"], ground_truth=pair["gold"],
        evidence_a=diy_ev, evidence_b=tav_ev, model=model,
    )
    o1 = orientation_to_diy(v1.winner, diy_is="A")

    # Orientation 2: A = Tavily, B = DIY (positions swapped)
    v2, _ = adjudicate(
        question_text=pair["question_text"], ground_truth=pair["gold"],
        evidence_a=tav_ev, evidence_b=diy_ev, model=model,
    )
    o2 = orientation_to_diy(v2.winner, diy_is="B")

    combined = combine_orientations(o1, o2)
    return {
        "question_id": pair["question_id"],
        "country_code": pair["country_code"],
        "dimension": pair["dimension"],
        "query": pair["query"],
        "gold": pair["gold"],
        "diy_n": len(diy_ev),
        "tavily_n": len(tav_ev),
        "verdict": combined["verdict"],
        "consistent": combined["consistent"],
        "orientation_1": {"winner": v1.winner, "diy_frame": o1,
                          "diy_supports": v1.answer_supported_by_a,
                          "tavily_supports": v1.answer_supported_by_b,
                          "reasoning": v1.reasoning, "confidence": v1.confidence},
        "orientation_2": {"winner": v2.winner, "diy_frame": o2,
                          "tavily_supports": v2.answer_supported_by_a,
                          "diy_supports": v2.answer_supported_by_b,
                          "reasoning": v2.reasoning, "confidence": v2.confidence},
        "diy_evidence": diy_ev,
        "tavily_evidence": tav_ev,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Adjudicated DIY-vs-Tavily evaluation")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=40, help="eval-set size (stratified)")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--model", type=str, default=None,
                        help="adjudicator model override (default: Opus)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    from agents.tools.search_adjudicator import ADJUDICATOR_MODEL
    model = args.model or ADJUDICATOR_MODEL

    full = build_eval_set(args.db)
    pairs = stratify_pairs(full, args.limit)
    print(f"Eval set: {len(pairs)} pairs (from {len(full)} judgeable), "
          f"adjudicator model={model}")
    dist = defaultdict(int)
    for p in pairs:
        dist[p["dimension"]] += 1
    print(f"Dimension spread: {dict(dist)}")

    cache = _load_cache()
    records = []
    for i, pair in enumerate(pairs, 1):
        tag = f"{pair['question_id']}/{pair['country_code']}"
        try:
            rec = judge_pair(pair, max_results=args.max_results, model=model, cache=cache)
            records.append(rec)
            flag = "" if rec["consistent"] else "  (position-inconsistent)"
            print(f"  [{i}/{len(pairs)}] {tag}: {rec['verdict']}"
                  f"  diy={rec['diy_n']} tav={rec['tavily_n']}{flag}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(pairs)}] {tag}: ERROR {type(exc).__name__}: {exc}")
        finally:
            _save_cache(cache)

    agg = aggregate([{"verdict": r["verdict"], "consistent": r["consistent"]}
                     for r in records])
    print("\n=== DIY vs Tavily (adjudicated) ===")
    print(f"  judged pairs           : {agg['n']}")
    print(f"  DIY wins               : {agg['diy']}")
    print(f"  ties                   : {agg['tie']}")
    print(f"  Tavily wins            : {agg['tavily']}")
    print(f"  both failed            : {agg['both_fail']}  "
          f"(question unanswerable from open web / answer on deny-list)")
    print(f"  decisive pairs         : {agg['decisive']}")
    print(f"  DIY NOT WORSE (decisive)  : {agg['diy_not_worse_decisive']:.0%}  "
          f"<- headline, target >= 80%")
    print(f"  DIY not worse (all)    : {agg['diy_not_worse_rate']:.0%}")
    print(f"  DIY strict win rate    : {agg['diy_win_rate']:.0%}")
    print(f"  position consistency   : {agg['consistency_rate']:.0%}")

    # Per-dimension verdict spread (shows the both_fail concentration).
    bydim: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in records:
        bydim[r["dimension"]][r["verdict"]] += 1
    print("\n  per-dimension verdicts (diy/tie/tavily/both_fail):")
    for dim in sorted(bydim):
        d = bydim[dim]
        print(f"    {dim:<8} {d['diy']}/{d['tie']}/{d['tavily']}/{d['both_fail']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.out or (RESULTS_DIR / f"diy_vs_tavily_{stamp}.jsonl")
    with out.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"summary": agg, "model": model,
                            "generated_at": stamp}) + "\n")
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(records)} judged records to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
