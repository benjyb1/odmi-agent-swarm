"""Run one Coordinator pass on a single (question, country) pair.

The Coordinator is the per-pair orchestrator: Researcher → Verifier
(→ Adjudicator on retry exhaustion). It owns the retry counter, writes
to subtrio_status at each stage transition, and writes one row each to
the phase2 result tables on terminal states.

Usage:
    uv run python scripts/run_coordinator.py P1 FR
    uv run python scripts/run_coordinator.py P1 FR --strategy verifier-negation
    uv run python scripts/run_coordinator.py P1 FR \\
        --researcher-model claude-haiku-4-5-20251001 \\
        --verifier-model claude-sonnet-4-6 \\
        --adjudicator-model claude-opus-4-6 \\
        --subtrio-id abc-123 --batch-id batch-456 \\
        --max-retries 3

Spec deviation note
-------------------
AGENT_DESIGN.md §5 specifies a LangGraph StateGraph. This implementation
uses a plain Python state machine instead. Reasons: the retry-loop is
linear, error handling is more straightforward to debug without a graph
runtime, and the dashboard cares about explicit stage transitions
which a flat Python function expresses directly. The behaviour matches
the graph spec; only the implementation idiom differs.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.adjudicator import run_adjudicator
from agents.errors import EXIT_CODE_RATE_LIMITED, RateLimitedShutdown
from agents.tools import answer_shapes
from agents.models import (
    AdjudicatorInput,
    AdjudicatorOutput,
    ResearcherInput,
    ResearcherOutput,
    VerifierFeedback,
    VerifierInput,
    VerifierOutput,
    VerifierStrategy,
)
from agents.researcher import ResearcherRunResult, run_researcher
from agents.tools.db import DB_PATH, connect
from agents.verifier import VerifierRunResult, run_verifier

QUESTIONS_JSON = REPO_ROOT / "data" / "questions" / "odmi_2025_questions.json"

COUNTRIES = {
    "FR": {"country_name": "France",   "country_language": "fr",
           "portal_url": "https://www.data.gouv.fr/"},
    "RO": {"country_name": "Romania",  "country_language": "ro",
           "portal_url": "https://data.gov.ro/"},
    "DE": {"country_name": "Germany",  "country_language": "de",
           "portal_url": "https://www.govdata.de/"},
    "NL": {"country_name": "Netherlands", "country_language": "nl",
           "portal_url": "https://data.overheid.nl/"},
    "HU": {"country_name": "Hungary",  "country_language": "hu",
           "portal_url": "https://data.gov.hu/"},
    "EE": {"country_name": "Estonia",  "country_language": "et",
           "portal_url": "https://avaandmed.eesti.ee/"},
    # Malta: English is an official language, so its open-data estate is
    # largely in English and a poor result is the pipeline's doing, not a
    # language artefact. This is why EXP-6 retargets its primary should_fail
    # class here (SPEC D38, R4). Binary questions route through web search,
    # so portal_url is not on the critical path for the Malta run.
    "MT": {"country_name": "Malta",    "country_language": "en",
           "portal_url": "https://data.gov.mt/"},
}


# ============================================================
# Dry-run and walkthrough flags
# ============================================================
#
# `_dry_run` is a module-level switch set by `coordinate()` at entry.
# When True, every DB write helper short-circuits — no row touches
# subtrio_status, phase2_researcher_runs, phase2_verifier_runs,
# phase2_adjudications, or phase2_final. `claude_usage_log` is NOT
# gated because the underlying tokens are billed regardless; suppressing
# the log would make the rolling-window budget under-count real spend.
#
# `_walkthrough` is set the same way. When True, the coordinator prints
# every stage transition and forwarded on_step event to stdout in a
# readable format. Off by default so dashboard-spawned subprocesses
# don't flood their batch log.

_dry_run: bool = False
_walkthrough: bool = False
_current_experiment_id: Optional[str] = None
_current_condition_label: str = "baseline"


def _print_step(prefix: str, event: str, payload: dict) -> None:
    """Verbose stage logger used when --walkthrough is on."""
    if not _walkthrough:
        return
    parts = [f"  [{prefix}]", event]
    if payload:
        # Trim large payload values for readability.
        for k, v in payload.items():
            if isinstance(v, str) and len(v) > 100:
                v = v[:97] + "..."
            if isinstance(v, list) and len(v) > 5:
                v = f"[{len(v)} items]"
            parts.append(f"{k}={v}")
    print(" ".join(str(p) for p in parts), flush=True)


# ============================================================
# subtrio_status helpers
# ============================================================

def _iso_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _upsert_subtrio_status(
    *,
    subtrio_id: str,
    batch_id: str,
    question_id: str,
    country_code: str,
    stage: str,
    substage: Optional[str] = None,
    retry_count: Optional[int] = None,
    final_verdict: Optional[str] = None,
    cumulative_cost_usd: Optional[float] = None,
    last_message: Optional[str] = None,
    researcher_model: Optional[str] = None,
    verifier_model: Optional[str] = None,
    adjudicator_model: Optional[str] = None,
    verifier_strategy: Optional[str] = None,
    final_failure_reason: Optional[str] = None,
    experiment_id: Optional[str] = None,
    ended: bool = False,
) -> None:
    """Insert or update one subtrio_status row.

    Best-effort; database errors are logged to stderr but do not raise
    because that would mask the real failure in the agent flow.
    Skipped entirely when --dry-run is set.
    """
    if _dry_run:
        _print_step("subtrio_status (dry-run skip)", stage, {"substage": substage})
        return
    now = _iso_now()
    try:
        with connect() as conn:
            existing = conn.execute(
                "SELECT subtrio_id, started_at FROM subtrio_status WHERE subtrio_id = ?",
                (subtrio_id,),
            ).fetchone()

            if existing is None:
                conn.execute(
                    """INSERT INTO subtrio_status (
                        subtrio_id, batch_id, question_id, country_code,
                        stage, substage, retry_count, started_at, updated_at,
                        cumulative_cost_usd, last_message, process_pid,
                        researcher_model, verifier_model, adjudicator_model,
                        verifier_strategy, experiment_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        subtrio_id, batch_id, question_id, country_code,
                        stage, substage, retry_count or 0, now, now,
                        cumulative_cost_usd, last_message, os.getpid(),
                        researcher_model, verifier_model, adjudicator_model,
                        verifier_strategy, experiment_id,
                    ),
                )
            else:
                # Build a dynamic update so we only touch provided fields.
                updates: List[str] = ["updated_at = ?"]
                params: List = [now]
                for name, val in [
                    ("stage", stage),
                    ("substage", substage),
                    ("retry_count", retry_count),
                    ("final_verdict", final_verdict),
                    ("cumulative_cost_usd", cumulative_cost_usd),
                    ("last_message", last_message),
                    ("researcher_model", researcher_model),
                    ("verifier_model", verifier_model),
                    ("adjudicator_model", adjudicator_model),
                    ("verifier_strategy", verifier_strategy),
                    ("final_failure_reason", final_failure_reason),
                ]:
                    if val is not None:
                        updates.append(f"{name} = ?")
                        params.append(val)
                if ended:
                    updates.append("ended_at = ?")
                    params.append(now)
                params.append(subtrio_id)
                conn.execute(
                    f"UPDATE subtrio_status SET {', '.join(updates)} "
                    f"WHERE subtrio_id = ?",
                    params,
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[coordinator] subtrio_status write failed: {exc}", file=sys.stderr)


# ============================================================
# Question / input loaders
# ============================================================

def _load_question(question_id: str) -> dict:
    if not QUESTIONS_JSON.exists():
        sys.exit(f"Question bank not found at {QUESTIONS_JSON}.")
    questions = json.loads(QUESTIONS_JSON.read_text())
    by_id = {q["question_id"]: q for q in questions}
    if question_id not in by_id:
        sys.exit(
            f"Question {question_id!r} not found. "
            f"Try one of {list(by_id)[:6]}..."
        )
    return by_id[question_id]


def _build_researcher_input(
    question_id: str,
    country_code: str,
    feedback: Optional[VerifierFeedback] = None,
    previous_search_queries: Optional[List[str]] = None,
) -> ResearcherInput:
    q = _load_question(question_id)
    meta = COUNTRIES.get(country_code.upper())
    if meta is None:
        sys.exit(f"Country {country_code!r} not configured. Add to COUNTRIES.")

    # D28: pull the per-question answer shape and allowed labels from
    # the DB. The classification was done once by
    # scripts/migrate_d28_shapes.py and is reused on every call.
    shape = answer_shapes.load_question_shape(q["question_id"])

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
        verifier_feedback=feedback,
        answer_shape=shape.shape,
        allowed_answers=list(shape.allowed_answers),
        previous_search_queries=list(previous_search_queries or []),
    )


# ============================================================
# Adjudicator finalisation helper (Change 1)
# ============================================================

def _finalise_after_adjudication(
    adj_output: Optional["AdjudicatorOutput"],
    researcher_outputs: List[ResearcherOutput],
) -> tuple[str, ResearcherOutput]:
    """Return (final_status, chosen_output) after the Adjudicator has run.

    For all resolved verdicts (researcher_correct / verifier_correct /
    neither) the Adjudicator's own authoritative fields are used — its
    answer, reasoning, source URL, and evidence quote. The last
    researcher output is only kept on an escalation.

    Args:
        adj_output: The AdjudicatorOutput, or None if the agent failed.
        researcher_outputs: Every ResearcherOutput from all attempts.
            The last element is used as the fallback for escalations.

    Returns:
        A (status, ResearcherOutput) tuple the caller can pass straight
        to _save_final_row.
    """
    last_researcher_output = researcher_outputs[-1]

    if adj_output is None or adj_output.adjudicator_verdict == "escalate_human":
        return ("escalated_adjudicator", last_researcher_output)

    # All three resolved verdicts share the same finalisation logic: use
    # the Adjudicator's authoritative answer and evidence, not the raw
    # researcher or verifier fields.
    chosen = ResearcherOutput(
        answer=adj_output.adjudicator_answer or "inconclusive",
        answer_explanation=adj_output.adjudicator_reasoning[:300],
        evidence_quote=(
            adj_output.chosen_evidence_quote
            or "(adjudicator did not provide quote)"
        ),
        source_url=str(
            adj_output.chosen_source_url or last_researcher_output.source_url
        ),
        retrieval_confidence=0.7,
        answer_confidence=adj_output.adjudicator_confidence,
    )
    return ("accepted_by_adjudicator", chosen)


# ============================================================
# DB write helpers (reuse the existing per-agent write paths)
# ============================================================

def _save_researcher_row(
    *, result: ResearcherRunResult, inp: ResearcherInput,
    run_id: str, pair_run_id: str, retry_count: int,
    condition_label: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> int:
    condition_label = condition_label or _current_condition_label
    experiment_id = experiment_id if experiment_id is not None else _current_experiment_id
    if _dry_run:
        _print_step("phase2_researcher_runs (dry-run skip)", "insert",
                    {"answer": result.output.answer if result.output else None})
        return -1
    o = result.output
    main = result.main_usage
    with connect() as conn:
        search_snippets_json = json.dumps([
            {
                "url": r.url,
                "snippet": r.snippet,
                "title": r.title,
                "provider": r.provider,
            }
            for r in result.search_results
        ]) if result.search_results else None
        cur = conn.execute(
            """INSERT INTO phase2_researcher_runs (
                run_id, pair_run_id, question_id, country_code, retry_count,
                answer, answer_explanation, evidence_quote, source_url,
                retrieval_confidence, answer_confidence,
                search_queries_used, fetched_urls,
                search_provider_calls,
                search_snippets,
                domain_trust_score, language_route_used, notes,
                failure_mode,
                input_tokens, output_tokens, wall_clock_ms,
                estimated_cost_usd, condition_label,
                prompt_version_id, model_version, raw_response,
                experiment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, pair_run_id, inp.question_id, inp.country_code, retry_count,
                o.answer if o else None,
                o.answer_explanation if o else None,
                o.evidence_quote if o else None,
                str(o.source_url) if o else None,
                o.retrieval_confidence if o else None,
                o.answer_confidence if o else None,
                json.dumps(result.search_queries_used),
                json.dumps(result.fetched_urls),
                json.dumps(result.search_provider_calls)
                    if result.search_provider_calls else None,
                search_snippets_json,
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
                experiment_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _save_verifier_row(
    *, result: VerifierRunResult, inp: VerifierInput,
    researcher_db_id: int,
    run_id: str, pair_run_id: str, retry_count: int,
    condition_label: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> int:
    condition_label = condition_label or _current_condition_label
    experiment_id = experiment_id if experiment_id is not None else _current_experiment_id
    if _dry_run:
        _print_step("phase2_verifier_runs (dry-run skip)", "insert",
                    {"verdict": result.output.verdict if result.output else None})
        return -1
    o = result.output
    main = result.main_usage
    with connect() as conn:
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
                prompt_version_id, model_version, raw_response,
                experiment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                experiment_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _save_adjudication_row(
    *, result, inp: AdjudicatorInput,
    run_id: str, pair_run_id: str,
    experiment_id: Optional[str] = None,
) -> int:
    experiment_id = experiment_id if experiment_id is not None else _current_experiment_id
    if _dry_run:
        _print_step("phase2_adjudications (dry-run skip)", "insert",
                    {"verdict": result.output.adjudicator_verdict if result.output else None})
        return -1
    o = result.output
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO phase2_adjudications (
                run_id, pair_run_id, question_id, country_code,
                adjudicator_verdict, adjudicator_answer, adjudicator_confidence,
                adjudicator_reasoning, chosen_source_url, chosen_evidence_quote,
                failure_mode,
                input_tokens, output_tokens, wall_clock_ms,
                estimated_cost_usd,
                prompt_version_id, model_version, raw_response,
                experiment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, pair_run_id, inp.question_id, inp.country_code,
                o.adjudicator_verdict if o else None,
                o.adjudicator_answer if o else None,
                o.adjudicator_confidence if o else None,
                o.adjudicator_reasoning if o else (result.notes or "(no output)"),
                str(o.chosen_source_url) if o and o.chosen_source_url else None,
                o.chosen_evidence_quote if o else None,
                result.failure_mode,
                result.cumulative_input_tokens,
                result.cumulative_output_tokens,
                result.cumulative_wall_clock_ms,
                result.cumulative_cost_usd,
                result.usage.prompt_version_id if result.usage else None,
                result.usage.model_version if result.usage else "unknown",
                result.usage.raw_response if result.usage else None,
                experiment_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _save_final_row(
    *, run_id: str, pair_run_id: str,
    inp: ResearcherInput,
    final_output: Optional[ResearcherOutput],
    terminal_status: str,
    retry_count: int,
    adjudicator_involved: bool,
    captcha_escalated: bool,
    cumulative_input_tokens: int,
    cumulative_output_tokens: int,
    cumulative_wall_clock_ms: int,
    cumulative_cost_usd: Optional[float],
    final_failure_reason: Optional[str],
    experiment_id: Optional[str] = None,
) -> int:
    experiment_id = experiment_id if experiment_id is not None else _current_experiment_id
    if _dry_run:
        _print_step("phase2_final (dry-run skip)", "insert",
                    {"status": terminal_status,
                     "answer": final_output.answer if final_output else None})
        return -1
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO phase2_final (
                run_id, pair_run_id, question_id, country_code,
                terminal_status,
                final_answer, final_answer_explanation,
                final_evidence_quote, final_source_url,
                final_retrieval_confidence, final_answer_confidence,
                retry_count, adjudicator_involved, captcha_escalated,
                cumulative_input_tokens, cumulative_output_tokens,
                cumulative_wall_clock_ms, cumulative_cost_usd,
                final_failure_reason,
                experiment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, pair_run_id, inp.question_id, inp.country_code,
                terminal_status,
                final_output.answer if final_output else None,
                final_output.answer_explanation if final_output else None,
                final_output.evidence_quote if final_output else None,
                str(final_output.source_url) if final_output else None,
                final_output.retrieval_confidence if final_output else None,
                final_output.answer_confidence if final_output else None,
                retry_count, 1 if adjudicator_involved else 0,
                1 if captcha_escalated else 0,
                cumulative_input_tokens, cumulative_output_tokens,
                cumulative_wall_clock_ms, cumulative_cost_usd,
                final_failure_reason,
                experiment_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


# ============================================================
# The Coordinator's state machine
# ============================================================

def _find_resumable_researcher(
    question_id: str, country_code: str,
    *, max_age_minutes: int = 60,
) -> Optional[dict]:
    """Look for a Researcher row from a recent incomplete subtrio.

    Returns the row dict (or None) for the most recent
    `phase2_researcher_runs` entry whose subtrio:
      - never wrote a `phase2_final` row, and
      - is no longer in an active stage (orphaned, interrupted, or
        merely stale by more than `max_age_minutes`).

    The freshness window protects us from reusing an answer that was
    correct yesterday but might have moved on.
    """
    cutoff = (
        datetime.utcnow() - timedelta(minutes=max_age_minutes)
    ).isoformat(timespec="seconds") + "Z"
    with connect() as conn:
        row = conn.execute(
            """
            SELECT r.id, r.pair_run_id, r.retry_count,
                   r.answer, r.answer_explanation, r.evidence_quote,
                   r.source_url, r.retrieval_confidence, r.answer_confidence,
                   r.search_queries_used, r.fetched_urls,
                   r.domain_trust_score, r.language_route_used, r.notes,
                   r.created_at,
                   s.subtrio_id AS subtrio_id, s.stage AS prior_stage
            FROM phase2_researcher_runs r
            JOIN subtrio_status s ON s.subtrio_id = r.pair_run_id
            LEFT JOIN phase2_final f ON f.pair_run_id = r.pair_run_id
            WHERE r.question_id = ? AND r.country_code = ?
              AND r.retry_count = 0
              AND r.answer IS NOT NULL
              AND f.id IS NULL
              AND (s.stage IN ('orphaned', 'interrupted_rate_limit', 'failed')
                   OR (s.updated_at IS NOT NULL
                       AND s.updated_at < ?))
            ORDER BY r.id DESC
            LIMIT 1
            """,
            (question_id, country_code, cutoff),
        ).fetchone()
    if row is None:
        return None
    return dict(row) if hasattr(row, "keys") else {
        k: row[i] for i, k in enumerate([
            "id", "pair_run_id", "retry_count",
            "answer", "answer_explanation", "evidence_quote",
            "source_url", "retrieval_confidence", "answer_confidence",
            "search_queries_used", "fetched_urls",
            "domain_trust_score", "language_route_used", "notes",
            "created_at", "subtrio_id", "prior_stage",
        ])
    }


def _mark_superseded(
    *, prior_subtrio_id: str, by_subtrio_id: str,
) -> None:
    """Mark a prior subtrio_status row as `superseded` so the audit
    trail records that a later subtrio reused its Researcher result."""
    if _dry_run:
        return
    note = f"superseded by {by_subtrio_id[:8]} (resume)"
    with connect() as conn:
        conn.execute(
            """UPDATE subtrio_status
               SET stage = 'superseded',
                   ended_at = COALESCE(ended_at, ?),
                   updated_at = ?,
                   last_message = ?
               WHERE subtrio_id = ?""",
            (_iso_now(), _iso_now(), note, prior_subtrio_id),
        )
        conn.commit()


def _researcher_output_from_row(row: dict) -> ResearcherOutput:
    """Rebuild a ResearcherOutput from a phase2_researcher_runs row.

    Used when resuming a partially-completed subtrio: we never re-call
    the Researcher; we feed the prior row's data directly to the
    Verifier.
    """
    return ResearcherOutput(
        answer=row["answer"],
        answer_explanation=row["answer_explanation"] or "",
        evidence_quote=row["evidence_quote"] or "",
        source_url=row["source_url"],
        retrieval_confidence=row["retrieval_confidence"] or 0.0,
        answer_confidence=row["answer_confidence"] or 0.0,
        search_queries_used=(
            json.loads(row["search_queries_used"])
            if row["search_queries_used"] else []
        ),
        fetched_urls=(
            json.loads(row["fetched_urls"])
            if row["fetched_urls"] else []
        ),
        domain_trust_score=row["domain_trust_score"],
        language_route_used=row["language_route_used"] or "native",
        notes=row["notes"],
    )


def _is_abstention(answer: Optional[str]) -> bool:
    """True if the answer is the `inconclusive` abstention literal.

    `not_applicable` is a valid determination and is NOT an abstention.
    """
    return bool(answer) and answer.strip().lower() == "inconclusive"


# Minimum answer confidence required to commit an answer that the Verifier
# passed. A Verifier pass on a low-confidence answer is a likely false
# positive (confident-wrong), so the coordinator retries instead.
COMMIT_CONFIDENCE_FLOOR = 0.65


def _should_accept_verifier_pass(
    verdict: str,
    answer: Optional[str],
    answer_confidence: Optional[float],
) -> bool:
    """A Verifier `pass` finalises an answer only if it is a real label
    (not an abstention) and its confidence clears the commit floor."""
    return (
        verdict == "pass"
        and not _is_abstention(answer)
        and (answer_confidence or 0.0) >= COMMIT_CONFIDENCE_FLOOR
    )


def coordinate(
    *,
    question_id: str,
    country_code: str,
    strategy: VerifierStrategy = "verifier-disprove",
    researcher_model: Optional[str] = None,
    verifier_model: Optional[str] = None,
    adjudicator_model: Optional[str] = None,
    max_retries: int = 3,
    provider: str = "auto",
    max_results_per_query: int = 5,
    num_queries: Optional[int] = None,
    no_cache: bool = False,
    subtrio_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    condition_label: str = "baseline",
    dry_run: bool = False,
    walkthrough: bool = False,
) -> tuple[str, Optional[ResearcherOutput]]:
    """Run one pair end-to-end.

    Returns (terminal_status, final_output).

    Raises RateLimitedShutdown if any LLM call hits a 429; the caller
    (main()) catches it, marks the subtrio as interrupted_rate_limit,
    and exits with code 42.
    """
    global _dry_run, _walkthrough, _current_experiment_id, _current_condition_label
    _dry_run = dry_run
    _walkthrough = walkthrough
    _current_experiment_id = experiment_id
    _current_condition_label = condition_label

    # Cold-cache mode (EXP-2). Disable cache reads for the whole run so the
    # DIY pipeline recomputes every SERP, fetch, and snippet-pick live. This
    # keeps search cost comparable across conditions dispatched back to back:
    # a later condition never reads a hit a previous one wrote. Set once here,
    # before any agent call, because each pair runs in its own subprocess.
    from agents.tools import search_cache
    search_cache.set_read_disabled(no_cache)

    subtrio_id = subtrio_id or str(uuid.uuid4())
    batch_id = batch_id or str(uuid.uuid4())
    run_id = batch_id   # one batch_id per coordinator invocation maps to run_id
    pair_run_id = subtrio_id

    dr_tag = " [DRY-RUN]" if dry_run else ""
    print(f"\n>>> COORDINATOR START{dr_tag} subtrio={subtrio_id[:8]} "
          f"{question_id}/{country_code}", flush=True)
    if walkthrough:
        print(f"    strategy={strategy} retries={max_retries} "
              f"R={researcher_model or 'default'} V={verifier_model or 'default'} "
              f"A={adjudicator_model or 'default'}", flush=True)

    _upsert_subtrio_status(
        subtrio_id=subtrio_id, batch_id=batch_id,
        question_id=question_id, country_code=country_code,
        stage="queued", retry_count=0,
        researcher_model=researcher_model,
        verifier_model=verifier_model,
        adjudicator_model=adjudicator_model,
        verifier_strategy=strategy,
        experiment_id=experiment_id,
        last_message="coordinator started",
    )

    researcher_outputs: List[ResearcherOutput] = []
    verifier_outputs: List[VerifierOutput] = []
    feedback: Optional[VerifierFeedback] = None
    # Accumulates every query the Researcher has tried across all
    # attempts so subsequent retries can diverge (Change 2).
    accumulated_search_queries: List[str] = []
    cumulative_tokens_in = 0
    cumulative_tokens_out = 0
    cumulative_wall = 0
    cumulative_cost = 0.0
    last_researcher_db_id: Optional[int] = None
    last_researcher_output: Optional[ResearcherOutput] = None
    retry_count = 0

    # Resume check: if a prior subtrio for this pair already wrote a
    # Researcher row (retry_count=0) and then died before finalising,
    # reuse that row instead of paying for a fresh Researcher call.
    resumable = _find_resumable_researcher(question_id, country_code)
    if resumable:
        _mark_superseded(
            prior_subtrio_id=resumable["subtrio_id"],
            by_subtrio_id=subtrio_id,
        )
        last_researcher_db_id = int(resumable["id"])
        last_researcher_output = _researcher_output_from_row(resumable)
        researcher_outputs.append(last_researcher_output)
        print(
            f"  R1 (resumed from subtrio={resumable['subtrio_id'][:8]}): "
            f"{last_researcher_output.answer} "
            f"({last_researcher_output.answer_confidence:.2f}) — "
            f"skipping Researcher call",
            flush=True,
        )

    for attempt in range(max_retries + 1):
        retry_count = attempt

        # --- Researcher stage ---
        if attempt == 0 and resumable is not None:
            # Resume path: a prior incomplete subtrio for this pair
            # already produced a Researcher row. `last_researcher_*`
            # were populated just before the retry loop; we just need
            # an `r_inp` for the Verifier-input construction below and
            # a stage transition for visibility. No Researcher call.
            r_inp = _build_researcher_input(
                question_id, country_code, feedback,
                previous_search_queries=accumulated_search_queries,
            )
            _upsert_subtrio_status(
                subtrio_id=subtrio_id, batch_id=batch_id,
                question_id=question_id, country_code=country_code,
                stage="researching", substage="resumed",
                retry_count=retry_count,
                last_message=(
                    f"resumed from subtrio "
                    f"{resumable['subtrio_id'][:8]}"
                ),
            )
        else:
            _upsert_subtrio_status(
                subtrio_id=subtrio_id, batch_id=batch_id,
                question_id=question_id, country_code=country_code,
                stage="researching", substage="search",
                retry_count=retry_count,
                last_message=f"researcher attempt {attempt + 1}",
            )
            r_inp = _build_researcher_input(
                question_id, country_code, feedback,
                previous_search_queries=accumulated_search_queries,
            )

            def _r_step(e, p, _att=attempt):
                _print_step(f"R{_att + 1}", e, p)
                if e in ("query_gen_start", "search_start", "main_call_start", "validation_start"):
                    _upsert_subtrio_status(
                        subtrio_id=subtrio_id, batch_id=batch_id,
                        question_id=question_id, country_code=country_code,
                        stage="researching", substage=e,
                        last_message=f"R{_att + 1} · {e}",
                    )

            r_result = run_researcher(
                r_inp, subtrio_id=subtrio_id, on_step=_r_step,
                provider=provider, max_results_per_query=max_results_per_query,
                num_queries=num_queries,
            )
            # Accumulate the queries used so the next attempt can diverge.
            accumulated_search_queries.extend(r_result.search_queries_used)
            cumulative_tokens_in += r_result.cumulative_input_tokens
            cumulative_tokens_out += r_result.cumulative_output_tokens
            cumulative_wall += r_result.cumulative_wall_clock_ms
            if r_result.cumulative_cost_usd:
                cumulative_cost += r_result.cumulative_cost_usd

            if r_result.output is None:
                # Researcher failed unrecoverably; treat as Verifier fail and retry
                print(f"  Researcher failed: {r_result.failure_mode}", flush=True)
                if attempt == max_retries:
                    # Save what we can and bail.
                    final_status = "agent_failure"
                    _upsert_subtrio_status(
                        subtrio_id=subtrio_id, batch_id=batch_id,
                        question_id=question_id, country_code=country_code,
                        stage="failed", final_verdict=final_status,
                        cumulative_cost_usd=cumulative_cost,
                        last_message=f"researcher failed: {r_result.failure_mode}",
                        final_failure_reason=r_result.failure_mode,
                        ended=True,
                    )
                    _save_final_row(
                        run_id=run_id, pair_run_id=pair_run_id, inp=r_inp,
                        final_output=None, terminal_status=final_status,
                        retry_count=retry_count, adjudicator_involved=False,
                        captcha_escalated=False,
                        cumulative_input_tokens=cumulative_tokens_in,
                        cumulative_output_tokens=cumulative_tokens_out,
                        cumulative_wall_clock_ms=cumulative_wall,
                        cumulative_cost_usd=cumulative_cost,
                        final_failure_reason=r_result.failure_mode,
                    )
                    return final_status, None
                feedback = VerifierFeedback(
                    rejection_reason=f"researcher failure: {r_result.failure_mode}",
                )
                continue

            researcher_outputs.append(r_result.output)
            last_researcher_output = r_result.output
            last_researcher_db_id = _save_researcher_row(
                result=r_result, inp=r_inp,
                run_id=run_id, pair_run_id=pair_run_id, retry_count=retry_count,
            )
            print(f"  R{attempt+1}: {r_result.output.answer} "
                  f"({r_result.output.answer_confidence:.2f}) "
                  f"£{(r_result.cumulative_cost_usd or 0) * 0.79:.4f}", flush=True)

        # An `inconclusive` answer is an abstention, not a result. Do not
        # let it run the Verifier or terminate the loop. Retry (the
        # accumulated queries already diverge the search) with an
        # abstention note, until the retry budget is spent. On the final
        # attempt fall through so the Verifier still runs (feeding the
        # Adjudicator) but the accept-guard below refuses to accept it.
        if _is_abstention(r_result.output.answer) and attempt < max_retries:
            feedback = VerifierFeedback(
                rejection_reason=(
                    "The Researcher returned `inconclusive`, which is an "
                    "abstention, not an answer. Search differently and commit "
                    "to a label from the allowed set if the evidence supports "
                    "one."
                ),
            )
            print(f"  R{attempt+1} inconclusive -> abstention, retrying",
                  flush=True)
            continue

        # --- Verifier stage ---
        _upsert_subtrio_status(
            subtrio_id=subtrio_id, batch_id=batch_id,
            question_id=question_id, country_code=country_code,
            stage="verifying", substage="substring_check",
            retry_count=retry_count,
            cumulative_cost_usd=cumulative_cost,
            last_message=f"verifier attempt {attempt + 1} starting",
        )
        v_inp = VerifierInput(
            question_id=question_id,
            question_text=r_inp.question_text,
            country_code=country_code,
            country_name=r_inp.country_name,
            researcher_output=last_researcher_output,
            strategy=strategy,
            answer_shape=r_inp.answer_shape,
            allowed_answers=list(r_inp.allowed_answers),
            researcher_snippets=[r.snippet for r in r_result.search_results],
        )
        def _v_step(e, p, _att=attempt):
            _print_step(f"V{_att + 1}", e, p)
            if e in ("substring_check_start", "query_gen_start",
                     "search_start", "main_call_start"):
                _upsert_subtrio_status(
                    subtrio_id=subtrio_id, batch_id=batch_id,
                    question_id=question_id, country_code=country_code,
                    stage="verifying", substage=e,
                    last_message=f"V{_att + 1} · {e}",
                )

        v_result = run_verifier(
            v_inp, subtrio_id=subtrio_id, on_step=_v_step,
            provider=provider, max_results_per_query=max_results_per_query,
            num_queries=num_queries,
        )
        cumulative_tokens_in += v_result.cumulative_input_tokens
        cumulative_tokens_out += v_result.cumulative_output_tokens
        cumulative_wall += v_result.cumulative_wall_clock_ms
        if v_result.cumulative_cost_usd:
            cumulative_cost += v_result.cumulative_cost_usd

        if v_result.output is None:
            print(f"  Verifier failed: {v_result.failure_mode}", flush=True)
            verifier_outputs.append(None)  # type: ignore
            if attempt == max_retries:
                final_status = "agent_failure"
                _upsert_subtrio_status(
                    subtrio_id=subtrio_id, batch_id=batch_id,
                    question_id=question_id, country_code=country_code,
                    stage="failed", final_verdict=final_status,
                    cumulative_cost_usd=cumulative_cost,
                    final_failure_reason=v_result.failure_mode,
                    last_message=f"verifier failed: {v_result.failure_mode}",
                    ended=True,
                )
                _save_final_row(
                    run_id=run_id, pair_run_id=pair_run_id, inp=r_inp,
                    final_output=last_researcher_output,
                    terminal_status=final_status,
                    retry_count=retry_count, adjudicator_involved=False,
                    captcha_escalated=False,
                    cumulative_input_tokens=cumulative_tokens_in,
                    cumulative_output_tokens=cumulative_tokens_out,
                    cumulative_wall_clock_ms=cumulative_wall,
                    cumulative_cost_usd=cumulative_cost,
                    final_failure_reason=v_result.failure_mode,
                )
                return final_status, last_researcher_output
            feedback = VerifierFeedback(
                rejection_reason=f"verifier failure: {v_result.failure_mode}",
            )
            continue

        verifier_outputs.append(v_result.output)
        _save_verifier_row(
            result=v_result, inp=v_inp,
            researcher_db_id=last_researcher_db_id,
            run_id=run_id, pair_run_id=pair_run_id, retry_count=retry_count,
        )

        print(f"  V{attempt+1}: {v_result.output.verdict} "
              f"({v_result.output.verifier_confidence:.2f}) "
              f"£{(v_result.cumulative_cost_usd or 0) * 0.79:.4f}", flush=True)

        # --- Verdict branching ---
        if _should_accept_verifier_pass(
            v_result.output.verdict,
            last_researcher_output.answer,
            last_researcher_output.answer_confidence,
        ):
            final_status = "accepted_by_verifier"
            _upsert_subtrio_status(
                subtrio_id=subtrio_id, batch_id=batch_id,
                question_id=question_id, country_code=country_code,
                stage="done", final_verdict=final_status,
                cumulative_cost_usd=cumulative_cost,
                last_message="verifier passed",
                ended=True,
            )
            _save_final_row(
                run_id=run_id, pair_run_id=pair_run_id, inp=r_inp,
                final_output=r_result.output, terminal_status=final_status,
                retry_count=retry_count, adjudicator_involved=False,
                captcha_escalated=False,
                cumulative_input_tokens=cumulative_tokens_in,
                cumulative_output_tokens=cumulative_tokens_out,
                cumulative_wall_clock_ms=cumulative_wall,
                cumulative_cost_usd=cumulative_cost,
                final_failure_reason=None,
            )
            return final_status, r_result.output

        # Verifier did not accept. Either retry or escalate to Adjudicator.
        if attempt < max_retries:
            # If the Verifier passed but confidence was sub-floor, the
            # rejection_reason from the Verifier would be misleading (it
            # said "pass"). Use a clearer message so the Researcher knows
            # exactly what to improve.
            _conf = last_researcher_output.answer_confidence
            if (
                v_result.output.verdict == "pass"
                and not _is_abstention(last_researcher_output.answer)
                and (_conf or 0.0) < COMMIT_CONFIDENCE_FLOOR
            ):
                _rejection_reason = (
                    f"The answer was accepted by the Verifier but its confidence "
                    f"({_conf:.2f}) is below the {COMMIT_CONFIDENCE_FLOOR} commit "
                    f"floor. Find stronger evidence or commit only if the evidence "
                    f"clearly supports a label."
                )
            else:
                _rejection_reason = (
                    v_result.output.rejection_reason or "verifier rejected"
                )
            feedback = VerifierFeedback(
                rejection_reason=_rejection_reason,
                suggested_search_query=v_result.output.suggested_search_query,
                failed_source_url=r_result.output.source_url,
            )
            print(f"  retry with feedback: {feedback.rejection_reason[:80]}",
                  flush=True)
            continue

        # Retries exhausted → Adjudicator.
        break

    # --- Adjudicator stage ---
    _upsert_subtrio_status(
        subtrio_id=subtrio_id, batch_id=batch_id,
        question_id=question_id, country_code=country_code,
        stage="adjudicating", retry_count=retry_count,
        cumulative_cost_usd=cumulative_cost,
        last_message="retries exhausted, calling adjudicator",
    )
    # Build the AdjudicatorInput, but only over verifier_outputs that
    # actually have a value (the placeholder Nones from failed runs are
    # filtered out).
    real_verifier_outputs = [v for v in verifier_outputs if v is not None]
    if not real_verifier_outputs:
        # Edge case: no actual Verifier output to weigh. Skip adjudication.
        final_status = "agent_failure"
        _upsert_subtrio_status(
            subtrio_id=subtrio_id, batch_id=batch_id,
            question_id=question_id, country_code=country_code,
            stage="failed", final_verdict=final_status,
            cumulative_cost_usd=cumulative_cost,
            last_message="no verifier output available for adjudication",
            ended=True,
        )
        _save_final_row(
            run_id=run_id, pair_run_id=pair_run_id, inp=r_inp,
            final_output=last_researcher_output,
            terminal_status=final_status, retry_count=retry_count,
            adjudicator_involved=False, captcha_escalated=False,
            cumulative_input_tokens=cumulative_tokens_in,
            cumulative_output_tokens=cumulative_tokens_out,
            cumulative_wall_clock_ms=cumulative_wall,
            cumulative_cost_usd=cumulative_cost,
            final_failure_reason="no verifier output for adjudication",
        )
        return final_status, last_researcher_output

    adj_inp = AdjudicatorInput(
        question_id=question_id,
        question_text=r_inp.question_text,
        country_code=country_code,
        country_name=r_inp.country_name,
        researcher_outputs=researcher_outputs,
        verifier_outputs=real_verifier_outputs,
        answer_shape=r_inp.answer_shape,
        allowed_answers=list(r_inp.allowed_answers),
    )
    adj_result = run_adjudicator(
        adj_inp,
        model=adjudicator_model,
        subtrio_id=subtrio_id,
        on_step=lambda e, p: _print_step("A", e, p),
    )
    if adj_result.usage:
        cumulative_tokens_in += adj_result.cumulative_input_tokens
        cumulative_tokens_out += adj_result.cumulative_output_tokens
        cumulative_wall += adj_result.cumulative_wall_clock_ms
        if adj_result.cumulative_cost_usd:
            cumulative_cost += adj_result.cumulative_cost_usd

    _save_adjudication_row(
        result=adj_result, inp=adj_inp,
        run_id=run_id, pair_run_id=pair_run_id,
    )

    final_status, chosen_output = _finalise_after_adjudication(
        adj_result.output, researcher_outputs
    )

    _upsert_subtrio_status(
        subtrio_id=subtrio_id, batch_id=batch_id,
        question_id=question_id, country_code=country_code,
        stage="done", final_verdict=final_status,
        cumulative_cost_usd=cumulative_cost,
        last_message=f"adjudicator: {adj_result.output.adjudicator_verdict if adj_result.output else 'failed'}",
        ended=True,
    )
    _save_final_row(
        run_id=run_id, pair_run_id=pair_run_id, inp=r_inp,
        final_output=chosen_output, terminal_status=final_status,
        retry_count=retry_count, adjudicator_involved=True,
        captcha_escalated=False,
        cumulative_input_tokens=cumulative_tokens_in,
        cumulative_output_tokens=cumulative_tokens_out,
        cumulative_wall_clock_ms=cumulative_wall,
        cumulative_cost_usd=cumulative_cost,
        final_failure_reason=None,
    )
    return final_status, chosen_output


# ============================================================
# CLI
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Coordinator pass.")
    parser.add_argument("question_id")
    parser.add_argument("country_code")
    parser.add_argument("--strategy", default="verifier-disprove",
                        choices=["verifier-disprove", "verifier-negation",
                                 "verifier-steelman", "verifier-blind"])
    parser.add_argument("--researcher-model", default=None)
    parser.add_argument("--verifier-model", default=None)
    parser.add_argument("--adjudicator-model", default=None)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--provider", default="auto",
                        choices=["auto", "tavily", "brave", "diy", "serper_raw"],
                        help="Search provider the Researcher and Verifier use "
                             "(D27 experiment knob). Default 'auto' = Tavily then Brave.")
    parser.add_argument("--max-results-per-query", type=int, default=5,
                        help="Results fetched per search query (cost/recall knob).")
    parser.add_argument("--num-queries", type=int, default=None,
                        help="Cap the generated search queries to this many "
                             "(cost knob). Default: no cap (up to 3).")
    parser.add_argument("--no-cache", action="store_true",
                        help="Cold-cache mode (EXP-2): disable DIY cache reads "
                             "for this run so every SERP/fetch/snippet is "
                             "computed live. Writes still happen. Use when "
                             "comparing search cost across conditions so a later "
                             "condition cannot read a prior one's cached hits.")
    parser.add_argument("--subtrio-id", default=None)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--experiment-id", default=None,
                        help="Tag every row produced by this run with the given "
                             "experiment_id (D27). NULL means a main-results run.")
    parser.add_argument("--condition-label", default="baseline",
                        help="Per-condition label inside an experiment (e.g. "
                             "'disprove' vs 'approve'). Written to "
                             "phase2_researcher_runs and phase2_verifier_runs.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Skip writes to subtrio_status, phase2_researcher_runs, "
            "phase2_verifier_runs, phase2_adjudications, and phase2_final. "
            "claude_usage_log is still written (the tokens are real)."
        ),
    )
    parser.add_argument(
        "--walkthrough", action="store_true",
        help="Print every Researcher / Verifier / Adjudicator stage event to stdout.",
    )
    args = parser.parse_args()

    subtrio_id = args.subtrio_id or str(uuid.uuid4())
    batch_id = args.batch_id or str(uuid.uuid4())

    try:
        terminal_status, final_output = coordinate(
            question_id=args.question_id,
            country_code=args.country_code.upper(),
            strategy=args.strategy,
            researcher_model=args.researcher_model,
            verifier_model=args.verifier_model,
            adjudicator_model=args.adjudicator_model,
            max_retries=args.max_retries,
            provider=args.provider,
            max_results_per_query=args.max_results_per_query,
            num_queries=args.num_queries,
            no_cache=args.no_cache,
            subtrio_id=subtrio_id,
            batch_id=batch_id,
            experiment_id=args.experiment_id,
            condition_label=args.condition_label,
            dry_run=args.dry_run,
            walkthrough=args.walkthrough,
        )
    except RateLimitedShutdown as exc:
        print(f"\n[RATE LIMITED] {exc}", file=sys.stderr)
        _upsert_subtrio_status(
            subtrio_id=subtrio_id, batch_id=batch_id,
            question_id=args.question_id, country_code=args.country_code.upper(),
            stage="interrupted_rate_limit",
            final_verdict="interrupted_rate_limit",
            last_message=str(exc)[:200],
            final_failure_reason="anthropic_rate_limit",
            ended=True,
        )
        return EXIT_CODE_RATE_LIMITED

    print(f"\n=== TERMINAL: {terminal_status} ===")
    if final_output:
        print(f"  answer: {final_output.answer} "
              f"({final_output.answer_confidence:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
