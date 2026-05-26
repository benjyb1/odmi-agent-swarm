"""The Adjudicator agent.

Fires when the Researcher and Verifier have failed to converge across
three retries. Single LLM call. No web searches; weighs only the
evidence already gathered by the prior two agents.

See AGENT_DESIGN.md section 5.11 for the full atomic specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from agents.models import (
    AdjudicatorInput,
    AdjudicatorOutput,
    LLMUsage,
)
from agents.prompts import adjudicator as adjudicator_prompt
from agents.tools import answer_shapes
from agents.tools import db as db_helpers
from agents.tools.llm import StructuredOutputError, call_for_structured


# Confidence threshold from AGENT_DESIGN §5.11.5: below this, the
# verdict is auto-promoted to escalate_human regardless of the model's
# nominal choice.
LOW_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class AdjudicatorRunResult:
    """Container for one Adjudicator run."""

    output: Optional[AdjudicatorOutput]
    failure_mode: Optional[str]
    usage: Optional[LLMUsage]
    promoted_to_human: bool = False
    notes: Optional[str] = None

    @property
    def cumulative_input_tokens(self) -> int:
        return self.usage.input_tokens if self.usage else 0

    @property
    def cumulative_output_tokens(self) -> int:
        return self.usage.output_tokens if self.usage else 0

    @property
    def cumulative_wall_clock_ms(self) -> int:
        return self.usage.wall_clock_ms if self.usage else 0

    @property
    def cumulative_cost_usd(self) -> Optional[float]:
        return self.usage.estimated_cost_usd if self.usage else None


StepCallback = Callable[[str, dict], None]


def _noop(event: str, payload: dict) -> None:  # pragma: no cover
    return


def run_adjudicator(
    inp: AdjudicatorInput,
    *,
    model: str | None = None,
    condition_label: str = "baseline",
    subtrio_id: str | None = None,
    on_step: StepCallback = _noop,
) -> AdjudicatorRunResult:
    """Run the Adjudicator once.

    Single LLM call. Returns an AdjudicatorRunResult either way; the
    caller writes a phase2_adjudications row regardless of outcome.
    """
    on_step("start", {
        "question_id": inp.question_id,
        "country": inp.country_code,
        "researcher_attempts": len(inp.researcher_outputs),
        "verifier_attempts": len(inp.verifier_outputs),
    })

    prompt_id = db_helpers.ensure_prompt_version(
        adjudicator_prompt.NAME,
        adjudicator_prompt.VERSION,
        adjudicator_prompt.SYSTEM,
        adjudicator_prompt.DESCRIPTION,
    )

    user_message = adjudicator_prompt.build_user_message(inp)

    on_step("main_call_start", {
        "prompt_version_id": prompt_id,
        "user_message_chars": len(user_message),
    })

    call_kwargs = {
        "system": adjudicator_prompt.SYSTEM,
        "user_message": user_message,
        "output_schema": AdjudicatorOutput,
        "max_tokens": 1200,
        "condition_label": condition_label,
        "prompt_version_id": prompt_id,
        "usage_context": f"adjudicator:{inp.question_id}:{inp.country_code}",
        "subtrio_id": subtrio_id,
    }
    if model:
        call_kwargs["model"] = model

    try:
        output, usage = call_for_structured(**call_kwargs)
    except StructuredOutputError as exc:
        on_step("main_call_failed", {"error": str(exc)})
        return AdjudicatorRunResult(
            output=None,
            failure_mode="schema_invalid",
            usage=None,
            notes=str(exc)[:300],
        )

    # D28: normalise / validate adjudicator_answer against the
    # question's allowed list. Only relevant when a winner verdict was
    # picked (escalate_human can carry a null answer).
    note_parts: list[str] = []
    if output.adjudicator_answer is not None:
        shape = answer_shapes.QuestionShape(
            question_id=inp.question_id,
            shape=inp.answer_shape,
            allowed_answers=tuple(inp.allowed_answers),
        )
        normalised = answer_shapes.normalise_answer(
            output.adjudicator_answer, shape
        )
        if normalised != output.adjudicator_answer:
            note_parts.append(
                f"adjudicator_answer normalised from "
                f"{output.adjudicator_answer!r} to {normalised!r}"
            )
            output = output.model_copy(
                update={"adjudicator_answer": normalised}
            )
        if not answer_shapes.is_valid_answer(
            output.adjudicator_answer, shape
        ):
            note_parts.append(
                f"adjudicator_answer {output.adjudicator_answer!r} "
                f"not in allowed set"
            )

    # Auto-promote low-confidence verdicts to escalate_human (§5.11.5).
    promoted = False
    if (
        output.adjudicator_verdict != "escalate_human"
        and output.adjudicator_confidence < LOW_CONFIDENCE_THRESHOLD
    ):
        output = output.model_copy(update={
            "adjudicator_verdict": "escalate_human",
        })
        promoted = True

    on_step("main_call_complete", {
        "verdict": output.adjudicator_verdict,
        "confidence": output.adjudicator_confidence,
        "promoted_to_human": promoted,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": usage.estimated_cost_usd,
    })

    base_note = (
        "auto-promoted: confidence below 0.6 threshold"
        if promoted else None
    )
    if note_parts:
        combined = "; ".join(note_parts)
        notes = f"{base_note}; {combined}" if base_note else combined
    else:
        notes = base_note

    return AdjudicatorRunResult(
        output=output,
        failure_mode=None,
        usage=usage,
        promoted_to_human=promoted,
        notes=notes,
    )
