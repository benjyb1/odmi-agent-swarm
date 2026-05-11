"""Run Phase 1 classification for a given country and question subset.

Usage:
    uv run python scripts/run_phase1.py --country FR
    uv run python scripts/run_phase1.py --country FR --questions POL_01,POR_03,IMP_02
    uv run python scripts/run_phase1.py --country FR --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.classifier import (
    PROMPT_REGISTRY,
    AnswerabilityTier,
    ClassificationResult,
    RubricScore,
)

MODEL_VERSION = "claude-sonnet-4-20250514"
PROMPT_VERSION = 1
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "odmi.db"


def load_questions(path: str = "data/questions/odmi_2025_questions.json") -> list[dict]:
    """Load parsed questions from JSON."""
    p = Path(path)
    if not p.exists():
        print(f"Questions file not found: {p}")
        print("Run parse_questions.py first.")
        sys.exit(1)
    return json.loads(p.read_text())


def classify_question(
    question: dict,
    country: str,
    *,
    dry_run: bool = False,
) -> ClassificationResult | None:
    """Classify a single question against a country.

    In dry-run mode, prints the prompt without calling the API.
    """
    prompt_template = PROMPT_REGISTRY["phase1_classifier"][PROMPT_VERSION]
    prompt = prompt_template.format(
        country=country,
        question_text=question["question_text"],
    )

    if dry_run:
        print(f"\n{'='*60}")
        print(f"[DRY RUN] {question['question_id']} — {question['dimension']}")
        print(f"{'='*60}")
        print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
        return None

    # ── API call (routed through CLIProxyAPI → Claude Max plan) ──
    import anthropic

    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
    )

    response = client.messages.create(
        model=MODEL_VERSION,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text

    # Parse the JSON from the response — handle cases where the model
    # wraps JSON in markdown code fences
    json_text = raw.strip()
    if json_text.startswith("```"):
        # Strip code fences
        lines = json_text.split("\n")
        json_text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        )

    score = RubricScore.model_validate_json(json_text)

    return ClassificationResult(
        question_id=question["question_id"],
        question_text=question["question_text"],
        dimension=question["dimension"],
        country=country,
        score=score,
        language_used="en",
        model_version=MODEL_VERSION,
        prompt_version=PROMPT_VERSION,
        raw_response=raw,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def save_to_db(result: ClassificationResult) -> None:
    """Insert a classification result into the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")

    row = result.to_db_row()
    conn.execute(
        """INSERT INTO phase1_classifications (
            question_id, question_text, dimension, country,
            evidence_score, determinism_score, complexity_score,
            composite_score, tier,
            evidence_justification, determinism_justification, complexity_justification,
            language_used, prompt_version_id, model_version,
            raw_llm_response, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["question_id"],
            row["question_text"],
            row["dimension"],
            row["country"],
            row["evidence_score"],
            row["determinism_score"],
            row["complexity_score"],
            row["evidence_score"] + row["determinism_score"] + row["complexity_score"],
            row["tier"],
            row["evidence_justification"],
            row["determinism_justification"],
            row["complexity_justification"],
            row["language_used"],
            None,  # prompt_version_id — will link once we insert the prompt
            row["model_version"],
            row["raw_llm_response"],
            row["created_at"],
        ),
    )
    conn.commit()
    conn.close()


def ensure_prompt_version_logged() -> None:
    """Make sure the current prompt version is recorded in the database."""
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute(
        "SELECT id FROM prompt_versions WHERE prompt_name = ? AND version = ?",
        ("phase1_classifier", PROMPT_VERSION),
    ).fetchone()

    if not existing:
        prompt_text = PROMPT_REGISTRY["phase1_classifier"][PROMPT_VERSION]
        conn.execute(
            "INSERT INTO prompt_versions (prompt_name, version, prompt_text, description) VALUES (?, ?, ?, ?)",
            ("phase1_classifier", PROMPT_VERSION, prompt_text, "Initial 3-dimension rubric prompt"),
        )
        conn.commit()
        print(f"Logged prompt version {PROMPT_VERSION} to database")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Run Phase 1 ODMI question classification")
    parser.add_argument("--country", required=True, help="ISO country code (e.g. FR)")
    parser.add_argument("--questions", help="Comma-separated question IDs (default: all subset)")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts without API calls")
    parser.add_argument("--all", action="store_true", help="Run all questions, not just subset")
    args = parser.parse_args()

    # Check database exists
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        print("Run: python scripts/setup_sqlite.py")
        sys.exit(1)

    questions = load_questions()

    # Filter to subset unless --all
    if not args.all:
        questions = [q for q in questions if q.get("in_subset", False)]

    # Filter to specific IDs if provided
    if args.questions:
        ids = set(args.questions.split(","))
        questions = [q for q in questions if q["question_id"] in ids]

    if not questions:
        print("No questions to classify. Check your filters or run parse_questions.py first.")
        sys.exit(1)

    print(f"Classifying {len(questions)} questions against {args.country}")
    print(f"Model: {MODEL_VERSION} | Prompt version: {PROMPT_VERSION}")
    print(f"Dry run: {args.dry_run}\n")

    if not args.dry_run:
        ensure_prompt_version_logged()

    results = []
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['question_id']} — {q['dimension']}...", end=" ", flush=True)
        try:
            result = classify_question(q, args.country, dry_run=args.dry_run)
            if result:
                results.append(result)
                save_to_db(result)
                print(f"→ {result.score.tier.value} (score: {result.score.composite}/9)")
        except Exception as e:
            print(f"→ ERROR: {e}")

    if results:
        # Summary
        print(f"\n{'='*60}")
        print(f"Results: {len(results)} classifications saved to {DB_PATH}")
        for tier in AnswerabilityTier:
            count = sum(1 for r in results if r.score.tier == tier)
            if count:
                print(f"  {tier.value}: {count}")


if __name__ == "__main__":
    main()
