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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.adjudicator import run_adjudicator
from agents.errors import (
    EXIT_CODE_RATE_LIMITED, EXIT_CODE_BLOCKER,
    RateLimitedShutdown, BlockerShutdown,
)
from agents.tools import answer_shapes
from agents.models import (
    AdjudicatorInput,
    AdjudicatorOutput,
    EvidenceItem,
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
    # Norway: the current development sweep country (D42 hold-out rule). NO sits
    # outside the nine-country evaluation matrix, so the default pipeline may be
    # iterated against it without contaminating the held-out estimate.
    "NO": {"country_name": "Norway",   "country_language": "no",
           "portal_url": "https://data.norge.no/"},
    # SK / SI / SE: members of the D42 3x3 evaluation matrix. Wired here so the
    # codes exist, but the matrix must not be run until the language-resource
    # axis is fixed empirically (see the warning on D42); these are not for the
    # headline run yet.
    "SK": {"country_name": "Slovakia", "country_language": "sk",
           "portal_url": "https://data.slovensko.sk/"},
    "SI": {"country_name": "Slovenia", "country_language": "sl",
           "portal_url": "https://podatki.gov.si/"},
    "SE": {"country_name": "Sweden",   "country_language": "sv",
           "portal_url": "https://www.dataportal.se/"},
    # Albania: dev-set country (D47). Albanian (sq) is low-resource, so binary
    # questions route through web search and portal_url is not on the critical
    # path. Portal from the D46 discovery seed list (opendata.gov.al, AKSHI).
    "AL": {"country_name": "Albania",  "country_language": "sq",
           "portal_url": "https://opendata.gov.al/"},
    # D47 held-out evaluation set, wired here for the EXP-21 frozen headline run
    # (the one sanctioned use of these countries). Languages are the national
    # query language; portal bases come from the D46 discovery seeds. SE is
    # already configured above. Stratum A (negative-rich, low/mid resource):
    "BA": {"country_name": "Bosnia and Herzegovina", "country_language": "bs",
           "portal_url": "https://odp.iddeea.gov.ba/"},
    "MK": {"country_name": "North Macedonia", "country_language": "mk",
           "portal_url": "https://data.gov.mk/"},
    "ME": {"country_name": "Montenegro", "country_language": "sr",
           "portal_url": "https://data.gov.me/"},
    "BG": {"country_name": "Bulgaria", "country_language": "bg",
           "portal_url": "https://data.egov.bg/"},
    # Stratum B (higher-resource, balanced):
    "FI": {"country_name": "Finland", "country_language": "fi",
           "portal_url": "https://www.avoindata.fi/"},
    "HR": {"country_name": "Croatia", "country_language": "hr",
           "portal_url": "https://data.gov.hr/"},
    # Belgium is trilingual; Dutch is the largest first language, so queries
    # default to nl. The federal portal is multilingual (EN/FR/NL available).
    "BE": {"country_name": "Belgium", "country_language": "nl",
           "portal_url": "https://data.gov.be/"},
    # Remaining ODMI countries, wired for completeness so no (question, country)
    # pair can ever bail with 'Country not configured'. Languages are the
    # national query language; portal bases from the D46 discovery seeds. These
    # are neither dev nor held-out, so the orchestrator preflight still gates
    # them out of experiment runs; this only removes the coordinator-level bail.
    "AT": {"country_name": "Austria",     "country_language": "de",
           "portal_url": "https://www.data.gv.at/"},
    "CH": {"country_name": "Switzerland", "country_language": "de",
           "portal_url": "https://opendata.swiss/"},
    "CY": {"country_name": "Cyprus",      "country_language": "el",
           "portal_url": "https://www.data.gov.cy/"},
    "CZ": {"country_name": "Czechia",     "country_language": "cs",
           "portal_url": "https://data.gov.cz/"},
    "DK": {"country_name": "Denmark",     "country_language": "da",
           "portal_url": "https://www.opendata.dk/"},
    "EL": {"country_name": "Greece",      "country_language": "el",
           "portal_url": "https://data.gov.gr/"},
    "ES": {"country_name": "Spain",       "country_language": "es",
           "portal_url": "https://datos.gob.es/"},
    "IE": {"country_name": "Ireland",     "country_language": "en",
           "portal_url": "https://data.gov.ie/"},
    "IS": {"country_name": "Iceland",     "country_language": "is",
           "portal_url": "https://opingogn.is/"},
    "IT": {"country_name": "Italy",       "country_language": "it",
           "portal_url": "https://www.dati.gov.it/"},
    "LT": {"country_name": "Lithuania",   "country_language": "lt",
           "portal_url": "https://data.gov.lt/"},
    "LU": {"country_name": "Luxembourg",  "country_language": "fr",
           "portal_url": "https://data.public.lu/"},
    "LV": {"country_name": "Latvia",      "country_language": "lv",
           "portal_url": "https://data.gov.lv/"},
    "PL": {"country_name": "Poland",      "country_language": "pl",
           "portal_url": "https://dane.gov.pl/"},
    "PT": {"country_name": "Portugal",    "country_language": "pt",
           "portal_url": "https://dados.gov.pt/"},
    "RS": {"country_name": "Serbia",      "country_language": "sr",
           "portal_url": "https://data.gov.rs/"},
    "UA": {"country_name": "Ukraine",     "country_language": "uk",
           "portal_url": "https://data.gov.ua/"},
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
    return (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds") + "Z"
    )


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
    prior_evidence: Optional[List[EvidenceItem]] = None,
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
        prior_evidence=list(prior_evidence or []),
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

    if adj_output is None or adj_output.adjudicator_verdict == "abstain":
        # The Adjudicator abstained (D51, formerly escalate_human): it could
        # not pick a winner. Returning the last Researcher output verbatim let
        # a sub-floor `no` (e.g. R3 at 0.45) become a finalised commit. That
        # defeats the D37 abstain floor: we want an honest abstention on retry
        # exhaustion, not whichever guess the last Researcher attempt happened
        # to produce. Keep the `escalated_adjudicator` terminal status, but
        # write `inconclusive` as the answer so the headline metric is not
        # polluted by a sub-floor fallback.
        chosen = ResearcherOutput(
            answer="inconclusive",
            answer_explanation=(
                last_researcher_output.answer_explanation[:300]
                if last_researcher_output.answer_explanation else ""
            ),
            evidence_quote=last_researcher_output.evidence_quote or "",
            source_url=str(last_researcher_output.source_url),
            retrieval_confidence=last_researcher_output.retrieval_confidence,
            answer_confidence=last_researcher_output.answer_confidence,
        )
        return ("escalated_adjudicator", chosen)

    # All resolved verdicts share the same finalisation logic: use the
    # Adjudicator's authoritative answer and evidence, not the raw researcher
    # or verifier fields.
    #
    # EXP-16 free arm: an `attempt_correct` verdict commits the answer of the
    # Researcher attempt the Adjudicator named in `chosen_attempt` (1-based).
    # We bind adj_answer to that attempt's own answer so the committed label
    # cannot be a synthesised one outside the attempts' answer set. The
    # Adjudicator's evidence URL/quote and confidence still carry the
    # finalisation, and the D37 floor / D44 backstop below apply unchanged.
    # The standard arm never emits this verdict, so this branch is dead there.
    adj_answer = adj_output.adjudicator_answer or "inconclusive"
    adj_conf = adj_output.adjudicator_confidence
    if adj_output.adjudicator_verdict == "attempt_correct":
        idx = adj_output.chosen_attempt
        if idx is not None and 1 <= idx <= len(researcher_outputs):
            adj_answer = researcher_outputs[idx - 1].answer
    if (not _is_abstention(adj_answer)
            and (adj_conf or 0.0) < COMMIT_CONFIDENCE_FLOOR):
        adj_answer = "inconclusive"
    # Evidence is a URL plus a quoted passage. A bare token like "yes" is
    # not evidence, and anything under the ResearcherOutput min_length (10)
    # would raise a ValidationError and crash the pair after the
    # adjudication has already been paid for. Treat a missing or too-short
    # quote as no quote.
    adj_quote = (adj_output.chosen_evidence_quote or "").strip()
    if len(adj_quote) < 10:
        adj_quote = "(adjudicator did not provide quote)"
    # D44: absence of evidence is not "no". If the Adjudicator committed a
    # negative label with no supporting quote, it is treating a failure to
    # find evidence as a negative. Abstain instead. (The prompt is the
    # primary guard; this is the structural backstop.)
    if (not _is_abstention(adj_answer)
            and adj_answer.strip().lower() == "no"
            and adj_quote == "(adjudicator did not provide quote)"):
        adj_answer = "inconclusive"
    chosen = ResearcherOutput(
        answer=adj_answer,
        answer_explanation=adj_output.adjudicator_reasoning[:300],
        evidence_quote=adj_quote,
        source_url=str(
            adj_output.chosen_source_url or last_researcher_output.source_url
        ),
        retrieval_confidence=0.7,
        answer_confidence=adj_conf,
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
    experiment_id: Optional[str] = None,
    condition_label: str = "baseline",
) -> Optional[dict]:
    """Look for a Researcher row from a recent incomplete subtrio.

    Returns the row dict (or None) for the most recent
    `phase2_researcher_runs` entry whose subtrio:
      - belongs to the SAME experiment_id and condition_label as the
        current run (so an arm never resumes another arm's work), and
      - never wrote a `phase2_final` row, and
      - is no longer in an active stage (orphaned, interrupted, or
        merely stale by more than `max_age_minutes`).

    Only a clean, committed Researcher result is resumable: rows that
    failed (`failure_mode` set) or abstained (`answer = 'inconclusive'`)
    are skipped. Resuming from those re-entered the retry/abstention
    branch without finalising, which left the new subtrio orphaned at
    'researching' with no `phase2_final`. A fresh Researcher call is the
    right move for those pairs, so the finder ignores them and the
    coordinator runs the Researcher from scratch.

    The experiment / condition scoping matters for paired experiments
    such as EXP-7 (D39): baseline and chained run on the identical pair
    set, often back to back, so an unscoped resume would let a chained
    run inherit a baseline Researcher row (or vice versa) and silently
    mix the arms. Matching on `experiment_id` and `condition_label`
    keeps the comparison paired. Production runs carry a NULL
    experiment_id and the 'baseline' condition, so they still resume only
    other production rows, exactly as before.

    The freshness window protects us from reusing an answer that was
    correct yesterday but might have moved on.
    """
    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(minutes=max_age_minutes)
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
              AND r.experiment_id IS ?
              AND r.condition_label IS ?
              AND r.retry_count = 0
              AND r.answer IS NOT NULL
              AND r.failure_mode IS NULL
              AND lower(trim(r.answer)) != 'inconclusive'
              AND f.id IS NULL
              AND (s.stage IN ('orphaned', 'interrupted_rate_limit', 'failed')
                   OR (s.updated_at IS NOT NULL
                       AND s.updated_at < ?))
            ORDER BY r.id DESC
            LIMIT 1
            """,
            (question_id, country_code, experiment_id, condition_label, cutoff),
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


# ============================================================
# EXP-7: evidence accumulation across the retry loop (chained arm)
# ============================================================
#
# These helpers are pure and offline. They turn a Researcher/Verifier run
# into EvidenceItem records and merge them into a running corpus, de-duped
# on (source_url, first 160 chars of snippet) so a page seen twice across
# rounds is not double-counted. They are only ever called when the chained
# arm is on; the baseline loop never touches them, so its prompts are
# byte-identical. See `docs/EXPERIMENTS_CHAINING.md`.

# Cap on the carried corpus so a long retry chain cannot blow up the prompt.
MAX_EVIDENCE_ITEMS = 40


def _evidence_from_researcher(result, round_index: int) -> List[EvidenceItem]:
    """EvidenceItems for the snippets a Researcher run actually read."""
    items: List[EvidenceItem] = []
    for r in result.search_results:
        if not r.snippet:
            continue
        items.append(EvidenceItem(
            snippet=r.snippet,
            source_url=str(r.url) if r.url else None,
            origin="researcher",
            round_index=round_index,
        ))
    return items


def _evidence_from_verifier(result, round_index: int) -> List[EvidenceItem]:
    """EvidenceItems for the Verifier's independent search and its
    counter-evidence quote, the findings the baseline loop throws away."""
    items: List[EvidenceItem] = []
    for r in result.search_results:
        if not r.snippet:
            continue
        items.append(EvidenceItem(
            snippet=r.snippet,
            source_url=str(r.url) if r.url else None,
            origin="verifier",
            round_index=round_index,
        ))
    o = result.output
    if o is not None and o.counter_evidence_quote:
        items.append(EvidenceItem(
            snippet=o.counter_evidence_quote,
            source_url=str(o.counter_source_url) if o.counter_source_url else None,
            origin="verifier",
            round_index=round_index,
        ))
    return items


def _merge_evidence(
    corpus: List[EvidenceItem],
    new_items: List[EvidenceItem],
    *,
    max_items: int = MAX_EVIDENCE_ITEMS,
) -> List[EvidenceItem]:
    """Append new evidence to the corpus, de-duped and capped.

    De-dup key is (source_url, full snippet) so the same page resurfacing
    on a later round does not pad the corpus. The full snippet is used, not
    a prefix: two distinct passages from one page that share an opening
    (a cookie banner, a nav header) must not collide and drop real
    evidence. Returns a new list; the input is not mutated.
    """
    merged = list(corpus)
    seen = {(it.source_url, it.snippet) for it in merged}
    for it in new_items:
        key = (it.source_url, it.snippet)
        if key in seen:
            continue
        seen.add(key)
        merged.append(it)
    return merged[:max_items]


def _is_abstention(answer: Optional[str]) -> bool:
    """True if the answer is the `inconclusive` abstention literal.

    `not_applicable` is a valid determination and is NOT an abstention.
    """
    return bool(answer) and answer.strip().lower() == "inconclusive"


# Minimum answer confidence required to commit an answer that the Verifier
# passed. A Verifier pass on a low-confidence answer is a likely false
# positive (confident-wrong), so the coordinator retries instead.
COMMIT_CONFIDENCE_FLOOR = 0.65


def _model_for_attempt(
    base_model: Optional[str],
    escalation_model: Optional[str],
    attempt: int,
) -> Optional[str]:
    """Pick the model for a given retry attempt (EXP-8 model-fallback).

    Attempt 0 always uses `base_model` (the cheaper model in the fallback
    arm). A later attempt uses `escalation_model` when one is set, so a
    retry after a Verifier reject escalates to the stronger model. With no
    escalation model the base model holds across every attempt, which is
    the behaviour for every other arm.
    """
    if attempt > 0 and escalation_model is not None:
        return escalation_model
    return base_model


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
    researcher_escalation_model: Optional[str] = None,
    verifier_escalation_model: Optional[str] = None,
    prompt_variant: str = "full",
    verifier_prompt_variant: str = "default",
    max_retries: int = 3,
    provider: str = "auto",
    max_results_per_query: int = 5,
    num_queries: Optional[int] = None,
    use_snippet_picker: bool = True,
    picker_max_chunks: int = 3,
    page_text_cap: int = 16000,
    max_snippet_chars: int = 600,
    no_cache: bool = False,
    verifier_search: str = "always",
    query_language: str = "bilingual",
    search_strategy: str = "narrow_then_wide",
    picker_model: Optional[str] = None,
    subtrio_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    condition_label: str = "baseline",
    chained: bool = False,
    adjudicator_selection: str = "standard",
    dry_run: bool = False,
    walkthrough: bool = False,
) -> tuple[str, Optional[ResearcherOutput]]:
    """Run one pair end-to-end.

    Returns (terminal_status, final_output).

    `researcher_model` / `verifier_model` / `adjudicator_model` set the
    Claude model per agent (EXP-9 model variants); `None` keeps the
    wrapper default. `researcher_escalation_model` /
    `verifier_escalation_model` implement the EXP-8 `model-fallback` arm:
    the first attempt uses the cheaper base model, and every retry after a
    Verifier reject uses the escalation model. Leave them `None` to hold
    one model across all attempts. `prompt_variant` ('full' or
    'compressed') selects the Researcher system prompt for the EXP-8
    `prompt-compressed` arm; the baseline 'full' prompt is untouched.

    `chained` is the EXP-7 evidence-accumulation arm. When False (the
    default, and what every production and EXP-8/9 baseline run uses) the
    loop is byte-identical to the independent-retry behaviour: each retry is
    a fresh shot carrying only the Verifier's verdict and a diverging query
    (D33). When True, the Verifier's counter-evidence is fed back to the
    Researcher, a corpus of every snippet found so far is carried across
    rounds, and the Adjudicator synthesises over the whole corpus. The D37
    commit-confidence floor and honest-abstention rules are unchanged in
    both arms. See `docs/EXPERIMENTS_CHAINING.md`.

    `verifier_search` (EXP-14) is the Verifier's web counter-search policy.
    'always' (the default) is byte-identical to current production: the
    Verifier runs its own adversarial web search every round. 'never' skips
    that independent search so the Verifier reasons only over the
    Researcher's evidence. 'elective' is not built and raises
    NotImplementedError. The knob does not touch the substring gate or any
    verdict post-processing.

    `search_strategy` (EXP-23) is the Researcher's retrieval strategy
    (SRCH-5/6). 'narrow_then_wide' (the default) is byte-identical to
    production: trusted-domain include list on the first pass, widen only
    on empty. 'wide_only' skips the include list entirely so every query
    runs against the open web. 'narrow_only' keeps the include list but
    never widens, so EXP-23 can attribute any wide_only gain to the
    widening step rather than to the absence of narrowing.

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
    # EXP-7 chained arm: the running evidence corpus across rounds. Stays
    # empty when `chained` is off, so nothing is carried forward and the
    # prompts match the baseline byte-for-byte.
    evidence_corpus: List[EvidenceItem] = []
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
    resumable = _find_resumable_researcher(
        question_id, country_code,
        experiment_id=experiment_id, condition_label=condition_label,
    )
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
                prior_evidence=evidence_corpus if chained else None,
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
            # Wrap the resumed output in a ResearcherRunResult so the rest
            # of the loop is uniform. No usage objects, because the resumed
            # call was already paid for under the prior subtrio (its cost
            # stays in claude_usage_log there), so cumulative_* are zero and
            # nothing is double-charged. The snippets are not persisted on
            # the researcher row, so search_results is empty: a resumed
            # Verifier falls back to a live re-fetch for the quote check
            # rather than the D34 stored-snippet path. The queries are
            # folded into the divergence accumulator so any retry varies.
            r_result = ResearcherRunResult(
                output=last_researcher_output,
                failure_mode=None,
                query_gen_usage=None,
                main_usage=None,
                search_queries_used=last_researcher_output.search_queries_used,
                fetched_urls=last_researcher_output.fetched_urls,
                search_results=[],
            )
            accumulated_search_queries.extend(r_result.search_queries_used)
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
                prior_evidence=evidence_corpus if chained else None,
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

            # model-fallback (EXP-8): the first attempt runs the cheaper
            # base model; a retry after a Verifier reject escalates. With
            # no escalation model set, the base model holds throughout.
            r_model = _model_for_attempt(
                researcher_model, researcher_escalation_model, attempt,
            )
            r_result = run_researcher(
                r_inp, subtrio_id=subtrio_id, on_step=_r_step,
                model=r_model, prompt_variant=prompt_variant,
                provider=provider, max_results_per_query=max_results_per_query,
                num_queries=num_queries,
                use_snippet_picker=use_snippet_picker,
                picker_max_chunks=picker_max_chunks,
                page_text_cap=page_text_cap,
                max_snippet_chars=max_snippet_chars,
                query_language=query_language,
                search_strategy=search_strategy,
                picker_model=picker_model,
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
                    if researcher_outputs:
                        # A prior attempt already produced an answer. Do not
                        # throw the whole pair away as a crash just because the
                        # final retry's search came back empty. Fall through to
                        # the Adjudicator on the attempts we have, so the pair
                        # resolves or abstains honestly rather than recording an
                        # agent_failure (Norway PT15 / PT25 / Q21).
                        print("  final retry failed; adjudicating on prior "
                              "attempts", flush=True)
                        break
                    # No answer was produced on any attempt: a real
                    # unrecoverable failure, keep agent_failure.
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
            # EXP-7 chained arm: fold the snippets this Researcher run read
            # into the running corpus so later rounds and the Adjudicator see
            # them. No-op in the baseline arm.
            if chained:
                evidence_corpus = _merge_evidence(
                    evidence_corpus,
                    _evidence_from_researcher(r_result, retry_count),
                )
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

        v_model = _model_for_attempt(
            verifier_model, verifier_escalation_model, attempt,
        )
        v_result = run_verifier(
            v_inp, subtrio_id=subtrio_id, on_step=_v_step,
            model=v_model,
            provider=provider, max_results_per_query=max_results_per_query,
            num_queries=num_queries,
            verifier_search=verifier_search,
            picker_model=picker_model,
            verifier_prompt_variant=verifier_prompt_variant,
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
        # EXP-7 chained arm: the Verifier searches the web every round and
        # often finds real counter-evidence; the baseline loop keeps only the
        # verdict and bins the rest. Here we fold its independent snippets and
        # counter-evidence into the corpus so they are not thrown away.
        if chained:
            evidence_corpus = _merge_evidence(
                evidence_corpus,
                _evidence_from_verifier(v_result, retry_count),
            )
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
                # EXP-7 chained arm: hand the Verifier's own counter-evidence
                # back to the Researcher, not just the verdict and a query.
                # None in the baseline arm, so the feedback is unchanged.
                counter_evidence_quote=(
                    v_result.output.counter_evidence_quote if chained else None
                ),
                counter_source_url=(
                    v_result.output.counter_source_url if chained else None
                ),
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
        # EXP-7 chained arm: let the Adjudicator synthesise over the whole
        # corpus. Empty in the baseline arm, so its prompt is unchanged.
        evidence_corpus=evidence_corpus if chained else [],
    )
    adj_result = run_adjudicator(
        adj_inp,
        model=adjudicator_model,
        subtrio_id=subtrio_id,
        selection=adjudicator_selection,
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
    parser.add_argument("--researcher-escalation-model", default=None,
                        help="EXP-8 model-fallback: model used for the "
                             "Researcher on a retry after a Verifier reject. "
                             "Attempt 0 uses --researcher-model. Unset = hold "
                             "one model across attempts.")
    parser.add_argument("--verifier-escalation-model", default=None,
                        help="EXP-8 model-fallback: model used for the Verifier "
                             "on a retry. Unset = hold one model.")
    parser.add_argument("--prompt-variant", default="full",
                        choices=["full", "compressed", "calibrated",
                                 "neg_licence"],
                        help="Researcher system prompt. 'full' is the V4 "
                             "baseline; 'compressed' is the EXP-8 cost arm; "
                             "'calibrated' is the EXP-A confidence-anchor arm; "
                             "'neg_licence' is the EXP-C licensed-negative "
                             "arm. All four register distinct prompt_versions "
                             "rows so receipts trace cleanly.")
    parser.add_argument("--verifier-prompt-variant", default="default",
                        choices=["default", "structured"],
                        help="Verifier disprove prompt body. 'default' is the "
                             "V4 prose Step 3; 'structured' is the EXP-B "
                             "per-dimension fit-check (entity / scope / tense "
                             "/ metric / scale). Only valid when --strategy is "
                             "verifier-disprove.")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--provider", default="diy",
                        choices=["auto", "tavily", "brave", "diy", "serper_raw"],
                        help="Search provider the Researcher and Verifier use. "
                             "Production is DIY only (D43); 'auto' is an alias for "
                             "'diy'. tavily/brave are retained only to reproduce the "
                             "EXP-1 provider comparison.")
    parser.add_argument("--max-results-per-query", type=int, default=5,
                        help="Results fetched per search query (cost/recall knob).")
    parser.add_argument("--num-queries", type=int, default=None,
                        help="Cap the generated search queries to this many "
                             "(cost knob). Default: no cap (up to 3).")
    parser.add_argument("--snippet-picker", choices=["on", "off"], default="on",
                        help="EXP-17 DIY snippet-funnel knob. 'on' (default) "
                             "runs the LLM snippet-picker. 'off' BYPASSES the "
                             "picker: the cleaned page text is used directly as "
                             "the snippet so a URL is not dropped just because "
                             "the picker chose nothing. DIY-only; no effect on "
                             "Tavily/Brave.")
    parser.add_argument("--max-snippet-chars", type=int, default=600,
                        help="EXP-17 knob: per-snippet prompt truncation in "
                             "format_for_prompt (chars). Default 600.")
    parser.add_argument("--picker-max-chunks", type=int, default=3,
                        help="EXP-17 knob: most chunks the snippet-picker keeps "
                             "for a non-confident page. Default 3.")
    parser.add_argument("--page-text-cap", type=int, default=16000,
                        help="EXP-17 knob: chars of cleaned page text the "
                             "snippet-picker sees before truncation. Default "
                             "16000.")
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
        "--chained", action="store_true",
        help="EXP-7 evidence-accumulation arm (default off). Feed the "
             "Verifier's counter-evidence back to the Researcher on retry, "
             "carry a corpus of all snippets found so far across rounds, and "
             "have the Adjudicator synthesise over the whole corpus. Off by "
             "default, so production and the EXP-8/9 baseline are "
             "byte-identical to the independent-retry loop.")
    parser.add_argument(
        "--verifier-search", default="always",
        choices=["never", "elective", "always"],
        help="EXP-14 Verifier web counter-search policy. 'always' (default) "
             "is byte-identical to production: the Verifier runs its own "
             "adversarial web search every round. 'never' skips that search "
             "so the Verifier reasons only over the Researcher's evidence. "
             "'elective' is not built and raises NotImplementedError.")
    parser.add_argument(
        "--query-language", default="bilingual",
        choices=["bilingual", "en"],
        help="Foreign-language ablation. 'bilingual' (default) is "
             "byte-identical to production: the Researcher generates an "
             "English query plus a native-language query when the country is "
             "not English-speaking. 'en' ablates the native query so all "
             "queries are English-only. See docs/EXPERIMENTS_FOREIGN_LANG.md.")
    parser.add_argument(
        "--search-strategy", default="narrow_then_wide",
        choices=["narrow_then_wide", "wide_only", "narrow_only"],
        help="EXP-23 Researcher retrieval strategy (SRCH-5/6). "
             "'narrow_then_wide' (default) is byte-identical to production: "
             "trusted-domain include list on the first pass, widen only on "
             "empty. 'wide_only' skips the include list entirely so every "
             "query runs against the open web (one pass, no widen). "
             "'narrow_only' keeps the include list but never widens even on "
             "empty, so EXP-23 can attribute any wide_only gain to the "
             "widening step rather than to the absence of narrowing.")
    parser.add_argument(
        "--picker-model", default=None,
        help="Pin the snippet-picker LLM to this model. Default None falls "
             "back to agents.tools.llm.DEFAULT_MODEL (currently Sonnet); "
             "set to e.g. claude-opus-4-6 when Sonnet quota is exhausted "
             "and the agent models are pinned to Opus, so the picker does "
             "not 429 mid-pair. EXP-23 sets it to Opus.")
    parser.add_argument(
        "--adjudicator-selection", default="standard",
        choices=["standard", "free"],
        help="EXP-16 candidate-selection mode. 'standard' (default) is "
             "byte-identical to production: the Adjudicator's verdict "
             "taxonomy and the registered phase2_adjudicator prompt are "
             "unchanged. 'free' lets the Adjudicator commit ANY of the "
             "up-to-four Researcher attempts' answers by index "
             "(attempt_correct verdict), registering a separate prompt "
             "version (phase2_adjudicator_free).")
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
            researcher_escalation_model=args.researcher_escalation_model,
            verifier_escalation_model=args.verifier_escalation_model,
            prompt_variant=args.prompt_variant,
            verifier_prompt_variant=args.verifier_prompt_variant,
            max_retries=args.max_retries,
            provider=args.provider,
            max_results_per_query=args.max_results_per_query,
            num_queries=args.num_queries,
            use_snippet_picker=(args.snippet_picker == "on"),
            picker_max_chunks=args.picker_max_chunks,
            page_text_cap=args.page_text_cap,
            max_snippet_chars=args.max_snippet_chars,
            no_cache=args.no_cache,
            verifier_search=args.verifier_search,
            query_language=args.query_language,
            search_strategy=args.search_strategy,
            picker_model=args.picker_model,
            subtrio_id=subtrio_id,
            batch_id=batch_id,
            experiment_id=args.experiment_id,
            condition_label=args.condition_label,
            chained=args.chained,
            adjudicator_selection=args.adjudicator_selection,
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
    except BlockerShutdown as exc:
        # The DIY fetch stage blew its 30s ceiling (D43): a real blocker, not a
        # per-pair failure. Flush state and signal a global stop, same contract
        # as a 429 so the dispatcher tears the whole batch down.
        print(f"\n[BLOCKER] {exc}", file=sys.stderr)
        _upsert_subtrio_status(
            subtrio_id=subtrio_id, batch_id=batch_id,
            question_id=args.question_id, country_code=args.country_code.upper(),
            stage="interrupted_blocker",
            final_verdict="interrupted_blocker",
            last_message=str(exc)[:200],
            final_failure_reason="diy_fetch_blocker",
            ended=True,
        )
        return EXIT_CODE_BLOCKER

    print(f"\n=== TERMINAL: {terminal_status} ===")
    if final_output:
        print(f"  answer: {final_output.answer} "
              f"({final_output.answer_confidence:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
