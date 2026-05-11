"""
Create the ODMI SQLite database with all tables.

Run: uv run scripts/setup_sqlite.py
Creates: data/odmi.db
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "odmi.db"


def create_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists():
        print(f"Database already exists at {DB_PATH}")
        print("Delete it manually if you want a fresh start.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        -- ============================================================
        -- Prompt versioning — tracks every iteration of every prompt
        -- so we can trace which prompt version produced which scores.
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
        -- ODMI question bank — parsed from the spreadsheet
        -- ============================================================
        CREATE TABLE questions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id     TEXT NOT NULL UNIQUE,
            dimension       TEXT NOT NULL CHECK (dimension IN ('Policy', 'Portal', 'Quality', 'Impact')),
            question_text   TEXT NOT NULL,
            in_subset       INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        -- ============================================================
        -- Phase 1: Question classification results
        -- ============================================================
        CREATE TABLE phase1_classifications (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id         TEXT NOT NULL,
            question_text       TEXT NOT NULL,
            dimension           TEXT NOT NULL,
            country             TEXT NOT NULL,

            -- Rubric scores (0-3 each)
            evidence_score      INTEGER NOT NULL CHECK (evidence_score BETWEEN 0 AND 3),
            determinism_score   INTEGER NOT NULL CHECK (determinism_score BETWEEN 0 AND 3),
            complexity_score    INTEGER NOT NULL CHECK (complexity_score BETWEEN 0 AND 3),
            composite_score     INTEGER NOT NULL,

            -- Tier derived from composite
            tier                TEXT NOT NULL CHECK (tier IN ('Highly Likely', 'Likely', 'Unlikely', 'Very Unlikely')),

            -- Justifications — one per dimension so we can audit the reasoning
            evidence_justification      TEXT NOT NULL,
            determinism_justification   TEXT NOT NULL,
            complexity_justification    TEXT NOT NULL,

            -- Metadata
            language_used       TEXT NOT NULL DEFAULT 'en',
            prompt_version_id   INTEGER REFERENCES prompt_versions(id),
            model_version       TEXT NOT NULL,
            raw_llm_response    TEXT,
            created_at          TEXT DEFAULT (datetime('now'))
        );

        -- ============================================================
        -- Phase 2: Swarm run results
        -- ============================================================
        CREATE TABLE phase2_runs (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id                  TEXT NOT NULL,
            question_id             TEXT NOT NULL,
            country                 TEXT NOT NULL,
            tier                    TEXT NOT NULL,

            -- Researcher output
            researcher_answer       TEXT,
            researcher_evidence     TEXT,
            researcher_url          TEXT,
            retrieval_confidence    REAL CHECK (retrieval_confidence BETWEEN 0 AND 1),

            -- Verifier output
            verifier_verdict        TEXT CHECK (verifier_verdict IN ('pass', 'fail')),
            verifier_reasoning      TEXT,
            answer_confidence       REAL CHECK (answer_confidence BETWEEN 0 AND 1),

            -- Loop metadata
            retry_count             INTEGER NOT NULL DEFAULT 0,
            coordinator_feedback    TEXT,

            -- Final output
            final_answer            TEXT,
            final_confidence        REAL CHECK (final_confidence BETWEEN 0 AND 1),
            source_urls             TEXT,

            -- Prompt and model tracking
            researcher_prompt_version_id    INTEGER REFERENCES prompt_versions(id),
            verifier_prompt_version_id      INTEGER REFERENCES prompt_versions(id),
            model_version                   TEXT NOT NULL,
            created_at                      TEXT DEFAULT (datetime('now'))
        );

        -- ============================================================
        -- Language confidence table (Phase B)
        -- ============================================================
        CREATE TABLE language_confidence (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            language            TEXT NOT NULL,
            benchmark_question  TEXT NOT NULL,
            native_accuracy     REAL,
            deepl_accuracy      REAL,
            routing_decision    TEXT CHECK (routing_decision IN ('native', 'deepl', 'manual')),
            tested_at           TEXT DEFAULT (datetime('now'))
        );

        -- Indices for common queries
        CREATE INDEX idx_classifications_country ON phase1_classifications(country);
        CREATE INDEX idx_classifications_dimension ON phase1_classifications(dimension);
        CREATE INDEX idx_classifications_tier ON phase1_classifications(tier);
        CREATE INDEX idx_runs_question_country ON phase2_runs(question_id, country);
        CREATE INDEX idx_runs_run_id ON phase2_runs(run_id);
    """)

    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")
    print("Tables: prompt_versions, questions, phase1_classifications, phase2_runs, language_confidence")


if __name__ == "__main__":
    create_database()
