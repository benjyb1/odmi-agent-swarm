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
