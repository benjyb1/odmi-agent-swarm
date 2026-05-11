"""Tests for the Phase 1 classifier data models and logic.

These test the rubric scoring, tier mapping, and data formatting —
not the LLM calls themselves.
"""

import pytest

from agents.classifier import AnswerabilityTier, ClassificationResult, RubricScore


class TestAnswerabilityTier:
    def test_highly_likely_range(self):
        assert AnswerabilityTier.from_composite(7) == AnswerabilityTier.HIGHLY_LIKELY
        assert AnswerabilityTier.from_composite(8) == AnswerabilityTier.HIGHLY_LIKELY
        assert AnswerabilityTier.from_composite(9) == AnswerabilityTier.HIGHLY_LIKELY

    def test_likely_range(self):
        assert AnswerabilityTier.from_composite(5) == AnswerabilityTier.LIKELY
        assert AnswerabilityTier.from_composite(6) == AnswerabilityTier.LIKELY

    def test_unlikely_range(self):
        assert AnswerabilityTier.from_composite(3) == AnswerabilityTier.UNLIKELY
        assert AnswerabilityTier.from_composite(4) == AnswerabilityTier.UNLIKELY

    def test_very_unlikely_range(self):
        assert AnswerabilityTier.from_composite(0) == AnswerabilityTier.VERY_UNLIKELY
        assert AnswerabilityTier.from_composite(1) == AnswerabilityTier.VERY_UNLIKELY
        assert AnswerabilityTier.from_composite(2) == AnswerabilityTier.VERY_UNLIKELY


class TestRubricScore:
    def test_composite_calculation(self):
        score = RubricScore(
            evidence_score=3,
            evidence_justification="test",
            determinism_score=2,
            determinism_justification="test",
            complexity_score=1,
            complexity_justification="test",
        )
        assert score.composite == 6
        assert score.tier == AnswerabilityTier.LIKELY

    def test_max_score(self):
        score = RubricScore(
            evidence_score=3,
            evidence_justification="test",
            determinism_score=3,
            determinism_justification="test",
            complexity_score=3,
            complexity_justification="test",
        )
        assert score.composite == 9
        assert score.tier == AnswerabilityTier.HIGHLY_LIKELY

    def test_min_score(self):
        score = RubricScore(
            evidence_score=0,
            evidence_justification="test",
            determinism_score=0,
            determinism_justification="test",
            complexity_score=0,
            complexity_justification="test",
        )
        assert score.composite == 0
        assert score.tier == AnswerabilityTier.VERY_UNLIKELY

    def test_validation_rejects_out_of_range(self):
        with pytest.raises(Exception):
            RubricScore(
                evidence_score=4,
                evidence_justification="test",
                determinism_score=0,
                determinism_justification="test",
                complexity_score=0,
                complexity_justification="test",
            )


class TestClassificationResult:
    def test_to_db_row(self):
        score = RubricScore(
            evidence_score=2,
            evidence_justification="Found on data.gouv.fr",
            determinism_score=3,
            determinism_justification="Binary yes/no",
            complexity_score=2,
            complexity_justification="Single portal source",
        )
        result = ClassificationResult(
            question_id="POL_01",
            question_text="Does the country have an open data policy?",
            dimension="Policy",
            country="FR",
            score=score,
            language_used="en",
            model_version="claude-opus-4-6",
            prompt_version=1,
            raw_response='{"evidence_score": 2}',
            timestamp="2026-03-27T12:00:00Z",
        )
        row = result.to_db_row()
        assert row["question_id"] == "POL_01"
        assert row["tier"] == "Highly Likely"
        assert row["evidence_score"] == 2
        assert row["country"] == "FR"
