"""Run the Researcher once on a single ODMI (question, country).

Usage:
    uv run python scripts/run_researcher.py P1 FR                    # save row, print summary
    uv run python scripts/run_researcher.py P1 FR --walkthrough      # print every step
    uv run python scripts/run_researcher.py P1 FR --dry-run          # don't save to DB
    uv run python scripts/run_researcher.py P1 FR --walkthrough --dry-run

`--walkthrough` is the "show me what is happening" mode used in the
first runs while we validate the agent against hand-marks and probe
the three failure scenarios named in `docs/AGENT_DESIGN.md` Section 8.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.models import ResearcherInput
from agents.researcher import ResearcherRunResult, run_researcher
from agents.tools.db import DB_PATH, connect

QUESTIONS_JSON = REPO_ROOT / "data" / "questions" / "odmi_2025_questions.json"

# Minimal country metadata. Expanded per country as Phase B starts.
COUNTRIES = {
    "FR": {
        "country_name": "France",
        "country_language": "fr",
        "portal_url": "https://www.data.gouv.fr/",
    },
}


# ============================================================
# CLI helpers
# ============================================================


def _load_question(question_id: str) -> dict:
    if not QUESTIONS_JSON.exists():
        sys.exit(
            f"Question bank not found at {QUESTIONS_JSON}. "
            f"Run scripts/parse_questions.py first."
        )
    questions = json.loads(QUESTIONS_JSON.read_text())
    by_id = {q["question_id"]: q for q in questions}
    if question_id not in by_id:
        sys.exit(
            f"Question {question_id!r} not found. "
            f"Try one of {list(by_id)[:6]}..."
        )
    return by_id[question_id]


def _build_input(question_id: str, country_code: str) -> ResearcherInput:
    q = _load_question(question_id)
    meta = COUNTRIES.get(country_code.upper())
    if meta is None:
        sys.exit(
            f"Country {country_code!r} not configured. "
            f"Add it to scripts/run_researcher.py COUNTRIES."
        )
    return ResearcherInput(
        question_id=q["question_id"],
        question_text=q["question_text"],
        dimension=q["dimension"],
        indicator=q["indicator"],
        response_scoring=q.get("response_scoring", ""),
        country_code=country_code.upper(),
        country_name=meta["country_name"],
        country_language=meta["country_language"],
        portal_url=meta.get("portal_url"),
    )


# ============================================================
# Walkthrough printing
# ============================================================


def make_walkthrough_callback(*, enabled: bool):
    """Return an on_step callback that prints (or doesn't)."""

    def _on_step(event: str, payload: dict) -> None:
        if not enabled:
            return
        line = f"  [{event}]"
        if event == "start":
            print(
                f"\n>>> RESEARCHER START "
                f"question={payload['question_id']} country={payload['country']}"
            )
            return
        if event == "query_gen_start":
            print("  step 1: generating search queries via Claude micro-call...")
            return
        if event == "query_gen_complete":
            qs = payload["queries"]
            print(
                f"  step 1 done: {len(qs)} queries, "
                f"{payload['input_tokens']}+{payload['output_tokens']} tok, "
                f"{payload['wall_clock_ms']} ms"
            )
            for q in qs:
                print(f"    - {q}")
            return
        if event == "query_gen_failed":
            print(f"  step 1 FAILED: {payload['error'][:200]}")
            return
        if event == "search_start":
            print(f"  step 2: searching Tavily with {len(payload['queries'])} queries...")
            return
        if event == "search_complete":
            print(f"  step 2 done: {payload['n_results']} unique results.")
            for title in payload["top_titles"]:
                print(f"    - {title}")
            return
        if event == "main_call_start":
            print(
                f"  step 3: main Claude call "
                f"(prompt_version_id={payload['prompt_version_id']}, "
                f"{payload['user_message_chars']} chars in user message)..."
            )
            return
        if event == "main_call_complete":
            print(
                f"  step 3 done: answer={payload['answer']!r} "
                f"answer_conf={payload['answer_confidence']:.2f} "
                f"retrieval_conf={payload['retrieval_confidence']:.2f}"
            )
            print(f"    source_url: {payload['source_url']}")
            print(
                f"    tokens: {payload['input_tokens']}+{payload['output_tokens']}, "
                f"{payload['wall_clock_ms']} ms, "
                f"£{(payload['cost_usd'] or 0) * 0.79:.6f}"
                if payload["cost_usd"] is not None
                else f"    tokens: {payload['input_tokens']}+{payload['output_tokens']}, "
                f"{payload['wall_clock_ms']} ms"
            )
            return
        if event == "main_call_failed":
            print(f"  step 3 FAILED: {payload['error'][:200]}")
            return
        if event == "validation_start":
            print("  step 4: post-call validation (HEAD check + trust score)...")
            return
        if event == "validation_complete":
            print(
                f"  step 4 done: head_ok={payload['head_ok']} "
                f"(HTTP {payload['head_status']}), "
                f"domain_trust={payload['domain_trust']}, "
                f"failure_mode={payload['failure_mode']}"
            )
            if payload["notes"]:
                for n in payload["notes"]:
                    print(f"    note: {n}")
            return
        # Unknown events get a generic print.
        print(f"  [{event}] {payload}")

    return _on_step


# ============================================================
# DB row writer
# ============================================================


def save_run(
    *,
    result: ResearcherRunResult,
    input: ResearcherInput,
    run_id: str,
    pair_run_id: str,
    retry_count: int,
    condition_label: str,
    db_path: Path = DB_PATH,
) -> int:
    """Insert one phase2_researcher_runs row. Returns the new row id."""
    o = result.output
    main = result.main_usage

    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO phase2_researcher_runs (
                run_id, pair_run_id, question_id, country_code, retry_count,
                answer, answer_explanation, evidence_quote, source_url,
                retrieval_confidence, answer_confidence,
                search_queries_used, fetched_urls,
                domain_trust_score, language_route_used, notes,
                failure_mode,
                input_tokens, output_tokens, wall_clock_ms,
                estimated_cost_usd, condition_label,
                prompt_version_id, model_version, raw_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, pair_run_id, input.question_id, input.country_code, retry_count,
                o.answer if o else None,
                o.answer_explanation if o else None,
                o.evidence_quote if o else None,
                str(o.source_url) if o else None,
                o.retrieval_confidence if o else None,
                o.answer_confidence if o else None,
                json.dumps(result.search_queries_used),
                json.dumps(result.fetched_urls),
                result.domain_trust,
                o.language_route_used if o else None,
                result.notes,
                result.failure_mode,
                result.cumulative_input_tokens,
                result.cumulative_output_tokens,
                result.cumulative_wall_clock_ms,
                result.cumulative_cost_usd,
                condition_label,
                main.prompt_version_id if main else None,
                main.model_version if main else (
                    result.query_gen_usage.model_version if result.query_gen_usage else "unknown"
                ),
                main.raw_response if main else None,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


# ============================================================
# Main
# ============================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Researcher on one ODMI question.")
    parser.add_argument("question_id", help="e.g. P1, PT4, Q1, I1, P10-a")
    parser.add_argument("country_code", help="ISO 3166-1 alpha-2, e.g. FR")
    parser.add_argument(
        "--walkthrough", action="store_true",
        help="Print every step (recommended for early runs).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip writing to SQLite. Useful for development.",
    )
    parser.add_argument(
        "--condition-label", default="baseline",
        help="Optimisation-experiment condition label, recorded on the row.",
    )
    parser.add_argument(
        "--run-id", default=None,
        help="Override the batch run UUID. Defaults to a fresh UUID.",
    )
    args = parser.parse_args()

    input = _build_input(args.question_id, args.country_code)
    run_id = args.run_id or str(uuid.uuid4())
    pair_run_id = str(uuid.uuid4())
    retry_count = 0

    on_step = make_walkthrough_callback(enabled=args.walkthrough)

    result = run_researcher(
        input,
        condition_label=args.condition_label,
        on_step=on_step,
    )

    # ----- Print summary -----
    print()
    print("=" * 64)
    print(f"RESEARCHER FINISHED  question={input.question_id} country={input.country_code}")
    print("=" * 64)
    if result.output is None:
        print(f"  Outcome: FAILED  failure_mode={result.failure_mode}")
        print(f"  Notes: {result.notes}")
    else:
        o = result.output
        print(f"  Answer:        {o.answer}  (conf={o.answer_confidence:.2f})")
        print(f"  Explanation:   {o.answer_explanation}")
        print(f"  Evidence:      \"{o.evidence_quote[:120]}{'...' if len(o.evidence_quote) > 120 else ''}\"")
        print(f"  Source URL:    {o.source_url}")
        print(f"  Retrieval conf: {o.retrieval_confidence:.2f}   domain trust: {result.domain_trust}")
        if result.failure_mode:
            print(f"  Failure mode:   {result.failure_mode}")
        if result.notes:
            print(f"  Notes:         {result.notes}")
    print()
    print(f"  Cost receipts (cumulative across all LLM calls):")
    print(f"    input_tokens:   {result.cumulative_input_tokens}")
    print(f"    output_tokens:  {result.cumulative_output_tokens}")
    print(f"    wall_clock_ms:  {result.cumulative_wall_clock_ms}")
    if result.cumulative_cost_usd is not None:
        print(f"    estimated_cost: £{result.cumulative_cost_usd * 0.79:.6f}")
    print()

    if args.dry_run:
        print("--dry-run: not writing to SQLite.")
    else:
        row_id = save_run(
            result=result,
            input=input,
            run_id=run_id,
            pair_run_id=pair_run_id,
            retry_count=retry_count,
            condition_label=args.condition_label,
        )
        print(f"Saved phase2_researcher_runs row id={row_id} (pair_run_id={pair_run_id})")


if __name__ == "__main__":
    main()
