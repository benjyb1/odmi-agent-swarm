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
import sqlite3
import sys
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


# ============================================================
# Subtrio status
# ============================================================

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


# ============================================================
# Phase 2 results
# ============================================================

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
      WHEN LOWER(TRIM(f.final_answer)) = LOWER(TRIM(gt.response))
        THEN 'match'
      WHEN LOWER(TRIM(f.final_answer)) = 'yes'
           AND (LOWER(TRIM(gt.response)) LIKE 'yes%')
        THEN 'match'
      WHEN LOWER(TRIM(f.final_answer)) = 'no'
           AND LOWER(TRIM(gt.response)) = 'no'
        THEN 'match'
      -- D28: adjacent-band miss on an ordered shape counts as
      -- near_match, not differ. The questions table carries the
      -- ordered list of labels per question; we look up the indices
      -- of the swarm and ODMI answers and check that they are one
      -- step apart.
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
        FROM phase2_final f
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
        FROM phase2_final f
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
            FROM phase2_final f
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

    Returns {n_finalised, n_match, n_near_match, n_differ, n_no_truth,
    accuracy, accuracy_within_one_band}.

    `accuracy` is exact matches / (matches + near_matches + differs).
    `accuracy_within_one_band` counts a near_match as correct,
    representing how often the swarm's band is at most one step off
    ODMI's answer. Both exclude pairs without a ground-truth row.
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
                  SUM(CASE WHEN ({_MATCH_STATUS_SQL}) IN
                           ('no_ground_truth', 'no_swarm_answer')
                           THEN 1 ELSE 0 END) AS n_no_truth
                FROM phase2_final f
                LEFT JOIN ground_truth gt
                  ON gt.question_id = f.question_id
                 AND gt.country_code = f.country_code
                WHERE {MAIN_RUNS_FILTER}""",
        ).fetchone()
    n_finalised = int(row["n_finalised"] or 0)
    n_match = int(row["n_match"] or 0)
    n_near_match = int(row["n_near_match"] or 0)
    n_differ = int(row["n_differ"] or 0)
    n_no_truth = int(row["n_no_truth"] or 0)
    denom = n_match + n_near_match + n_differ
    accuracy = (n_match / denom) if denom > 0 else None
    accuracy_within_one_band = (
        (n_match + n_near_match) / denom if denom > 0 else None
    )
    return {
        "n_finalised": n_finalised,
        "n_match": n_match,
        "n_near_match": n_near_match,
        "n_differ": n_differ,
        "n_no_truth": n_no_truth,
        "accuracy": accuracy,
        "accuracy_within_one_band": accuracy_within_one_band,
    }


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


# ============================================================
# Claude usage / cost
# ============================================================

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


# ============================================================
# Questions
# ============================================================

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


# ============================================================
# Hand-marks
# ============================================================

def hand_marks() -> pd.DataFrame:
    return read_sql("SELECT * FROM hand_marks ORDER BY country_code, question_id")


# ============================================================
# Model defaults + analytics
# ============================================================

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


# ============================================================
# Prompts
# ============================================================

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
