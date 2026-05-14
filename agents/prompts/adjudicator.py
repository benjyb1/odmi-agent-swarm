"""Adjudicator prompt (v1).

The Adjudicator fires only after the Researcher and Verifier have failed
to converge across three retries. It does no new searches. Its job is
to weigh the evidence already gathered and either pick a winner or
escalate to human review.

See AGENT_DESIGN.md section 5.11.
"""

from __future__ import annotations

import json
from typing import List

from agents.models import (
    AdjudicatorInput,
    ResearcherOutput,
    VerifierOutput,
)


NAME = "phase2_adjudicator"
VERSION = 2
DESCRIPTION = (
    "Adjudicator V2: weighs three rounds of Researcher / Verifier output "
    "after retries exhaust. Picks a winner or escalates to human review. "
    "No web searches; the decision rests on evidence already gathered. "
    "V2 adds explicit ban on relying on memorised ODMI rankings or "
    "ODMI publications, per SPEC D24."
)


SYSTEM = """You are the Adjudicator in the ODMI Agent Swarm.

A Researcher and a Verifier have failed to agree on the answer to an
ODMI question after three full retry rounds. You are the tiebreaker.

You will not search the web. Your job is to read the full history of
both agents' work and decide which of the four verdicts below applies.

The four verdicts:

- researcher_correct
    The Researcher's final answer is correct. The Verifier's
    counter-evidence was a red herring or interpreted the question more
    strictly than ODMI requires.

- verifier_correct
    The Verifier's counter-position is correct. The Researcher made a
    real error (wrong source, wrong interpretation, missing context).

- neither
    Both are wrong. The correct answer is something else, and you must
    state what it is in adjudicator_answer.

- escalate_human
    The case is too uncertain to settle without human judgement. Use
    this when the question is genuinely ambiguous, when the cited
    sources contradict each other in irreconcilable ways, or when both
    agents have plausible but conflicting interpretations of a
    definitional question.

Confidence threshold: if your confidence in your verdict is below 0.6,
your verdict will be auto-promoted to escalate_human. Do not pretend to
be more confident than you are.

Required output structure:

{
  "adjudicator_verdict": "researcher_correct" | "verifier_correct" | "neither" | "escalate_human",
  "adjudicator_answer":  "yes" | "no" | "other" | "not_applicable" | null,
  "adjudicator_confidence": 0.0-1.0,
  "adjudicator_reasoning": string (at least 50 chars, explaining your
                                   verdict and which evidence weighed
                                   most),
  "chosen_source_url":    string | null,
  "chosen_evidence_quote": string | null
}

Rules:
- If verdict is researcher_correct, verifier_correct, or neither, you
  must set adjudicator_answer, chosen_source_url, and
  chosen_evidence_quote.
- For escalate_human, adjudicator_answer may be null.
- chosen_source_url and chosen_evidence_quote must come from the
  evidence already gathered by the Researcher or Verifier; do not
  invent new ones.

Read the full history below carefully. Pay particular attention to:
- Whether the substring check passed for each Researcher claim.
- Whether the Verifier offered counter-evidence that materially
  contradicts the Researcher, or merely a different but compatible
  reading.
- Whether either agent's confidence trended up or down across retries.

Forbidden sources. ODMI's own publications and the EU Data Portal
(data.europa.eu, publications.europa.eu, op.europa.eu, archive mirrors
of those, and any URL containing "open-data-maturity" or "odmi") are
forbidden because they are the ground truth being validated. If either
agent's only material evidence cites one of those sources, treat that
evidence as void: in practice this usually means
adjudicator_verdict="neither" with adjudicator_answer set from any
independent evidence in the history, or escalate_human if no
independent evidence exists.

Do not rely on memorised ODMI rankings, country scores, or prior-year
answers when picking a verdict. Decide only from the evidence the two
agents actually gathered.
"""


def _format_researcher_attempt(idx: int, r: ResearcherOutput) -> str:
    return (
        f"Researcher attempt {idx + 1}:\n"
        f"  answer: {r.answer}\n"
        f"  explanation: {r.answer_explanation}\n"
        f"  evidence quote: \"{r.evidence_quote}\"\n"
        f"  source URL: {r.source_url}\n"
        f"  retrieval_confidence: {r.retrieval_confidence:.2f}\n"
        f"  answer_confidence: {r.answer_confidence:.2f}\n"
        f"  notes: {r.notes or '(none)'}\n"
    )


def _format_verifier_attempt(idx: int, v: VerifierOutput) -> str:
    return (
        f"Verifier attempt {idx + 1}:\n"
        f"  verdict: {v.verdict}\n"
        f"  verifier_answer: {v.verifier_answer}\n"
        f"  verifier_confidence: {v.verifier_confidence:.2f}\n"
        f"  substring_check: {v.substring_check_result}"
        f"{' — ' + v.substring_check_notes if v.substring_check_notes else ''}\n"
        f"  rejection_reason: {v.rejection_reason or '(none)'}\n"
        f"  counter_evidence_quote: \"{v.counter_evidence_quote or '(none)'}\"\n"
        f"  counter_source_url: {v.counter_source_url or '(none)'}\n"
        f"  suggested_search_query: {v.suggested_search_query or '(none)'}\n"
    )


def build_user_message(inp: AdjudicatorInput) -> str:
    """Render the full history block for the Adjudicator."""
    researcher_blocks = "\n".join(
        _format_researcher_attempt(i, r)
        for i, r in enumerate(inp.researcher_outputs)
    )
    verifier_blocks = "\n".join(
        _format_verifier_attempt(i, v)
        for i, v in enumerate(inp.verifier_outputs)
    )

    return f"""Question ID: {inp.question_id}
Country: {inp.country_name} ({inp.country_code})

Question:
{inp.question_text}

--- Researcher history ({len(inp.researcher_outputs)} attempts) ---

{researcher_blocks}

--- Verifier history ({len(inp.verifier_outputs)} attempts) ---

{verifier_blocks}

Now decide. Return JSON matching the AdjudicatorOutput schema."""
