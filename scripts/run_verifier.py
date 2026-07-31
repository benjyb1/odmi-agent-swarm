"""Run the Verifier on the latest (or a specific) Researcher row.

Usage:
    uv run python scripts/run_verifier.py P1 FR                          # default strategy (disprove)
    uv run python scripts/run_verifier.py I1 FR --strategy verifier-blind
    uv run python scripts/run_verifier.py I1 FR --walkthrough
    uv run python scripts/run_verifier.py I1 FR --dry-run
    uv run python scripts/run_verifier.py I1 FR --researcher-run-id 3   # explicit row

The Verifier reads the Researcher's output from the SQLite database.
By default it picks the most recent row for the (question, country) pair.
Use --researcher-run-id to pin a specific row.

Four strategies are available (per D15):
  verifier-disprove   Default. Explicit sceptical stance.
  verifier-negation   Searches for the logical opposite answer.
  verifier-steelman   Steelmans the claim then attacks even that.
  verifier-blind      Forms its own answer; Python compares.
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

from agents.models import (
    ResearcherOutput,
    VerifierInput,
    VerifierStrategy,
)
from agents.verifier import VerifierRunResult, run_verifier
from agents.tools.db import connect

VALID_STRATEGIES: list[VerifierStrategy] = [
    "verifier-disprove",
    "verifier-negation",
    "verifier-steelman",
    "verifier-blind",
]


# DB helpers

def _load_researcher_row(
    question_id: str,
    country_code: str,
    researcher_run_id: Optional[int],
    db_path: Path | None = None,
) -> dict:
    """Fetch a phase2_researcher_runs row from SQLite.

    If researcher_run_id is given, load that specific row.
    Otherwise, load the most recent row for (question_id, country_code).
    """
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row  # type: ignore[assignment]
        if researcher_run_id is not None:
            cur = conn.execute(
                "SELECT * FROM phase2_researcher_runs WHERE id = ?",
                (researcher_run_id,),
            )
        else:
            cur = conn.execute(
                """SELECT * FROM phase2_researcher_runs
                   WHERE question_id = ? AND country_code = ?
                   ORDER BY id DESC LIMIT 1""",
                (question_id, country_code.upper()),
            )
        row = cur.fetchone()

    if row is None:
        if researcher_run_id is not None:
            sys.exit(f"No phase2_researcher_runs row with id={researcher_run_id}.")
        sys.exit(
            f"No Researcher row found for ({question_id}, {country_code.upper()}). "
            "Run scripts/run_researcher.py first."
        )

    return dict(row)


def _row_to_researcher_output(row: dict) -> ResearcherOutput:
    """Reconstruct a ResearcherOutput from a phase2_researcher_runs row."""
    if row.get("answer") is None:
        sys.exit(
            f"Researcher row id={row['id']} has no answer "
            f"(failure_mode={row.get('failure_mode')!r}). "
            "Cannot run the Verifier on a failed Researcher row."
        )
    return ResearcherOutput(
        answer=row["answer"],
        answer_explanation=row["answer_explanation"] or "",
        evidence_quote=row["evidence_quote"] or " ",
        source_url=row["source_url"],
        retrieval_confidence=row["retrieval_confidence"] or 0.0,
        answer_confidence=row["answer_confidence"] or 0.0,
        search_queries_used=json.loads(row["search_queries_used"] or "[]"),
        fetched_urls=json.loads(row["fetched_urls"] or "[]"),
        domain_trust_score=row["domain_trust_score"],
        language_route_used=row["language_route_used"] or "native",
        notes=row["notes"],
    )


def _load_question_text(question_id: str, db_path: Path | None = None) -> str:
    """Fetch question_text from the questions table."""
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT question_text FROM questions WHERE question_id = ?",
            (question_id,),
        )
        row = cur.fetchone()
    if row is None:
        # Fall back to the questions JSON if the DB isn't populated.
        questions_json = REPO_ROOT / "data" / "questions" / "odmi_2025_questions.json"
        if questions_json.exists():
            questions = json.loads(questions_json.read_text())
            by_id = {q["question_id"]: q for q in questions}
            if question_id in by_id:
                return by_id[question_id]["question_text"]
        sys.exit(
            f"Question {question_id!r} not found in DB or questions JSON. "
            "Run scripts/parse_questions.py first."
        )
    return str(row[0])


# Country metadata: mirrors run_researcher.py.
COUNTRIES = {
    "FR": {
        "country_name": "France",
    },
}


# Walkthrough printing

def make_walkthrough_callback(*, enabled: bool):
    def _on_step(event: str, payload: dict) -> None:
        if not enabled:
            return
        if event == "start":
            print(
                f"\n>>> VERIFIER START "
                f"question={payload['question_id']} "
                f"country={payload['country']} "
                f"strategy={payload['strategy']}"
            )
            print(
                f"    Researcher said: {payload['researcher_answer']!r}"
            )
            return
        if event == "substring_check_start":
            print(f"  step 1: substring check against {payload['url'][:80]}...")
            return
        if event == "substring_check_complete":
            status = f"HTTP {payload['fetch_status']}" if payload["fetch_status"] else "unreachable"
            print(
                f"  step 1 done: result={payload['result']!r} "
                f"({status})"
                + (f"  note: {payload['notes']}" if payload["notes"] else "")
            )
            return
        if event == "query_gen_start":
            print("  step 2: generating adversarial queries via Claude micro-call...")
            return
        if event == "query_gen_complete":
            qs = payload["queries"]
            print(
                f"  step 2 done: {len(qs)} queries, "
                f"{payload['input_tokens']}+{payload['output_tokens']} tok, "
                f"{payload['wall_clock_ms']} ms"
            )
            for q in qs:
                print(f"    - {q}")
            return
        if event == "query_gen_failed":
            print(f"  step 2 FAILED: {payload['error'][:200]}")
            return
        if event == "search_start":
            print(f"  step 3: searching Tavily with {len(payload['queries'])} adversarial queries...")
            return
        if event == "search_complete":
            print(f"  step 3 done: {payload['n_results']} results.")
            for title in payload["top_titles"]:
                print(f"    - {title}")
            return
        if event == "main_call_start":
            print(
                f"  step 4: main Claude call "
                f"(strategy={payload['strategy']!r}, "
                f"prompt_version_id={payload['prompt_version_id']}, "
                f"{payload['user_message_chars']} chars)..."
            )
            return
        if event == "main_call_complete":
            print(
                f"  step 4 done: verdict={payload['verdict']!r} "
                f"verifier_answer={payload['verifier_answer']!r} "
                f"confidence={payload['verifier_confidence']:.2f}"
            )
            if payload["rejection_reason"]:
                print(f"    rejection: {payload['rejection_reason'][:150]}")
            print(
                f"    tokens: {payload['input_tokens']}+{payload['output_tokens']}, "
                f"{payload['wall_clock_ms']} ms"
                + (f", £{payload['cost_usd'] * 0.79:.6f}" if payload["cost_usd"] else "")
            )
            return
        if event == "main_call_failed":
            print(f"  step 4 FAILED: {payload['error'][:200]}")
            return
        if event == "blind_comparison":
            match = "MATCH" if payload["answers_match"] else "DIVERGE"
            print(
                f"  blind: researcher={payload['researcher_answer']!r} "
                f"verifier={payload['verifier_answer']!r} → {match}"
            )
            return
        print(f"  [{event}] {payload}")

    return _on_step


# DB row writer

def save_run(
    *,
    result: VerifierRunResult,
    inp: VerifierInput,
    researcher_db_id: int,
    run_id: str,
    pair_run_id: str,
    retry_count: int,
    condition_label: str,
    db_path: Path | None = None,
) -> int:
    """Insert one phase2_verifier_runs row. Returns the new row id."""
    o = result.output
    main = result.main_usage

    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO phase2_verifier_runs (
                run_id, pair_run_id, question_id, country_code, retry_count,
                strategy_label, researcher_run_id,
                verdict, verifier_answer, verifier_confidence,
                substring_check_result, substring_check_notes,
                independent_search_queries, independent_evidence,
                rejection_reason, counter_evidence_quote,
                counter_source_url, suggested_search_query,
                failure_mode,
                input_tokens, output_tokens, wall_clock_ms,
                estimated_cost_usd, condition_label,
                prompt_version_id, model_version, raw_response
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?
            )""",
            (
                run_id, pair_run_id, inp.question_id, inp.country_code, retry_count,
                result.strategy, researcher_db_id,
                o.verdict if o else None,
                o.verifier_answer if o else None,
                o.verifier_confidence if o else None,
                result.substring_result,
                result.substring_notes,
                json.dumps(result.adversarial_queries),
                json.dumps([r.snippet[:300] for r in result.search_results]),
                o.rejection_reason if o else None,
                o.counter_evidence_quote if o else None,
                str(o.counter_source_url) if o and o.counter_source_url else None,
                o.suggested_search_query if o else None,
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


# Main

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Verifier on an existing Researcher row."
    )
    parser.add_argument("question_id", help="e.g. P1, I1, Q1, P10-a")
    parser.add_argument("country_code", help="ISO 3166-1 alpha-2, e.g. FR")
    parser.add_argument(
        "--strategy",
        default="verifier-disprove",
        choices=VALID_STRATEGIES,
        help="Verifier prompt strategy (default: verifier-disprove).",
    )
    parser.add_argument(
        "--researcher-run-id",
        type=int,
        default=None,
        help=(
            "Use a specific phase2_researcher_runs row id. "
            "Defaults to the most recent row for this question/country."
        ),
    )
    parser.add_argument(
        "--walkthrough", action="store_true",
        help="Print every step.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip writing to SQLite.",
    )
    parser.add_argument(
        "--condition-label", default="baseline",
        help="Optimisation-experiment condition label.",
    )
    parser.add_argument(
        "--run-id", default=None,
        help="Override the batch run UUID.",
    )
    args = parser.parse_args()

    country_code = args.country_code.upper()
    meta = COUNTRIES.get(country_code)
    if meta is None:
        sys.exit(
            f"Country {country_code!r} not configured. "
            "Add it to scripts/run_verifier.py COUNTRIES."
        )

    # Load the Researcher row from DB.
    row = _load_researcher_row(args.question_id, country_code, args.researcher_run_id)
    researcher_db_id = int(row["id"])
    researcher_output = _row_to_researcher_output(row)
    question_text = _load_question_text(args.question_id)

    from agents.tools import answer_shapes
    shape = answer_shapes.load_question_shape(args.question_id)
    inp = VerifierInput(
        question_id=args.question_id,
        question_text=question_text,
        country_code=country_code,
        country_name=meta["country_name"],
        researcher_output=researcher_output,
        strategy=args.strategy,
        answer_shape=shape.shape,
        allowed_answers=list(shape.allowed_answers),
    )

    run_id = args.run_id or str(uuid.uuid4())
    # Re-use the Researcher's pair_run_id if available so the rows link.
    pair_run_id = row.get("pair_run_id") or str(uuid.uuid4())

    on_step = make_walkthrough_callback(enabled=args.walkthrough)

    result = run_verifier(
        inp,
        condition_label=args.condition_label,
        on_step=on_step,
    )

    print()
    print(
        f"VERIFIER FINISHED  question={inp.question_id} "
        f"country={inp.country_code}  strategy={inp.strategy}"
    )
    print(f"  Researcher said:   {researcher_output.answer!r} "
          f"(conf={researcher_output.answer_confidence:.2f})")

    if result.output is None:
        print(f"  Outcome:           FAILED  failure_mode={result.failure_mode}")
        print(f"  Notes:             {result.notes}")
    else:
        o = result.output
        print(f"  Verdict:           {o.verdict.upper()}")
        print(f"  Verifier answer:   {o.verifier_answer!r} "
              f"(conf={o.verifier_confidence:.2f})")
        print(f"  Substring check:   {o.substring_check_result}"
              + (f"  [{result.substring_notes}]" if result.substring_notes else ""))
        if o.verdict == "fail":
            rr = (o.rejection_reason or "")[:200]
            print(f"  Rejection reason:  {rr}")
            if o.counter_evidence_quote:
                print(f"  Counter quote:     \"{o.counter_evidence_quote[:120]}\"")
            if o.counter_source_url:
                print(f"  Counter URL:       {o.counter_source_url}")
            if o.suggested_search_query:
                print(f"  Suggested query:   {o.suggested_search_query}")
        if result.notes:
            print(f"  Notes:             {result.notes}")

    print()
    print(f"  Cost receipts (cumulative):")
    print(f"    input_tokens:   {result.cumulative_input_tokens}")
    print(f"    output_tokens:  {result.cumulative_output_tokens}")
    print(f"    wall_clock_ms:  {result.cumulative_wall_clock_ms}")
    if result.cumulative_cost_usd is not None:
        print(f"    estimated_cost: £{result.cumulative_cost_usd * 0.79:.6f}")
    print()

    if args.dry_run:
        print("--dry-run: not writing to SQLite.")
        return

    row_id = save_run(
        result=result,
        inp=inp,
        researcher_db_id=researcher_db_id,
        run_id=run_id,
        pair_run_id=pair_run_id,
        retry_count=0,
        condition_label=args.condition_label,
    )
    print(
        f"Saved phase2_verifier_runs row id={row_id} "
        f"(researcher_run_id={researcher_db_id}, pair_run_id={pair_run_id})"
    )


if __name__ == "__main__":
    main()
