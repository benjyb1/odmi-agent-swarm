"""Create the ODMI SQLite database with the full schema.

Run: uv run python scripts/setup_sqlite.py
Creates or refreshes: data/odmi.db

This is the authoritative schema definition. Any change here must be
reflected in `docs/AGENT_DESIGN.md` and recorded as a numbered decision
in `docs/SPEC.md`. The decisions baked into this schema:

  D5  every LLM call links to a prompt_versions row
  D6  three-dimension rubric (evidence, determinism, complexity 0-3)
  D8  hand-marks are the authoritative rubric scores (not LLM-produced)
  D9  hand-marks lock via git commit SHA in `locked_by_commit`
  D12 token/latency on every LLM call for the accuracy-cost surface
  D15 Verifier strategy is logged as `strategy_label` per row
  D16 Adjudicator is a Coordinator-internal call with its own table
  Q6  cost columns on every per-call table
  Q7  split tables for researcher/verifier/adjudications/final
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "odmi.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

-- ============================================================
-- Prompt versioning (D5): every score links to the exact prompt
-- that produced it. Iterating prompts inserts new rows; old runs
-- stay traceable to the prompt they actually saw.
-- ============================================================
CREATE TABLE prompt_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_name     TEXT NOT NULL,
    version         INTEGER NOT NULL,
    prompt_text     TEXT NOT NULL,
    description     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE (prompt_name, version)
);

-- ============================================================
-- ODMI question bank parsed from the spreadsheet (D2 cycle).
-- ============================================================
CREATE TABLE questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id     TEXT NOT NULL UNIQUE,
    dimension       TEXT NOT NULL CHECK (dimension IN ('Policy', 'Portal', 'Quality', 'Impact')),
    indicator       TEXT NOT NULL,
    question_text   TEXT NOT NULL,
    response_scoring TEXT,
    in_subset       INTEGER NOT NULL DEFAULT 0,
    answer_shape    TEXT,
    allowed_answers TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_questions_answer_shape ON questions(answer_shape);

-- ============================================================
-- Hand-marks (D8, D9, D10): the audit-trail evidence behind the
-- rubric. CSV is the human-editable workspace; this table is the
-- queryable mirror. locked_by_commit is the git SHA that
-- committed the row to the CSV (D9 lock rule).
-- ============================================================
CREATE TABLE hand_marks (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id                 TEXT NOT NULL,
    country_code                TEXT NOT NULL,

    evidence_score              INTEGER NOT NULL CHECK (evidence_score BETWEEN 0 AND 3),
    evidence_justification      TEXT NOT NULL,
    determinism_score           INTEGER NOT NULL CHECK (determinism_score BETWEEN 0 AND 3),
    determinism_justification   TEXT NOT NULL,
    complexity_score            INTEGER NOT NULL CHECK (complexity_score BETWEEN 0 AND 3),
    complexity_justification    TEXT NOT NULL,
    composite_score             INTEGER NOT NULL,
    tier                        TEXT NOT NULL CHECK (tier IN ('Highly Likely', 'Likely', 'Unlikely', 'Very Unlikely')),

    search_queries              TEXT,
    sources_found               TEXT,
    answer_obtained             TEXT,

    marker                      TEXT NOT NULL,
    marked_at                   TEXT NOT NULL,
    locked_by_commit            TEXT,
    superseded_by               INTEGER REFERENCES hand_marks(id),
    notes                       TEXT,

    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Phase 1 classifications (off the critical path per D8, retained
-- for the optional post-hoc classifier experiment described in
-- AGENT_DESIGN.md section 7). Cost columns added per D12.
-- ============================================================
CREATE TABLE phase1_classifications (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id                 TEXT NOT NULL,
    question_text               TEXT NOT NULL,
    dimension                   TEXT NOT NULL,
    country_code                TEXT NOT NULL,

    evidence_score              INTEGER NOT NULL CHECK (evidence_score BETWEEN 0 AND 3),
    determinism_score           INTEGER NOT NULL CHECK (determinism_score BETWEEN 0 AND 3),
    complexity_score            INTEGER NOT NULL CHECK (complexity_score BETWEEN 0 AND 3),
    composite_score             INTEGER NOT NULL,
    tier                        TEXT NOT NULL CHECK (tier IN ('Highly Likely', 'Likely', 'Unlikely', 'Very Unlikely')),

    evidence_justification      TEXT NOT NULL,
    determinism_justification   TEXT NOT NULL,
    complexity_justification    TEXT NOT NULL,

    language_used               TEXT NOT NULL DEFAULT 'en',
    prompt_version_id           INTEGER REFERENCES prompt_versions(id),
    model_version               TEXT NOT NULL,
    raw_llm_response            TEXT,

    -- D12 cost tracking
    input_tokens                INTEGER,
    output_tokens               INTEGER,
    wall_clock_ms               INTEGER,
    estimated_cost_usd          REAL,
    condition_label             TEXT,

    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Phase 2: Researcher runs. One row per Researcher attempt
-- (multiple per pair_run_id if the Verifier triggers retries).
-- ============================================================
CREATE TABLE phase2_researcher_runs (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      TEXT NOT NULL,                 -- batch UUID
    pair_run_id                 TEXT NOT NULL,                 -- per-pair UUID
    question_id                 TEXT NOT NULL,
    country_code                TEXT NOT NULL,
    retry_count                 INTEGER NOT NULL,              -- 0, 1, 2, 3

    answer                      TEXT,
    answer_explanation          TEXT,
    evidence_quote              TEXT,
    source_url                  TEXT,
    retrieval_confidence        REAL,
    answer_confidence           REAL,
    search_queries_used         TEXT,                          -- JSON list
    fetched_urls                TEXT,                          -- JSON list
    search_provider_calls       TEXT,                          -- JSON list: per-search {provider, ms, results, ok, error}
    domain_trust_score          REAL,
    language_route_used         TEXT,
    notes                       TEXT,

    failure_mode                TEXT,                          -- null if success

    -- D12 cost tracking
    input_tokens                INTEGER,
    output_tokens               INTEGER,
    wall_clock_ms               INTEGER,
    estimated_cost_usd          REAL,
    condition_label             TEXT,                          -- e.g. baseline / prompt-compressed

    prompt_version_id           INTEGER REFERENCES prompt_versions(id),
    model_version               TEXT NOT NULL,

    raw_response                TEXT,
    experiment_id               TEXT,                          -- D27: NULL = main run, otherwise tag from experiments table
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Phase 2: Verifier runs. The strategy_label (D15) records which
-- of the four prompt strategies the Verifier used on this row.
-- ============================================================
CREATE TABLE phase2_verifier_runs (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      TEXT NOT NULL,
    pair_run_id                 TEXT NOT NULL,
    question_id                 TEXT NOT NULL,
    country_code                TEXT NOT NULL,
    retry_count                 INTEGER NOT NULL,
    strategy_label              TEXT NOT NULL CHECK (strategy_label IN (
                                    'verifier-disprove',
                                    'verifier-negation',
                                    'verifier-steelman',
                                    'verifier-blind'
                                )),

    researcher_run_id           INTEGER NOT NULL REFERENCES phase2_researcher_runs(id),

    verdict                     TEXT NOT NULL CHECK (verdict IN ('pass', 'fail')),
    verifier_answer             TEXT,
    verifier_confidence         REAL,

    substring_check_result      TEXT NOT NULL CHECK (substring_check_result IN ('pass', 'fail', 'not_attempted')),
    substring_check_notes       TEXT,

    independent_search_queries  TEXT,                          -- JSON list
    independent_evidence        TEXT,                          -- JSON list of snippets

    rejection_reason            TEXT,
    counter_evidence_quote      TEXT,
    counter_source_url          TEXT,
    suggested_search_query      TEXT,

    failure_mode                TEXT,

    input_tokens                INTEGER,
    output_tokens               INTEGER,
    wall_clock_ms               INTEGER,
    estimated_cost_usd          REAL,
    condition_label             TEXT,

    prompt_version_id           INTEGER REFERENCES prompt_versions(id),
    model_version               TEXT NOT NULL,

    raw_response                TEXT,
    experiment_id               TEXT,                          -- D27
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Phase 2: Adjudications (D16). Fires only when retry_count == 3
-- with no convergence. One row per pair if it fires; zero rows
-- if the swarm converged earlier.
-- ============================================================
CREATE TABLE phase2_adjudications (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      TEXT NOT NULL,
    pair_run_id                 TEXT NOT NULL,
    question_id                 TEXT NOT NULL,
    country_code                TEXT NOT NULL,

    adjudicator_verdict         TEXT NOT NULL CHECK (adjudicator_verdict IN (
                                    'researcher_correct',
                                    'verifier_correct',
                                    'neither',
                                    'escalate_human'
                                )),
    adjudicator_answer          TEXT,
    adjudicator_confidence      REAL,
    adjudicator_reasoning       TEXT NOT NULL,
    chosen_source_url           TEXT,
    chosen_evidence_quote       TEXT,

    failure_mode                TEXT,

    input_tokens                INTEGER,
    output_tokens               INTEGER,
    wall_clock_ms               INTEGER,
    estimated_cost_usd          REAL,

    prompt_version_id           INTEGER REFERENCES prompt_versions(id),
    model_version               TEXT NOT NULL,

    raw_response                TEXT,
    experiment_id               TEXT,                          -- D27
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Phase 2: Final per-pair outcome. One row per (run_id, pair_run_id).
-- This is what dashboards and the dissertation read.
-- ============================================================
CREATE TABLE phase2_final (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      TEXT NOT NULL,
    pair_run_id                 TEXT NOT NULL UNIQUE,
    question_id                 TEXT NOT NULL,
    country_code                TEXT NOT NULL,

    terminal_status             TEXT NOT NULL CHECK (terminal_status IN (
                                    'accepted_by_verifier',
                                    'accepted_by_adjudicator',
                                    'escalated_captcha',
                                    'escalated_adjudicator',
                                    'agent_failure'
                                )),

    final_answer                TEXT,
    final_answer_explanation    TEXT,
    final_evidence_quote        TEXT,
    final_source_url            TEXT,
    final_retrieval_confidence  REAL,
    final_answer_confidence     REAL,

    retry_count                 INTEGER NOT NULL,
    adjudicator_involved        INTEGER NOT NULL DEFAULT 0,
    captcha_escalated           INTEGER NOT NULL DEFAULT 0,

    cumulative_input_tokens     INTEGER NOT NULL DEFAULT 0,
    cumulative_output_tokens    INTEGER NOT NULL DEFAULT 0,
    cumulative_wall_clock_ms    INTEGER NOT NULL DEFAULT 0,
    cumulative_cost_usd         REAL,

    final_failure_reason        TEXT,

    experiment_id               TEXT,                          -- D27
    created_at                  TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Live subtrio state (D19/D21 — dashboard design 2026-05-12).
-- One row per subtrio. Mirrors phase2_final.terminal_status for
-- final_verdict so the dashboard does not have to translate enums.
-- ============================================================
CREATE TABLE subtrio_status (
    subtrio_id              TEXT PRIMARY KEY,
    batch_id                TEXT NOT NULL,
    question_id             TEXT NOT NULL,
    country_code            TEXT NOT NULL,
    stage                   TEXT,
    substage                TEXT,
    retry_count             INTEGER DEFAULT 0,
    started_at              TEXT,
    updated_at              TEXT,
    ended_at                TEXT,
    final_verdict           TEXT,
    cumulative_cost_usd     REAL,
    last_message            TEXT,
    process_pid             INTEGER,
    researcher_model        TEXT,
    verifier_model          TEXT,
    adjudicator_model       TEXT,
    verifier_strategy       TEXT,
    final_failure_reason    TEXT,
    experiment_id           TEXT,                              -- D27
    created_at              TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Claude usage log (D20 — every LLM call, for the rolling 5-h window).
-- ============================================================
CREATE TABLE claude_usage_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    model               TEXT NOT NULL,
    input_tokens        INTEGER NOT NULL,
    output_tokens       INTEGER NOT NULL,
    estimated_cost_usd  REAL,
    rate_limited        INTEGER DEFAULT 0,
    context             TEXT,
    subtrio_id          TEXT
);

-- ============================================================
-- Default model assignment per agent role (D21).
-- Only top-level roles. Query-gen micro-calls inherit the parent.
-- ============================================================
CREATE TABLE model_defaults (
    agent_role          TEXT PRIMARY KEY CHECK (agent_role IN (
                            'researcher', 'verifier', 'adjudicator'
                        )),
    model               TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    updated_by          TEXT
);

-- ============================================================
-- Language confidence (Phase B routing decisions).
-- ============================================================
CREATE TABLE language_confidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    language            TEXT NOT NULL,
    benchmark_question  TEXT NOT NULL,
    native_accuracy     REAL,
    deepl_accuracy      REAL,
    routing_decision    TEXT CHECK (routing_decision IN ('native', 'deepl', 'human_required')),
    tested_at           TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Experiments registry (D27). Tags a set of run rows across
-- subtrio_status, phase2_*, etc. so ablations and condition
-- comparisons stay isolated from main dissertation results.
-- The `conditions` column is a JSON list of per-condition specs
-- (label + overrides for model, strategy, prompt_version_id).
-- ============================================================
CREATE TABLE experiments (
    experiment_id       TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT,
    conditions          TEXT NOT NULL,                         -- JSON list
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- Indices for the queries dashboards and analysis will run.
-- ============================================================
CREATE INDEX idx_handmarks_question_country     ON hand_marks(question_id, country_code);
CREATE INDEX idx_handmarks_locked               ON hand_marks(locked_by_commit);

CREATE INDEX idx_p2res_pair                     ON phase2_researcher_runs(pair_run_id);
CREATE INDEX idx_p2res_run                      ON phase2_researcher_runs(run_id);
CREATE INDEX idx_p2res_question_country         ON phase2_researcher_runs(question_id, country_code);

CREATE INDEX idx_p2ver_pair                     ON phase2_verifier_runs(pair_run_id);
CREATE INDEX idx_p2ver_strategy                 ON phase2_verifier_runs(strategy_label);

CREATE INDEX idx_p2adj_pair                     ON phase2_adjudications(pair_run_id);

CREATE INDEX idx_p2final_status                 ON phase2_final(terminal_status);
CREATE INDEX idx_p2final_run                    ON phase2_final(run_id);

CREATE INDEX idx_classifications_country        ON phase1_classifications(country_code);
CREATE INDEX idx_classifications_tier           ON phase1_classifications(tier);

CREATE INDEX idx_subtrio_status_batch           ON subtrio_status(batch_id);
CREATE INDEX idx_subtrio_status_stage           ON subtrio_status(stage);
CREATE INDEX idx_subtrio_status_question_country ON subtrio_status(question_id, country_code);

CREATE INDEX idx_claude_usage_ts                ON claude_usage_log(timestamp);
CREATE INDEX idx_claude_usage_subtrio            ON claude_usage_log(subtrio_id);

-- D27 experiment isolation
CREATE INDEX idx_subtrio_status_experiment       ON subtrio_status(experiment_id);
CREATE INDEX idx_p2final_experiment              ON phase2_final(experiment_id);
CREATE INDEX idx_p2res_experiment                ON phase2_researcher_runs(experiment_id);
CREATE INDEX idx_p2ver_experiment                ON phase2_verifier_runs(experiment_id);
CREATE INDEX idx_p2adj_experiment                ON phase2_adjudications(experiment_id);
"""

TABLES = (
    "prompt_versions",
    "questions",
    "hand_marks",
    "phase1_classifications",
    "phase2_researcher_runs",
    "phase2_verifier_runs",
    "phase2_adjudications",
    "phase2_final",
    "subtrio_status",
    "claude_usage_log",
    "model_defaults",
    "language_confidence",
    "experiments",
)


def create_database(force: bool = False) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists() and not force:
        print(f"Database already exists at {DB_PATH}")
        print("Run with --force to drop and recreate (data will be lost).")
        return

    if DB_PATH.exists() and force:
        # Also remove the WAL/SHM files so the new DB starts clean.
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = DB_PATH.with_name(DB_PATH.name + suffix) if suffix else DB_PATH
            if p.exists():
                p.unlink()
        print(f"Dropped existing database at {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")
    print(f"Tables: {', '.join(TABLES)}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Create the ODMI SQLite database")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Drop the existing database and recreate. All data is lost.",
    )
    args = parser.parse_args()
    create_database(force=args.force)


if __name__ == "__main__":
    main()
