"""EXP-24 Phase B: snippet-cap replay (Opus).

For each (question, country) pair the swarm abstained on, re-run ONLY the
Researcher's reasoning call (no new search, no new fetch) using the SAME
stored snippets, at different per-snippet caps. Single variable: the cap.

Holds constant: question, country, snippets fetched, prior queries, prompt
template, output schema. Changes: max_chars_per_snippet in
agents.prompts.researcher.build_user_message, and the model is pinned to Opus
across all arms.

This script does spend tokens (Opus). Sample sizes are conservative; pass
--n to scale. Per-row cost is logged.

Run:  uv run python evaluation/snippet_cap_replay.py --n 20
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agents import prompts as _prompts_pkg  # noqa: F401  ensure import path
from agents.prompts import researcher as researcher_prompt
from agents.models import ResearcherInput, ResearcherOutput
from agents.tools.search import SearchResult
from agents.tools.llm import call_for_structured, StructuredOutputError

DEFAULT_DB = REPO / "data" / "odmi.db"
OPUS_MODEL = "claude-opus-4-6"

# Caps to compare. 600 is the production baseline; 3000 is the treatment.
CAPS = (600, 3000)

# Country metadata, mirrored from scripts/run_coordinator.COUNTRIES.
META = {
    "NL": ("Netherlands", "nl"),
    "MT": ("Malta", "en"),
    "FI": ("Finland", "fi"),
    "NO": ("Norway", "no"),
    "SE": ("Sweden", "sv"),
    "AL": ("Albania", "sq"),
    "HR": ("Croatia", "hr"),
    "FR": ("France", "fr"),
}


def build_input(cur: sqlite3.Cursor, qid: str, cc: str) -> ResearcherInput | None:
    row = cur.execute(
        "SELECT question_id, question_text, dimension, indicator, "
        "  COALESCE(response_scoring,'') response_scoring, "
        "  COALESCE(answer_shape,'binary') answer_shape, "
        "  COALESCE(allowed_answers,'[\"yes\",\"no\"]') allowed_answers "
        "FROM questions WHERE question_id=?", (qid,)
    ).fetchone()
    if not row:
        return None
    cname, clang = META.get(cc, (cc, "en"))
    try:
        allowed = json.loads(row["allowed_answers"])
    except (ValueError, TypeError):
        allowed = ["yes", "no"]
    return ResearcherInput(
        question_id=row["question_id"],
        question_text=row["question_text"],
        dimension=row["dimension"],
        indicator=row["indicator"],
        response_scoring=row["response_scoring"],
        country_code=cc,
        country_name=cname,
        country_language=clang,
        answer_shape=row["answer_shape"],
        allowed_answers=allowed,
    )


def load_snippets(cur: sqlite3.Cursor, qid: str, cc: str) -> tuple[list[SearchResult], list[str]]:
    """Pull the richest stored Researcher run for (qid, cc): the run with the
    longest combined snippet payload. Returns (search_results, queries_used)."""
    rrows = cur.execute(
        "SELECT search_snippets, search_queries_used "
        "FROM phase2_researcher_runs "
        "WHERE question_id=? AND country_code=? "
        "  AND search_snippets IS NOT NULL AND search_snippets <> '[]' "
        "ORDER BY LENGTH(search_snippets) DESC LIMIT 1",
        (qid, cc),
    ).fetchone()
    if not rrows:
        return ([], [])
    try:
        raw = json.loads(rrows["search_snippets"])
    except (ValueError, TypeError):
        return ([], [])
    sr: list[SearchResult] = []
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        sr.append(SearchResult(
            title=s.get("title") or s.get("url", ""),
            url=s.get("url", ""),
            snippet=s.get("snippet", ""),
            score=s.get("score"),
            provider=s.get("provider", "diy"),
        ))
    try:
        queries = json.loads(rrows["search_queries_used"] or "[]")
        if not isinstance(queries, list):
            queries = []
    except (ValueError, TypeError):
        queries = []
    return (sr, queries)


def gt_for(cur: sqlite3.Cursor, qid: str, cc: str) -> str:
    r = cur.execute(
        "SELECT COALESCE(response,'') response FROM ground_truth "
        "WHERE question_id=? AND country_code=?", (qid, cc),
    ).fetchone()
    return (r["response"] if r else "").strip().lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--n", type=int, default=20, help="pairs to replay")
    ap.add_argument("--country", default="NL", help="country code (NL or MT)")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Pick abstained binary pairs for the country, prefer ones with a long snippet.
    pairs = cur.execute(
        "SELECT DISTINCT f.question_id, f.country_code "
        "FROM phase2_final f "
        "JOIN questions q ON q.question_id=f.question_id "
        "JOIN ground_truth g "
        "  ON g.question_id=f.question_id AND g.country_code=f.country_code "
        "WHERE f.country_code=? "
        "  AND (f.final_answer='inconclusive' OR f.terminal_status='agent_failure') "
        "  AND q.answer_shape='binary' "
        "  AND LOWER(TRIM(g.response)) IN ('yes','no') "
        "ORDER BY f.question_id",
        (args.country,),
    ).fetchall()
    print(f"# Candidate abstained binary pairs for {args.country}: {len(pairs)}",
          file=sys.stderr)

    # Filter to pairs with at least one stored snippet > 1500 chars (where the
    # cap can hide something) and sample up to N.
    selected: list[tuple[str, str]] = []
    for p in pairs:
        sr, _ = load_snippets(cur, p["question_id"], p["country_code"])
        if any(len(r.snippet) > 1500 for r in sr):
            selected.append((p["question_id"], p["country_code"]))
        if len(selected) >= args.n:
            break
    print(f"# Selected with long snippet: {len(selected)}", file=sys.stderr)

    prompt_spec = researcher_prompt.variant("full")

    # Columns of the output table: pair, GT, baseline cap=600 answer/conf/match,
    # treatment cap=3000 answer/conf/match.
    print("pair\tcountry\tgt\tbase_ans\tbase_conf\tbase_match\ttreat_ans\ttreat_conf\ttreat_match\tflip")
    summary: dict[str, int] = {
        "n": 0, "base_committed": 0, "treat_committed": 0,
        "base_correct": 0, "treat_correct": 0,
        "flip_abst_to_correct": 0, "flip_abst_to_wrong": 0,
        "flip_correct_to_abst": 0,
    }
    total_cost = 0.0
    for qid, cc in selected:
        rinp = build_input(cur, qid, cc)
        if not rinp:
            continue
        sr, queries = load_snippets(cur, qid, cc)
        if not sr or not queries:
            continue
        gt = gt_for(cur, qid, cc)
        outs: dict[int, tuple[str, float]] = {}
        for cap in CAPS:
            user_msg = researcher_prompt.build_user_message(
                rinp, search_results=sr, queries_used=queries,
                max_chars_per_snippet=cap,
            )
            try:
                out, usage = call_for_structured(
                    system=prompt_spec.system,
                    user_message=user_msg,
                    output_schema=ResearcherOutput,
                    model=OPUS_MODEL,
                    max_tokens=2000,
                    condition_label="exp24_replay",
                    prompt_version_id=None,
                    usage_context=f"exp24:{qid}:{cc}:cap{cap}",
                    subtrio_id=None,
                )
            except StructuredOutputError as exc:
                outs[cap] = ("schema_invalid", 0.0)
                continue
            except Exception as exc:
                import traceback
                print(f"!! ERROR on {qid}/{cc} cap={cap}: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                outs[cap] = (f"error:{type(exc).__name__}", 0.0)
                continue
            ans = (out.answer or "").strip().lower()
            outs[cap] = (ans, float(out.answer_confidence or 0.0))
            if usage and getattr(usage, "estimated_cost_usd", None):
                total_cost += float(usage.estimated_cost_usd)

        base_ans, base_conf = outs.get(600, ("error", 0.0))
        treat_ans, treat_conf = outs.get(3000, ("error", 0.0))

        committed = lambda a: a in {"yes", "no"}
        match = lambda a: committed(a) and a == gt
        base_committed = committed(base_ans)
        treat_committed = committed(treat_ans)
        base_match = match(base_ans)
        treat_match = match(treat_ans)
        flip = "none"
        if not base_committed and treat_committed and treat_match:
            flip = "abst->correct"; summary["flip_abst_to_correct"] += 1
        elif not base_committed and treat_committed and not treat_match:
            flip = "abst->wrong"; summary["flip_abst_to_wrong"] += 1
        elif base_committed and not treat_committed:
            flip = "correct->abst" if base_match else "wrong->abst"
            if base_match: summary["flip_correct_to_abst"] += 1
        elif base_committed and treat_committed and base_ans != treat_ans:
            flip = f"{base_ans}->{treat_ans}"

        summary["n"] += 1
        summary["base_committed"] += int(base_committed)
        summary["treat_committed"] += int(treat_committed)
        summary["base_correct"] += int(base_match)
        summary["treat_correct"] += int(treat_match)

        print(f"{qid}\t{cc}\t{gt}\t{base_ans}\t{base_conf:.2f}\t"
              f"{'Y' if base_match else 'N'}\t"
              f"{treat_ans}\t{treat_conf:.2f}\t"
              f"{'Y' if treat_match else 'N'}\t{flip}")

    print(f"\n# SUMMARY (n={summary['n']})", file=sys.stderr)
    for k in ("base_committed","treat_committed","base_correct","treat_correct",
              "flip_abst_to_correct","flip_abst_to_wrong","flip_correct_to_abst"):
        print(f"#   {k}: {summary[k]}", file=sys.stderr)
    print(f"# Approx Opus spend: ${total_cost:.2f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
