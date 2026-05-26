"""Per-question answer shapes (D28).

The ODMI 2025 questionnaire has 143 questions across five answer
shapes:

  - binary             — yes / no (optionally + other / not applicable /
                          i don't know variants from the ODMI rubric)
  - percentage_band    — ordered list of band labels (e.g. >90% … <10%)
  - ordinal_magnitude  — ordered list (all / majority / half / few / none)
  - count_band         — ordered list of count thresholds (e.g. 1-4 / 5-10 / >10)
  - categorical        — small fixed enum (P14 top-down / bottom-up / hybrid;
                          Q3 within one day / week / month / longer)

Each question's shape and the canonical list of allowed answers live
in the `questions` table (`answer_shape`, `allowed_answers`),
populated by `scripts/migrate_d28_shapes.py`.

Two escape-valve labels are always permitted on top of the shape's
allowed list:

  - `inconclusive`     — the swarm could not reach a confident answer
                          (low confidence, D24 forbidden-source refusal,
                          honest uncertainty). Distinct from a literal
                          `other`, which is only valid where ODMI's
                          rubric lists it.
  - `not_applicable`   — the question does not apply to this country.

Shape-aware verification (D28 phase C) sits on top of this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from agents.tools.db import connect


INCONCLUSIVE = "inconclusive"
NOT_APPLICABLE = "not_applicable"

# Labels that are always valid regardless of shape.
ALWAYS_ALLOWED: tuple[str, ...] = (INCONCLUSIVE, NOT_APPLICABLE)

# Shape names. Must mirror scripts/migrate_d28_shapes.py.
SHAPES: tuple[str, ...] = (
    "binary",
    "percentage_band",
    "ordinal_magnitude",
    "count_band",
    "categorical",
)

# Shapes whose `allowed_answers` are an ordered scale. Used by the
# Verifier's near-miss reasoning and by `_MATCH_STATUS_SQL`'s
# `near_match` state. `categorical` is excluded because its labels
# carry no inherent order.
ORDERED_SHAPES: tuple[str, ...] = (
    "percentage_band",
    "ordinal_magnitude",
    "count_band",
)


@dataclass(frozen=True)
class QuestionShape:
    """Per-question answer space, loaded from the `questions` table."""

    question_id: str
    shape: str
    allowed_answers: tuple[str, ...]

    @property
    def all_valid(self) -> tuple[str, ...]:
        """The full set of strings the agent may emit for this question."""
        return tuple(self.allowed_answers) + ALWAYS_ALLOWED


def load_question_shape(question_id: str) -> QuestionShape:
    """Read the question's shape and allowed answers from the DB.

    Falls back to `binary` with `["yes", "no"]` if the row exists but
    has not been classified yet (e.g. a fresh DB before the D28
    migration ran). Raises if the question_id is unknown.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT answer_shape, allowed_answers FROM questions "
            "WHERE question_id = ?",
            (question_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"Unknown question_id {question_id!r}")

    shape, allowed_json = row
    if not shape:
        shape = "binary"
    if allowed_json:
        try:
            allowed = tuple(json.loads(allowed_json))
        except json.JSONDecodeError:
            allowed = ("yes", "no")
    else:
        allowed = ("yes", "no")
    return QuestionShape(
        question_id=question_id,
        shape=shape,
        allowed_answers=allowed,
    )


def is_valid_answer(answer: str, shape: QuestionShape) -> bool:
    """True if the agent's emitted answer is one of the allowed labels."""
    return answer in shape.all_valid


def normalise_answer(answer: str, shape: QuestionShape) -> str:
    """Best-effort normalisation of a model-emitted answer.

    Returns the canonical label if a case-insensitive or whitespace-
    folded match exists. Returns the original answer untouched if no
    match was found, so the caller can decide whether to reject.
    """
    if answer in shape.all_valid:
        return answer
    target = answer.strip().lower()
    for label in shape.all_valid:
        if label.lower() == target:
            return label
    return answer


def is_inconclusive(answer: str) -> bool:
    return answer == INCONCLUSIVE


def is_band_shape(shape: str) -> bool:
    return shape in ORDERED_SHAPES


def band_distance(a: str, b: str, allowed: Sequence[str]) -> int | None:
    """Number of steps between two band labels in an ordered shape.

    Returns 0 for an exact match, 1 for adjacent bands, 2 for two-apart,
    etc. Returns None if either label is not in the ordered list (e.g.
    `inconclusive` against `>90%`). Caller decides what to do with
    `None`.
    """
    if a == b:
        return 0
    try:
        idx_a = allowed.index(a)
        idx_b = allowed.index(b)
    except ValueError:
        return None
    return abs(idx_a - idx_b)
