-- ODMI Agent Swarm — Supabase Schema
-- Run this against a fresh Supabase project.

-- ============================================================
-- Prompt versioning — tracks every iteration of every prompt
-- so we can trace which prompt version produced which scores.
-- ============================================================
create table prompt_versions (
    id              bigint generated always as identity primary key,
    prompt_name     text not null,          -- e.g. 'phase1_classifier', 'researcher', 'verifier'
    version         int not null,
    prompt_text     text not null,
    description     text,                   -- what changed and why
    created_at      timestamptz default now(),
    unique (prompt_name, version)
);

-- ============================================================
-- Phase 1: Question classification results
-- ============================================================
create table phase1_classifications (
    id                  bigint generated always as identity primary key,
    question_id         text not null,          -- e.g. 'P1', 'Q3', 'I2'
    question_text       text not null,
    dimension           text not null,          -- Policy, Portal, Quality, Impact
    country             text not null,          -- ISO 3166-1 alpha-2 (e.g. 'FR')

    -- Rubric scores (0-3 each)
    evidence_score      int not null check (evidence_score between 0 and 3),
    determinism_score   int not null check (determinism_score between 0 and 3),
    complexity_score    int not null check (complexity_score between 0 and 3),
    composite_score     int generated always as (evidence_score + determinism_score + complexity_score) stored,

    -- Tier derived from composite
    tier                text not null check (tier in ('Highly Likely', 'Likely', 'Unlikely', 'Very Unlikely')),

    -- Justifications — one per dimension so we can audit the reasoning
    evidence_justification      text not null,
    determinism_justification   text not null,
    complexity_justification    text not null,

    -- Metadata
    language_used       text not null default 'en',
    prompt_version_id   bigint references prompt_versions(id),
    model_version       text not null,          -- e.g. 'claude-opus-4-6'
    raw_llm_response    text,                   -- full response for reproducibility
    created_at          timestamptz default now()
);

-- ============================================================
-- Phase 2: Swarm run results
-- ============================================================
create table phase2_runs (
    id                      bigint generated always as identity primary key,
    run_id                  uuid not null default gen_random_uuid(),
    question_id             text not null,
    country                 text not null,
    tier                    text not null,

    -- Researcher output
    researcher_answer       text,
    researcher_evidence     text,
    researcher_url          text,
    retrieval_confidence    real check (retrieval_confidence between 0 and 1),

    -- Verifier output
    verifier_verdict        text check (verifier_verdict in ('pass', 'fail')),
    verifier_reasoning      text,
    answer_confidence       real check (answer_confidence between 0 and 1),

    -- Loop metadata
    retry_count             int not null default 0,
    coordinator_feedback    text[],              -- feedback sent on each retry

    -- Final output
    final_answer            text,
    final_confidence        real check (final_confidence between 0 and 1),
    source_urls             text[],

    -- Prompt and model tracking
    researcher_prompt_version_id    bigint references prompt_versions(id),
    verifier_prompt_version_id      bigint references prompt_versions(id),
    model_version                   text not null,
    created_at                      timestamptz default now()
);

-- ============================================================
-- Language confidence table (Phase B)
-- ============================================================
create table language_confidence (
    id                  bigint generated always as identity primary key,
    language            text not null,          -- ISO 639-1 (e.g. 'et', 'hu')
    benchmark_question  text not null,
    native_accuracy     real,
    deepl_accuracy      real,
    routing_decision    text check (routing_decision in ('native', 'deepl', 'manual')),
    tested_at           timestamptz default now()
);

-- ============================================================
-- ODMI question bank — parsed from the spreadsheet
-- ============================================================
create table questions (
    id              bigint generated always as identity primary key,
    question_id     text not null unique,       -- generated ID like 'POL_01', 'POR_03'
    dimension       text not null check (dimension in ('Policy', 'Portal', 'Quality', 'Impact')),
    question_text   text not null,
    in_subset       boolean not null default false,   -- whether selected for Phase A testing
    created_at      timestamptz default now()
);

-- Indices for common queries
create index idx_classifications_country on phase1_classifications(country);
create index idx_classifications_dimension on phase1_classifications(dimension);
create index idx_classifications_tier on phase1_classifications(tier);
create index idx_runs_question_country on phase2_runs(question_id, country);
create index idx_runs_run_id on phase2_runs(run_id);
