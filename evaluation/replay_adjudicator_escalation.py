#!/usr/bin/env python3
"""EXP-33 / EXP-37 adjudicator-only checker escalation (corrected design).

Supersedes replay_checker_escalation.py, which re-ran the Verifier as well as
the Adjudicator -- wasteful, since it re-litigates a verdict the cheap tier
already reached. Benjy's correction: escalate ONLY the Adjudicator, reuse the
ENTIRE frozen evidence trail (every Researcher attempt, every Verifier
attempt) exactly as the original run produced it, and only pay for a pair
that actually reached adjudication in the source run -- a pair the cheap
Verifier accepted outright had nothing for a stronger checker to catch, so
re-running it teaches nothing and burns tokens for no reason.

  Haiku -> Haiku -> Sonnet: source = exp32_model_haiku/haiku_h45, checker = Sonnet.
  Sonnet -> Sonnet -> Opus: source = exp28_arch_ablation/trio_s5, checker = Opus.

For each eligible pair (source terminal_status in accepted_by_adjudicator /
abstained_adjudicator -- i.e. the Verifier never accepted, forcing the
original Adjudicator call):
  1. Load every Researcher attempt (ordered by retry_count) for that
     pair_run_id -> List[ResearcherOutput], byte-identical to what the
     original Adjudicator saw.
  2. Load every non-null Verifier attempt (ordered by retry_count) for that
     pair_run_id -> List[VerifierOutput], same.
  3. Run ONE fresh Adjudicator call with the escalated model.
  4. Finalise with the same _finalise_after_adjudication helper the
     coordinator itself uses, so the semantics (D37 floor, D44 backstop,
     abstain-on-no-quote) are identical to production.

Cost: exactly one Adjudicator call per eligible pair. No Researcher call, no
Verifier call (so no live web search either) on the escalation side at all.

Durability: writes each result to a JSONL file, flushing after every line
(the killed-processes incident: buffered-but-never-flushed writes looked
like a hang and lost real work when the process was terminated). A crash or
kill here loses at most the one in-flight pair, not the whole run.

  uv run python evaluation/replay_adjudicator_escalation.py --which h_h_s --limit 2   # reachability
  uv run python evaluation/replay_adjudicator_escalation.py --which h_h_s             # full run
  uv run python evaluation/replay_adjudicator_escalation.py --which s_s_o
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env", override=True)

_base = os.environ.get("ANTHROPIC_BASE_URL", "")
if "localhost" not in _base and "127.0.0.1" not in _base:
    sys.exit(f"REFUSING TO RUN: ANTHROPIC_BASE_URL is {_base!r}, not the local proxy.")

from agents.models import AdjudicatorInput, ResearcherOutput, VerifierOutput  # noqa: E402
from agents.adjudicator import run_adjudicator  # noqa: E402
from agents.tools.db import DB_PATH  # noqa: E402
from scripts.run_coordinator import (  # noqa: E402
    COUNTRIES, QUESTIONS_JSON, _finalise_after_adjudication,
)
from agents.tools import answer_shapes  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

ADJUDICATED_STATUSES = ("accepted_by_adjudicator", "abstained_adjudicator")

CONFIGS = {
    "h_h_s": {
        "source_experiment_id": "exp32_model_haiku",
        "source_condition_label": "haiku_h45",
        "target_experiment_id": "exp33_model_tiered",
        "target_condition_label": "tiered_h45_h45_s46_adjonly",
        "checker_model": "claude-sonnet-4-6",
    },
    "s_s_o": {
        "source_experiment_id": "exp28_arch_ablation",
        "source_condition_label": "trio_s5",
        "target_experiment_id": "exp37_model_tiered_opus_check",
        "target_condition_label": "tiered_s46_s46_o48_adjonly",
        "checker_model": "claude-opus-4-8",
        # This worktree's local data/odmi.db is a smaller, stale snapshot
        # of trio_s5 (100 pairs vs the canonical 155 -- worktree DB copies
        # diverge from the main checkout, see CLAUDE.md). trio_s5 predates
        # this worktree and lives complete only in the canonical checkout,
        # so read the frozen source evidence from there, not the local copy.
        "source_db_path": "/Users/benjyb/Desktop/MscProject/data/odmi.db",
    },
}


def _load_questions() -> dict:
    return {q["question_id"]: q for q in json.loads(QUESTIONS_JSON.read_text())}


def _eligible_pairs(con: sqlite3.Connection, source_experiment_id: str,
                     source_condition_label: str) -> list[dict]:
    """One row per pair that reached adjudication in the source run (the
    canonical -- latest -- phase2_final row per pair, deduped)."""
    rows = con.execute(
        """
        WITH canon AS (
          SELECT f.*, r.condition_label, r.pair_run_id AS rc_pair_run_id,
                 ROW_NUMBER() OVER (
                   PARTITION BY r.question_id, r.country_code, r.condition_label
                   ORDER BY f.id DESC
                 ) rn
          FROM phase2_final f
          JOIN phase2_researcher_runs r
            ON r.pair_run_id = f.pair_run_id AND r.experiment_id = f.experiment_id
          WHERE r.experiment_id = ? AND r.condition_label = ?
        )
        SELECT question_id, country_code, pair_run_id, terminal_status, final_answer
        FROM canon
        WHERE rn = 1 AND terminal_status IN (?, ?)
        ORDER BY question_id, country_code
        """,
        (source_experiment_id, source_condition_label, *ADJUDICATED_STATUSES),
    ).fetchall()
    return [
        {"question_id": r[0], "country_code": r[1], "pair_run_id": r[2],
         "source_terminal_status": r[3], "source_final_answer": r[4]}
        for r in rows
    ]


def _load_researcher_outputs(con: sqlite3.Connection, pair_run_id: str,
                              experiment_id: str) -> list[ResearcherOutput]:
    rows = con.execute(
        """SELECT answer, answer_explanation, evidence_quote, source_url,
                  retrieval_confidence, answer_confidence,
                  search_queries_used, fetched_urls, domain_trust_score,
                  language_route_used
           FROM phase2_researcher_runs
           WHERE pair_run_id = ? AND experiment_id = ? AND answer IS NOT NULL
           ORDER BY retry_count ASC""",
        (pair_run_id, experiment_id),
    ).fetchall()
    out = []
    for r in rows:
        out.append(ResearcherOutput(
            answer=r[0], answer_explanation=r[1] or "",
            evidence_quote=r[2] or "(no quote on frozen row)", source_url=r[3],
            retrieval_confidence=r[4] or 0.5, answer_confidence=r[5] or 0.5,
            search_queries_used=json.loads(r[6] or "[]"),
            fetched_urls=json.loads(r[7] or "[]"),
            domain_trust_score=r[8], language_route_used=r[9] or "native",
        ))
    return out


def _load_verifier_outputs(con: sqlite3.Connection, pair_run_id: str,
                            experiment_id: str) -> list[VerifierOutput]:
    rows = con.execute(
        """SELECT verdict, verifier_answer, verifier_confidence,
                  substring_check_result, substring_check_notes,
                  independent_search_queries, independent_evidence,
                  rejection_reason, counter_evidence_quote, counter_source_url,
                  suggested_search_query
           FROM phase2_verifier_runs
           WHERE pair_run_id = ? AND experiment_id = ? AND verdict IS NOT NULL
           ORDER BY retry_count ASC""",
        (pair_run_id, experiment_id),
    ).fetchall()
    out = []
    for r in rows:
        out.append(VerifierOutput(
            verdict=r[0], verifier_answer=r[1], verifier_confidence=r[2],
            substring_check_result=r[3], substring_check_notes=r[4],
            independent_search_queries=json.loads(r[5] or "[]"),
            independent_evidence_snippets=json.loads(r[6] or "[]"),
            rejection_reason=r[7], counter_evidence_quote=r[8],
            counter_source_url=r[9], suggested_search_query=r[10],
        ))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=list(CONFIGS), required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    cfg = CONFIGS[args.which]

    source_db_path = cfg.get("source_db_path", DB_PATH)
    con = sqlite3.connect(source_db_path)
    pairs = _eligible_pairs(con, cfg["source_experiment_id"], cfg["source_condition_label"])
    if args.limit:
        pairs = pairs[: args.limit]
    print(f"{args.which}: {len(pairs)} pairs reached adjudication in "
          f"{cfg['source_experiment_id']}/{cfg['source_condition_label']} "
          f"(source db: {source_db_path}) "
          f"(escalating Adjudicator only, to {cfg['checker_model']})", flush=True)

    questions = _load_questions()
    out_path = RESULTS_DIR / f"{args.which}_adjonly_replay.jsonl"
    total_cost = 0.0
    with out_path.open("w", buffering=1) as f:  # line-buffered: durable per pair
        for i, p in enumerate(pairs, 1):
            q = questions[p["question_id"]]
            country = COUNTRIES[p["country_code"].upper()]
            shape = answer_shapes.load_question_shape(p["question_id"])

            researcher_outputs = _load_researcher_outputs(
                con, p["pair_run_id"], cfg["source_experiment_id"])
            verifier_outputs = _load_verifier_outputs(
                con, p["pair_run_id"], cfg["source_experiment_id"])
            if not researcher_outputs or not verifier_outputs:
                result = {**p, "checker_final_answer": None,
                          "checker_terminal_status": "skipped_missing_frozen_evidence",
                          "cost_usd": 0.0}
                f.write(json.dumps(result) + "\n")
                f.flush()
                print(f"  [{i}/{len(pairs)}] {p['question_id']}/{p['country_code']} "
                      f"SKIPPED (missing frozen researcher/verifier rows)", flush=True)
                continue

            adj_inp = AdjudicatorInput(
                question_id=p["question_id"], question_text=q["question_text"],
                country_code=p["country_code"], country_name=country["country_name"],
                researcher_outputs=researcher_outputs,
                verifier_outputs=verifier_outputs,
                answer_shape=shape.shape, allowed_answers=list(shape.allowed_answers),
            )
            adj_result = run_adjudicator(adj_inp, model=cfg["checker_model"])
            status, final = _finalise_after_adjudication(adj_result.output, researcher_outputs)
            cost = adj_result.cumulative_cost_usd or 0.0
            total_cost += cost

            result = {
                **p,
                "checker_terminal_status": status,
                "checker_final_answer": final.answer if final else None,
                "cost_usd": cost,
                "input_tokens": adj_result.cumulative_input_tokens,
                "output_tokens": adj_result.cumulative_output_tokens,
                "target_experiment_id": cfg["target_experiment_id"],
                "target_condition_label": cfg["target_condition_label"],
            }
            f.write(json.dumps(result) + "\n")
            f.flush()
            print(f"  [{i}/{len(pairs)}] {p['question_id']}/{p['country_code']} "
                  f"source={p['source_final_answer']} -> checker={result['checker_final_answer']} "
                  f"£{cost * 0.79:.4f}", flush=True)

    print(f"\nDone. {len(pairs)} pairs, total est cost ${total_cost:.2f} "
          f"(£{total_cost * 0.79:.2f}). Results: {out_path}", flush=True)


if __name__ == "__main__":
    main()
