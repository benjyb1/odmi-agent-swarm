"""Read-only DB helpers for the dashboard.

The dashboard only reads. Every write is funneled through the agent
scripts (run_coordinator.py, dispatch_subtrios.py). Keeping read and
write paths separate means the dashboard cannot accidentally corrupt
the audit trail.

All helpers return plain dicts or pandas DataFrames so Streamlit can
render them without further massaging.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "odmi.db"


def _conn() -> sqlite3.Connection:
    """Open a read-only-ish connection. Streamlit calls this often."""
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def read_sql(query: str, params: tuple = ()) -> pd.DataFrame:
    """Run a query, return a DataFrame. Empty DataFrame on no results."""
    with _conn() as conn:
        return pd.read_sql_query(query, conn, params=params)


# Subtrio status

def active_subtrios() -> pd.DataFrame:
    """Rows currently in an active stage."""
    return read_sql(
        """SELECT * FROM subtrio_status
           WHERE stage IN ('queued', 'researching', 'verifying', 'adjudicating')
           ORDER BY started_at DESC"""
    )


def recent_subtrios(limit: int = 30) -> pd.DataFrame:
    """Most recent subtrios across all batches."""
    return read_sql(
        f"""SELECT * FROM subtrio_status
            ORDER BY COALESCE(ended_at, updated_at, started_at) DESC
            LIMIT {int(limit)}"""
    )


def subtrios_by_batch(batch_id: str) -> pd.DataFrame:
    return read_sql(
        """SELECT * FROM subtrio_status
           WHERE batch_id = ?
           ORDER BY started_at""",
        (batch_id,),
    )


# Phase 2 results

def researcher_runs(limit: int = 200) -> pd.DataFrame:
    return read_sql(
        f"""SELECT id, run_id, pair_run_id, question_id, country_code,
                   retry_count, answer, answer_confidence, retrieval_confidence,
                   domain_trust_score, source_url, evidence_quote,
                   model_version, condition_label, failure_mode, notes,
                   estimated_cost_usd, wall_clock_ms, created_at
            FROM phase2_researcher_runs
            ORDER BY id DESC LIMIT {int(limit)}"""
    )


def verifier_runs(limit: int = 200) -> pd.DataFrame:
    return read_sql(
        f"""SELECT id, run_id, pair_run_id, question_id, country_code,
                   retry_count, strategy_label, verdict, verifier_answer,
                   verifier_confidence, substring_check_result,
                   rejection_reason, counter_source_url,
                   researcher_run_id, model_version, condition_label,
                   estimated_cost_usd, wall_clock_ms, created_at
            FROM phase2_verifier_runs
            ORDER BY id DESC LIMIT {int(limit)}"""
    )


def adjudications(limit: int = 50) -> pd.DataFrame:
    return read_sql(
        f"""SELECT * FROM phase2_adjudications
            ORDER BY id DESC LIMIT {int(limit)}"""
    )


def finals(limit: int = 200) -> pd.DataFrame:
    return read_sql(
        f"""SELECT * FROM phase2_final
            ORDER BY id DESC LIMIT {int(limit)}"""
    )


_MATCH_STATUS_SQL = """
    CASE
      WHEN gt.response IS NULL OR TRIM(gt.response) = ''
        THEN 'no_ground_truth'
      WHEN f.final_answer IS NULL OR TRIM(f.final_answer) = ''
        THEN 'no_swarm_answer'
      -- A `not applicable` / `n/a` gold means ODMI itself judged the question
      -- not applicable. The swarm abstaining (`inconclusive`) or also saying
      -- n/a there is the correct outcome, so it scores `match`. A swarm that
      -- instead commits a real answer is not necessarily wrong: it may have
      -- found evidence the assessors missed, so it is flagged for review
      -- (`flag_review`) rather than scored `differ`, and is excluded from the
      -- accuracy denominator pending that review.
      WHEN REPLACE(LOWER(TRIM(gt.response)), '_', ' ') IN
             ('not applicable', 'n/a', 'na')
        THEN CASE
          WHEN LOWER(TRIM(f.final_answer)) = 'inconclusive'
               OR REPLACE(LOWER(TRIM(f.final_answer)), '_', ' ') IN
                    ('not applicable', 'n/a', 'na')
            THEN 'match'
          ELSE 'flag_review'
        END
      -- D35/D37: `inconclusive` is an honest abstention, not a label.
      -- It is held in its own bucket so the abstention rate can be
      -- reported separately, but it is still a failure to answer, so
      -- accuracy_summary counts it against accuracy (it never matches).
      WHEN LOWER(TRIM(f.final_answer)) = 'inconclusive'
        THEN 'abstained'
      -- Normalise underscores to spaces on both sides before comparing.
      -- The swarm writes sentinels like `not_applicable`; ODMI gold carries
      -- `not applicable`. They are the same answer, so an underscore-vs-space
      -- difference must not score `differ` (the Norway scoring artefact).
      WHEN REPLACE(LOWER(TRIM(f.final_answer)), '_', ' ')
           = REPLACE(LOWER(TRIM(gt.response)), '_', ' ')
        THEN 'match'
      -- A bare `yes` only fully matches a `yes...` gold on a binary
      -- question. On a count_band gold like `yes, >9` a bare `yes`
      -- is under-specified and must not score an exact match.
      WHEN LOWER(TRIM(f.final_answer)) = 'yes'
           AND (LOWER(TRIM(gt.response)) LIKE 'yes%')
           AND EXISTS (
             SELECT 1 FROM questions q
             WHERE q.question_id = f.question_id
               AND q.answer_shape = 'binary'
           )
        THEN 'match'
      WHEN LOWER(TRIM(f.final_answer)) = 'no'
           AND LOWER(TRIM(gt.response)) = 'no'
        THEN 'match'
      -- D28: adjacent-band miss on an ordered shape counts as
      -- near_match, not differ. The questions table carries the
      -- ordered list of labels per question; we look up the indices
      -- of the swarm and ODMI answers and check that they are one
      -- step apart. Sentinel labels (`not applicable`, `i don't know`
      -- and the abstention/other escape hatches) are not band steps,
      -- so they are excluded: they sit at the end of some allowed_answers
      -- lists and would otherwise read as adjacent to a real band.
      WHEN EXISTS (
        SELECT 1
        FROM questions q,
             json_each(q.allowed_answers) ja_swarm,
             json_each(q.allowed_answers) ja_gt
        WHERE q.question_id = f.question_id
          AND q.answer_shape IN ('percentage_band',
                                  'ordinal_magnitude',
                                  'count_band')
          AND ABS(ja_swarm.key - ja_gt.key) = 1
          AND LOWER(TRIM(ja_swarm.value)) = LOWER(TRIM(f.final_answer))
          AND LOWER(TRIM(ja_gt.value)) = LOWER(TRIM(gt.response))
          AND LOWER(TRIM(ja_swarm.value)) NOT IN
                ('not applicable', 'i don''t know', 'inconclusive', 'other')
          AND LOWER(TRIM(ja_gt.value)) NOT IN
                ('not applicable', 'i don''t know', 'inconclusive', 'other')
      )
        THEN 'near_match'
      ELSE 'differ'
    END
"""


# D27: dissertation headline numbers exclude experiment rows.
# Apply to phase2_final references as `WHERE f.experiment_id IS NULL`
# (or alias appropriately). The Experimentation page intentionally
# does the opposite, filtering to a single experiment_id.
MAIN_RUNS_FILTER = "f.experiment_id IS NULL"


# A (question, country) pair can carry several phase2_final rows when it is
# re-dispatched (e.g. a resumed run, or a re-score after a code fix). The
# headline aggregates must count each pair once, using the latest row, or a
# re-run pair is double-counted and a pair with two conflicting finals is
# scored as both match and differ. This subquery keeps only the newest row per
# (question, country, experiment_id); use it as `FROM {_LATEST_FINALS} f`.
# coverage_grid does its own ROW_NUMBER dedup and is left untouched.
_LATEST_FINALS = """(
    SELECT * FROM phase2_final
    WHERE id IN (
        SELECT id FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY question_id, country_code, experiment_id
                ORDER BY id DESC
            ) AS _rn
            FROM phase2_final
        ) WHERE _rn = 1
    )
)"""


def analytics_frame() -> pd.DataFrame:
    """One fat row per finalised main-run pair with every axis the
    Analytics page can slice on.

    Joins:
    - questions             (dimension, indicator)
    - subtrio_status        (R/V/A models, verifier_strategy)
    - latest_verifier       (most recent verdict + confidence + strategy)
    - any_rejection         (1 if any V verdict in the history was 'fail')
    - provider_mix          (search_provider_calls JSON unrolled)
    - ground_truth          (response → match_status)

    Columns the page groups on: dimension, country_code, researcher_model,
    verifier_model, adjudicator_model, verifier_strategy, search_provider.

    Columns it summarises: match_status, terminal_status, retry_count,
    adjudicator_involved, had_rejection, cumulative_cost_usd,
    cumulative_wall_clock_ms.

    Always filtered to main runs (D27 MAIN_RUNS_FILTER).
    """
    return read_sql(
        f"""
        WITH latest_verifier AS (
            SELECT pair_run_id, verdict, verifier_confidence, strategy_label
            FROM phase2_verifier_runs v
            WHERE id = (
                SELECT MAX(id) FROM phase2_verifier_runs
                WHERE pair_run_id = v.pair_run_id
            )
        ),
        any_rejection AS (
            SELECT pair_run_id,
                   MAX(CASE WHEN verdict = 'fail' THEN 1 ELSE 0 END) AS had_rejection
            FROM phase2_verifier_runs
            GROUP BY pair_run_id
        ),
        provider_mix AS (
            SELECT r.pair_run_id,
                   SUM(json_extract(value, '$.provider') = 'tavily'
                       AND json_extract(value, '$.ok') = 1) AS n_tavily_ok,
                   SUM(json_extract(value, '$.provider') = 'brave'
                       AND json_extract(value, '$.ok') = 1) AS n_brave_ok
            FROM phase2_researcher_runs r, json_each(r.search_provider_calls)
            WHERE r.search_provider_calls IS NOT NULL
            GROUP BY r.pair_run_id
        )
        SELECT
            f.id, f.pair_run_id, f.question_id, f.country_code,
            f.terminal_status, f.retry_count, f.adjudicator_involved,
            f.final_answer,
            f.cumulative_cost_usd, f.cumulative_wall_clock_ms,
            f.created_at,
            q.dimension, q.indicator,
            v.verdict           AS latest_verifier_verdict,
            v.verifier_confidence,
            v.strategy_label    AS verifier_strategy,
            COALESCE(ar.had_rejection, 0) AS had_rejection,
            s.researcher_model, s.verifier_model, s.adjudicator_model,
            pm.n_tavily_ok, pm.n_brave_ok,
            CASE
                WHEN pm.pair_run_id IS NULL THEN 'unknown'
                WHEN COALESCE(pm.n_brave_ok, 0) = 0 AND COALESCE(pm.n_tavily_ok, 0) > 0
                    THEN 'tavily'
                WHEN COALESCE(pm.n_tavily_ok, 0) = 0 AND COALESCE(pm.n_brave_ok, 0) > 0
                    THEN 'brave'
                ELSE 'mixed'
            END AS search_provider,
            gt.response         AS odmi_response,
            {_MATCH_STATUS_SQL} AS match_status
        FROM {_LATEST_FINALS} f
        LEFT JOIN questions q    ON q.question_id = f.question_id
        LEFT JOIN latest_verifier v ON v.pair_run_id = f.pair_run_id
        LEFT JOIN any_rejection ar ON ar.pair_run_id = f.pair_run_id
        LEFT JOIN subtrio_status s ON s.subtrio_id = f.pair_run_id
        LEFT JOIN provider_mix pm  ON pm.pair_run_id = f.pair_run_id
        LEFT JOIN ground_truth gt
              ON gt.question_id = f.question_id
             AND gt.country_code = f.country_code
        WHERE {MAIN_RUNS_FILTER}
        ORDER BY f.created_at DESC, f.id DESC
        """
    )


def result_cards() -> pd.DataFrame:
    """One row per finalised pair, joined with questions, latest Verifier,
    and ODMI ground truth. Adds match_status, ground_truth_response, and
    ground_truth_explanation columns so the Cards view can render the
    swarm answer next to ODMI's recorded answer with a match badge.
    """
    return read_sql(
        f"""
        WITH latest_verifier AS (
            SELECT pair_run_id,
                   verdict, verifier_confidence, strategy_label,
                   rejection_reason, counter_evidence_quote, counter_source_url,
                   substring_check_result
            FROM phase2_verifier_runs v
            WHERE id = (
                SELECT MAX(id) FROM phase2_verifier_runs
                WHERE pair_run_id = v.pair_run_id
            )
        )
        SELECT
            f.id, f.pair_run_id, f.question_id, f.country_code,
            f.terminal_status, f.retry_count, f.adjudicator_involved,
            f.final_answer, f.final_answer_explanation,
            f.final_evidence_quote, f.final_source_url,
            f.final_retrieval_confidence, f.final_answer_confidence,
            f.cumulative_cost_usd, f.cumulative_wall_clock_ms,
            f.created_at,
            q.dimension, q.indicator, q.question_text,
            v.verdict          AS verifier_verdict,
            v.verifier_confidence,
            v.strategy_label   AS verifier_strategy,
            v.rejection_reason,
            v.counter_evidence_quote,
            v.counter_source_url,
            v.substring_check_result,
            gt.response        AS ground_truth_response,
            gt.decision        AS ground_truth_decision,
            gt.awarded_score   AS ground_truth_awarded_score,
            gt.max_score       AS ground_truth_max_score,
            gt.explanation     AS ground_truth_explanation,
            gt.cycle_year      AS ground_truth_cycle,
            {_MATCH_STATUS_SQL} AS match_status
        FROM {_LATEST_FINALS} f
        LEFT JOIN questions q   ON q.question_id = f.question_id
        LEFT JOIN latest_verifier v ON v.pair_run_id = f.pair_run_id
        LEFT JOIN ground_truth gt
              ON gt.question_id = f.question_id
             AND gt.country_code = f.country_code
        WHERE {MAIN_RUNS_FILTER}
        ORDER BY f.created_at DESC, f.id DESC
        """
    )


def country_outcome_counts() -> pd.DataFrame:
    """Per-country counts of finalised pairs, split by match against
    ODMI ground truth. Match = swarm final_answer agrees with the
    `response` column on the corresponding ground_truth row. Countries
    with zero finalised pairs are excluded.

    Returned columns: country_code, outcome ('Matches ODMI' |
    'Differs from ODMI' | 'No ground truth'), n.
    """
    df = read_sql(
        f"""
        WITH per_pair AS (
            SELECT f.country_code,
                   {_MATCH_STATUS_SQL} AS match_status
            FROM {_LATEST_FINALS} f
            LEFT JOIN ground_truth gt
              ON gt.question_id = f.question_id
             AND gt.country_code = f.country_code
            WHERE f.country_code IS NOT NULL
              AND {MAIN_RUNS_FILTER}
        )
        SELECT country_code,
               CASE match_status
                 WHEN 'match' THEN 'Matches ODMI'
                 WHEN 'near_match' THEN 'Near match (adjacent band)'
                 WHEN 'differ' THEN 'Differs from ODMI'
                 WHEN 'abstained' THEN 'Abstained'
                 WHEN 'flag_review' THEN 'Flag for review (n/a gold)'
                 ELSE 'No ground truth'
               END AS outcome,
               COUNT(*) AS n
        FROM per_pair
        GROUP BY country_code, outcome
        """
    )
    return df


def accuracy_summary() -> dict:
    """Overall accuracy of the swarm against ODMI ground truth.

    Returns {n_finalised, n_match, n_near_match, n_differ, n_abstained,
    n_flag_review, n_failed, n_no_truth, accuracy,
    accuracy_within_one_band, abstention_rate}.

    Counts are over the latest phase2_final row per (question, country,
    experiment_id): a re-dispatched pair is counted once, never as both
    match and differ. `n_failed` is pairs with no swarm answer (empty /
    NULL final_answer); `n_flag_review` is a committed answer on an n/a
    gold, held for review. Both are excluded from the accuracy
    denominator. `n_no_truth` is now ground-truth-missing only.

    `accuracy` is exact matches / (matches + near_matches + differs +
    abstentions). An abstention (`inconclusive`) is a failure to answer,
    so it is counted in the denominator against accuracy, never as a
    correct answer. `abstention_rate` reports those abstentions as their
    own metric: abstentions / (the same answerable denominator).
    `accuracy_within_one_band` counts a near_match as correct,
    representing how often the swarm's band is at most one step off
    ODMI's answer. All three exclude pairs without a ground-truth row.
    """
    with _conn() as conn:
        row = conn.execute(
            f"""SELECT
                  COUNT(*) AS n_finalised,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'match'
                           THEN 1 ELSE 0 END) AS n_match,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'near_match'
                           THEN 1 ELSE 0 END) AS n_near_match,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'differ'
                           THEN 1 ELSE 0 END) AS n_differ,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'abstained'
                           THEN 1 ELSE 0 END) AS n_abstained,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'flag_review'
                           THEN 1 ELSE 0 END) AS n_flag_review,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'no_swarm_answer'
                           THEN 1 ELSE 0 END) AS n_failed,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'no_ground_truth'
                           THEN 1 ELSE 0 END) AS n_no_truth
                FROM {_LATEST_FINALS} f
                LEFT JOIN ground_truth gt
                  ON gt.question_id = f.question_id
                 AND gt.country_code = f.country_code
                WHERE {MAIN_RUNS_FILTER}""",
        ).fetchone()
    n_finalised = int(row["n_finalised"] or 0)
    n_match = int(row["n_match"] or 0)
    n_near_match = int(row["n_near_match"] or 0)
    n_differ = int(row["n_differ"] or 0)
    n_abstained = int(row["n_abstained"] or 0)
    n_flag_review = int(row["n_flag_review"] or 0)
    n_failed = int(row["n_failed"] or 0)
    n_no_truth = int(row["n_no_truth"] or 0)
    # flag_review (committed on an n/a gold, pending review) and n_failed
    # (no swarm answer produced) are excluded from the accuracy denominator:
    # neither is a scored right-or-wrong answer.
    denom = n_match + n_near_match + n_differ + n_abstained
    accuracy = (n_match / denom) if denom > 0 else None
    accuracy_within_one_band = (
        (n_match + n_near_match) / denom if denom > 0 else None
    )
    abstention_rate = (n_abstained / denom) if denom > 0 else None
    return {
        "n_finalised": n_finalised,
        "n_match": n_match,
        "n_near_match": n_near_match,
        "n_differ": n_differ,
        "n_abstained": n_abstained,
        "n_flag_review": n_flag_review,
        "n_failed": n_failed,
        "n_no_truth": n_no_truth,
        "accuracy": accuracy,
        "accuracy_within_one_band": accuracy_within_one_band,
        "abstention_rate": abstention_rate,
    }


def accuracy_by_decision() -> list[dict]:
    """Swarm accuracy stratified by ODMI's `decision` validation field.

    ODMI is a country self-report questionnaire validated by assessors; the
    `ground_truth.decision` field records, per (question, country), whether the
    country's answer was accepted as submitted (`confirm`, ~63% of rows), kept
    with assessor-added desk-research evidence (`complement`, ~27%), or
    overridden by the assessor (`change`, ~10%). The swarm reads the open web,
    so a disagreement on a `confirm` gold (the country's unverifiable word) is
    often a measurement mismatch rather than a swarm error, whereas `complement`
    golds are themselves web-evidenced. This splits the headline accuracy /
    abstention / false-positive figures by that field so the self-report
    contamination is visible (D22; docs/CONFIDENCE_FRAMEWORK_DEEPDIVE.md
    section 1A; logic from evaluation/selfreport_decision_split.py).

    Returns one dict per decision value (ordered confirm, complement, change,
    then any others / `(none)`), each carrying `decision`, the match-status
    counts, `accuracy` and `abstention_rate` over the same answerable
    denominator as accuracy_summary, plus `n_fp` (a binary committed `yes` on a
    `no` gold) and `fp_rate` over committed negative golds. Production runs only
    (MAIN_RUNS_FILTER), ground-truth rows only.
    """
    with _conn() as conn:
        rows = conn.execute(
            f"""SELECT
                  COALESCE(NULLIF(TRIM(gt.decision), ''), '(none)') AS decision,
                  COUNT(*) AS n_finalised,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'match'
                           THEN 1 ELSE 0 END) AS n_match,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'near_match'
                           THEN 1 ELSE 0 END) AS n_near_match,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'differ'
                           THEN 1 ELSE 0 END) AS n_differ,
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) = 'abstained'
                           THEN 1 ELSE 0 END) AS n_abstained,
                  SUM(CASE WHEN qs.answer_shape = 'binary'
                            AND LOWER(TRIM(gt.response)) = 'no'
                            AND LOWER(TRIM(f.final_answer)) = 'yes'
                           THEN 1 ELSE 0 END) AS n_fp,
                  SUM(CASE WHEN qs.answer_shape = 'binary'
                            AND LOWER(TRIM(gt.response)) = 'no'
                            AND f.final_answer IS NOT NULL
                            AND LOWER(TRIM(f.final_answer)) NOT IN ('inconclusive', '')
                           THEN 1 ELSE 0 END) AS n_committed_neg
                FROM {_LATEST_FINALS} f
                LEFT JOIN ground_truth gt
                  ON gt.question_id = f.question_id
                 AND gt.country_code = f.country_code
                LEFT JOIN questions qs
                  ON qs.question_id = f.question_id
                WHERE {MAIN_RUNS_FILTER}
                  AND gt.response IS NOT NULL AND TRIM(gt.response) <> ''
                GROUP BY 1""",
        ).fetchall()
    order = {"confirm": 0, "complement": 1, "change": 2}
    out = []
    for r in rows:
        n_match = int(r["n_match"] or 0)
        n_near = int(r["n_near_match"] or 0)
        n_differ = int(r["n_differ"] or 0)
        n_abst = int(r["n_abstained"] or 0)
        denom = n_match + n_near + n_differ + n_abst
        n_neg = int(r["n_committed_neg"] or 0)
        n_fp = int(r["n_fp"] or 0)
        out.append({
            "decision": r["decision"],
            "n_finalised": int(r["n_finalised"] or 0),
            "n_match": n_match,
            "n_near_match": n_near,
            "n_differ": n_differ,
            "n_abstained": n_abst,
            "accuracy": (n_match / denom) if denom else None,
            "abstention_rate": (n_abst / denom) if denom else None,
            "n_fp": n_fp,
            "n_committed_neg": n_neg,
            "fp_rate": (n_fp / n_neg) if n_neg else None,
        })
    out.sort(key=lambda d: order.get(d["decision"], 9))
    return out


def ground_truth_count() -> int:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM ground_truth"
        ).fetchone()
    return int(row[0] or 0)


_SWARM_TABLES_TO_CLEAR = [
    "phase2_final",
    "phase2_adjudications",
    "phase2_verifier_runs",
    "phase2_researcher_runs",
    "subtrio_status",
]


def pair_row_counts(question_id: str, country_code: str) -> dict[str, int]:
    """Row counts per swarm table for a (question, country) pair.

    Useful for showing the user what `delete_pair` is about to wipe.
    `claude_usage_log` is intentionally excluded: it's the cost-audit
    record and is keyed by `subtrio_id`, not by question/country, so
    it stays put.
    """
    counts: dict[str, int] = {}
    with _conn() as conn:
        for table in _SWARM_TABLES_TO_CLEAR:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE question_id = ? AND country_code = ?",
                (question_id, country_code),
            ).fetchone()
            counts[table] = int(row[0] or 0)
    return counts


def delete_pair(question_id: str, country_code: str) -> dict[str, int]:
    """Delete every swarm row for a (question, country) pair.

    Returns the number of rows deleted per table. `claude_usage_log`
    is intentionally NOT touched (cost audit preserved).
    """
    deleted: dict[str, int] = {}
    with _conn() as conn:
        for table in _SWARM_TABLES_TO_CLEAR:
            cur = conn.execute(
                f"DELETE FROM {table} "
                f"WHERE question_id = ? AND country_code = ?",
                (question_id, country_code),
            )
            deleted[table] = cur.rowcount
        conn.commit()
    return deleted


# Tables a single in-flight run writes to, keyed by pair_run_id
# (== subtrio_id). Ordered children-first so foreign references go
# before the parent status row. claude_usage_log is omitted on purpose:
# it is the cost-audit receipt and stays put, same as delete_pair.
_RUN_TABLES_TO_CLEAR = [
    "phase2_final",
    "phase2_adjudications",
    "phase2_verifier_runs",
    "phase2_researcher_runs",
]


def _pid_is_coordinator(pid: int, subtrio_id: str) -> bool:
    """Confirm `pid` is the coordinator process for this subtrio.

    Guards against PID reuse: between the status row being written and
    the user clicking cancel, the recorded PID could have been recycled
    by an unrelated process. We only signal a process whose command line
    is the coordinator running this exact subtrio. `-ww` stops `ps`
    truncating the command, so the subtrio UUID is always visible.
    """
    try:
        out = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception:  # noqa: BLE001
        return False
    return "run_coordinator" in out and subtrio_id in out


def _terminate_pid(pid: int, *, grace_seconds: float = 3.0) -> bool:
    """Best-effort stop: SIGTERM, escalate to SIGKILL if it lingers.

    Returns True once the process is gone (or was never running). The
    coordinator installs no signal handler, so SIGTERM kills it outright
    without running any teardown, meaning it cannot rewrite a status row
    after we delete one.
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return True


def cancel_subtrio(subtrio_id: str) -> dict:
    """Cancel one in-flight subtrio and wipe what it has written so far.

    Kills the coordinator process recorded in
    `subtrio_status.process_pid` (after verifying the PID still belongs
    to that coordinator), waits for it to exit, then deletes every row
    keyed to this run's `pair_run_id` across the phase2_* tables and the
    `subtrio_status` row itself. Historical runs of the same
    (question, country) pair are left alone because deletion is scoped
    by subtrio_id, not by question/country. `claude_usage_log` is
    preserved so the cost receipt survives.

    Returns {"killed": bool, "pid": int | None, "deleted": {table: n}}.
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT process_pid FROM subtrio_status WHERE subtrio_id = ?",
            (subtrio_id,),
        ).fetchone()
    pid = (
        int(row["process_pid"])
        if row is not None and row["process_pid"] is not None
        else None
    )

    killed = False
    if pid is not None and _pid_is_coordinator(pid, subtrio_id):
        killed = _terminate_pid(pid)

    deleted: dict[str, int] = {}
    with _conn() as conn:
        for table in _RUN_TABLES_TO_CLEAR:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE pair_run_id = ?",
                (subtrio_id,),
            )
            deleted[table] = cur.rowcount
        cur = conn.execute(
            "DELETE FROM subtrio_status WHERE subtrio_id = ?",
            (subtrio_id,),
        )
        deleted["subtrio_status"] = cur.rowcount
        conn.commit()

    return {"killed": killed, "pid": pid, "deleted": deleted}


def coverage_grid() -> pd.DataFrame:
    """Long-format DataFrame of every ODMI (question, country) pair
    (5,148 rows) left-joined with the latest swarm final and match
    status. Source of truth for the Database page.

    Columns: question_id, country_code, country_name, dimension,
    indicator, odmi_response, awarded_score, max_score, swarm_answer,
    terminal_status, last_run, match_status, swarm_runs (count).
    """
    return read_sql(
        f"""
        WITH latest_finals AS (
            SELECT f.*,
                   ROW_NUMBER() OVER (
                     PARTITION BY f.question_id, f.country_code
                     ORDER BY f.id DESC
                   ) AS rn,
                   COUNT(*) OVER (
                     PARTITION BY f.question_id, f.country_code
                   ) AS n_runs
            FROM phase2_final f
            WHERE {MAIN_RUNS_FILTER}
        )
        SELECT
          gt.question_id, gt.country_code, gt.country_name,
          gt.dimension, gt.indicator,
          gt.response       AS odmi_response,
          gt.awarded_score, gt.max_score,
          f.final_answer    AS swarm_answer,
          f.terminal_status,
          f.created_at      AS last_run,
          {_MATCH_STATUS_SQL} AS match_status,
          COALESCE(f.n_runs, 0) AS swarm_runs
        FROM ground_truth gt
        LEFT JOIN latest_finals f
          ON f.question_id = gt.question_id
         AND f.country_code = gt.country_code
         AND f.rn = 1
        ORDER BY gt.country_code, gt.question_id
        """
    )


def already_finalised(
    question_ids: list[str], country_codes: list[str]
) -> pd.DataFrame:
    """For each requested (qid, cc) pair, return a row if at least one
    `phase2_final` row exists. Columns: question_id, country_code,
    n_runs, last_terminal_status, last_match_status, last_created_at.
    Used by the Run Console to warn before re-running.
    """
    if not question_ids or not country_codes:
        return pd.DataFrame(
            columns=[
                "question_id", "country_code", "n_runs",
                "last_terminal_status", "last_match_status",
                "last_created_at",
            ]
        )
    q_marks = ",".join("?" for _ in question_ids)
    c_marks = ",".join("?" for _ in country_codes)
    return read_sql(
        f"""
        WITH per_pair AS (
            SELECT f.question_id, f.country_code,
                   f.terminal_status, f.created_at,
                   {_MATCH_STATUS_SQL} AS match_status,
                   ROW_NUMBER() OVER (
                     PARTITION BY f.question_id, f.country_code
                     ORDER BY f.id DESC
                   ) AS rn,
                   COUNT(*) OVER (
                     PARTITION BY f.question_id, f.country_code
                   ) AS n_runs
            FROM phase2_final f
            LEFT JOIN ground_truth gt
              ON gt.question_id = f.question_id
             AND gt.country_code = f.country_code
            WHERE f.question_id IN ({q_marks})
              AND f.country_code IN ({c_marks})
              AND {MAIN_RUNS_FILTER}
        )
        SELECT question_id, country_code, n_runs,
               terminal_status AS last_terminal_status,
               match_status    AS last_match_status,
               created_at      AS last_created_at
        FROM per_pair
        WHERE rn = 1
        ORDER BY question_id, country_code
        """,
        tuple(question_ids) + tuple(country_codes),
    )


# Claude usage / cost

def rolling_window_summary(window_hours: float = 5.0) -> dict:
    """Aggregate Claude usage for the last `window_hours`."""
    cutoff = (datetime.utcnow() - timedelta(hours=window_hours))\
        .isoformat(timespec="seconds") + "Z"
    with _conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n_calls,
                      COALESCE(SUM(input_tokens), 0) AS in_tok,
                      COALESCE(SUM(output_tokens), 0) AS out_tok,
                      COALESCE(SUM(estimated_cost_usd), 0.0) AS cost,
                      COALESCE(SUM(rate_limited), 0) AS rate_limit_hits,
                      MIN(timestamp) AS oldest
               FROM claude_usage_log WHERE timestamp > ?""",
            (cutoff,),
        ).fetchone()
    return dict(row) if row else {
        "n_calls": 0, "in_tok": 0, "out_tok": 0,
        "cost": 0.0, "rate_limit_hits": 0, "oldest": None,
    }


def usage_log(limit: int = 200) -> pd.DataFrame:
    return read_sql(
        f"""SELECT * FROM claude_usage_log
            ORDER BY id DESC LIMIT {int(limit)}"""
    )


def cost_by_day(days: int = 30) -> pd.DataFrame:
    return read_sql(
        f"""SELECT substr(timestamp, 1, 10) AS day,
                   COUNT(*) AS n_calls,
                   SUM(input_tokens) AS in_tok,
                   SUM(output_tokens) AS out_tok,
                   SUM(estimated_cost_usd) AS cost
            FROM claude_usage_log
            WHERE timestamp > datetime('now', '-{int(days)} days')
            GROUP BY day ORDER BY day"""
    )


# Questions

def all_questions() -> pd.DataFrame:
    """Read from the questions table; fallback to JSON if empty."""
    df = read_sql("SELECT * FROM questions ORDER BY id")
    if len(df) > 0:
        return df
    # Fallback: load from JSON.
    questions_json = REPO_ROOT / "data" / "questions" / "odmi_2025_questions.json"
    if questions_json.exists():
        records = json.loads(questions_json.read_text())
        return pd.DataFrame(records)
    return pd.DataFrame()


# Hand-marks

def hand_marks() -> pd.DataFrame:
    return read_sql("SELECT * FROM hand_marks ORDER BY country_code, question_id")


# Model defaults + analytics

def model_defaults() -> pd.DataFrame:
    return read_sql("SELECT * FROM model_defaults")


def set_model_default(role: str, model: str) -> None:
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO model_defaults
               (agent_role, model, updated_at, updated_by)
               VALUES (?, ?, ?, 'dashboard')""",
            (role, model, now),
        )
        conn.commit()


def model_analytics_researcher() -> pd.DataFrame:
    return read_sql(
        """SELECT model_version,
                  COUNT(*) AS n,
                  AVG(answer_confidence) AS avg_answer_conf,
                  AVG(retrieval_confidence) AS avg_retr_conf,
                  AVG(estimated_cost_usd) AS avg_cost,
                  AVG(wall_clock_ms) AS avg_ms
           FROM phase2_researcher_runs
           WHERE model_version IS NOT NULL AND model_version != 'unknown'
           GROUP BY model_version
           ORDER BY n DESC"""
    )


def model_analytics_verifier() -> pd.DataFrame:
    return read_sql(
        """SELECT model_version, strategy_label,
                  COUNT(*) AS n,
                  AVG(CASE WHEN verdict='pass' THEN 1.0 ELSE 0.0 END) AS pass_rate,
                  AVG(verifier_confidence) AS avg_conf,
                  AVG(estimated_cost_usd) AS avg_cost
           FROM phase2_verifier_runs
           WHERE model_version IS NOT NULL AND model_version != 'unknown'
           GROUP BY model_version, strategy_label
           ORDER BY n DESC"""
    )


# Prompts

def prompt_versions() -> pd.DataFrame:
    return read_sql(
        """SELECT id, prompt_name, version, description, created_at
           FROM prompt_versions ORDER BY id"""
    )


def prompt_text(prompt_id: int) -> Optional[str]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT prompt_text FROM prompt_versions WHERE id = ?",
            (prompt_id,),
        ).fetchone()
    return row[0] if row else None
