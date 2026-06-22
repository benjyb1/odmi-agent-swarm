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
VERSION = 4
DESCRIPTION = (
    "Adjudicator V4: weighs three rounds of Researcher / Verifier output "
    "after retries exhaust. Picks a winner or escalates to human review. "
    "No web searches; the decision rests on evidence already gathered. "
    "V3 (D28) makes the answer space per-question: adjudicator_answer "
    "must be a label from the question's allowed list (or "
    "'inconclusive' / 'not_applicable'), not a fixed yes/no/other/NA "
    "literal. V4 (D36) explicitly prefers honest abstention over a "
    "low-confidence label when the gathered evidence does not support a "
    "confident commit."
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
    state what it is in adjudicator_answer (chosen from the allowed
    list in the user message).

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
  "adjudicator_answer":  string from the allowed list shown in the
                         user message, OR 'inconclusive', OR
                         'not_applicable', OR null (only when verdict
                         is "escalate_human"),
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
- adjudicator_answer must be exactly one of the labels in the
  "Answer space" block of the user message, or 'inconclusive', or
  'not_applicable'. Do not paraphrase band labels.
- For ordered band shapes (percentage / ordinal / count), a single
  adjacent-band miss is still a real disagreement; do not split the
  difference.
- For escalate_human, adjudicator_answer may be null.
- chosen_source_url and chosen_evidence_quote must come from the
  evidence already gathered by the Researcher or Verifier; do not
  invent new ones.
- If the evidence gathered by the two agents does not support a
  confident label, set adjudicator_answer to 'inconclusive' rather
  than guessing a label to break the tie. An honest 'inconclusive' is
  preferred over a low-confidence commit. Do not invent support for a
  label that the evidence does not provide.
- Absence of evidence is not evidence of "no". Only answer a negative
  label (such as 'no') when the evidence positively shows the thing is
  absent or false (for example a portal page that states the feature
  does not exist). If the agents simply failed to find evidence that
  the thing is present, that is 'inconclusive', not 'no'. Never convert
  "we could not find it" into "no".

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


# ============================================================
# EXP-16 free-selection arm. SEPARATE prompt version: it adds the
# `attempt_correct` verdict, so the system prompt differs from the
# standard one. The standard `phase2_adjudicator` v4 above is untouched,
# so default-mode `prompt_versions` rows are unchanged. The free arm
# registers its own row under FREE_NAME / FREE_VERSION.
# ============================================================

FREE_NAME = "phase2_adjudicator_free"
FREE_VERSION = 1
FREE_DESCRIPTION = (
    "Adjudicator free-selection arm (EXP-16). Extends V4 with an "
    "`attempt_correct` verdict that lets the Adjudicator commit the answer "
    "from ANY of the up-to-four Researcher attempts by index, not only the "
    "final attempt that `researcher_correct` is pinned to. The D44 rule "
    "(absence of evidence is 'inconclusive', never 'no'), the "
    "honest-abstention preference, and the confidence floor all still hold. "
    "Selection-mode 'standard' keeps the V4 prompt and is byte-identical to "
    "production; only the 'free' arm uses this prompt."
)

# The free system prompt is the standard one with the verdict taxonomy and
# output structure extended to admit `attempt_correct` + `chosen_attempt`.
SYSTEM_FREE = SYSTEM.replace(
    "decide which of the four verdicts below applies.\n\nThe four verdicts:",
    "decide which of the five verdicts below applies.\n\nThe five verdicts:",
).replace(
    """- escalate_human
    The case is too uncertain to settle without human judgement. Use""",
    """- attempt_correct
    One of the Researcher's attempts (not necessarily the final one)
    reached the correct answer on the evidence it gathered. Set
    chosen_attempt to that attempt's 1-based index and copy its answer
    into adjudicator_answer. Use this when an EARLIER attempt was right
    and a later attempt drifted or abstained: researcher_correct only
    ever refers to the FINAL attempt, so this verdict is the only way to
    commit an earlier attempt's answer. The committed answer must be one
    of the attempts' own answers (or an honest 'inconclusive'); do not
    synthesise a new answer here.

- escalate_human
    The case is too uncertain to settle without human judgement. Use""",
).replace(
    '  "adjudicator_verdict": "researcher_correct" | "verifier_correct" | "neither" | "escalate_human",',
    '  "adjudicator_verdict": "researcher_correct" | "verifier_correct" | "neither" | "attempt_correct" | "escalate_human",\n'
    '  "chosen_attempt":      integer (1-based attempt index, REQUIRED when\n'
    '                         verdict is "attempt_correct", else null),',
).replace(
    """Rules:
- If verdict is researcher_correct, verifier_correct, or neither, you
  must set adjudicator_answer, chosen_source_url, and
  chosen_evidence_quote.""",
    """Rules:
- If verdict is researcher_correct, verifier_correct, neither, or
  attempt_correct, you must set adjudicator_answer, chosen_source_url,
  and chosen_evidence_quote.
- If verdict is attempt_correct you must also set chosen_attempt to the
  1-based index of the chosen Researcher attempt, and adjudicator_answer
  must equal that attempt's answer (or 'inconclusive' if you judge that
  attempt's answer to be an honest abstention).""",
)


def _free_selection_block(num_attempts: int) -> str:
    """Per-call instruction enabling free attempt selection (EXP-16).

    Renders only when free selection is requested. Returned empty for the
    standard arm, so the standard user message is byte-identical.
    """
    return (
        "\n--- Free attempt selection (EXP-16) ---\n"
        "You may commit the answer from ANY of the "
        f"{num_attempts} Researcher attempt(s) above, not only the final "
        "one. If an EARLIER attempt reached the right answer on the evidence "
        "it gathered and a later attempt drifted, set "
        "adjudicator_verdict='attempt_correct', chosen_attempt to that "
        "attempt's 1-based index, and copy that attempt's answer into "
        "adjudicator_answer. researcher_correct still refers to the FINAL "
        "attempt only. The answer you commit must come from one of the "
        "attempts' answers, or be an honest 'inconclusive'. Absence of "
        "evidence is 'inconclusive', never 'no'. Prefer an honest "
        "abstention over a low-confidence commit.\n"
    )


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


def _evidence_corpus_block(inp: AdjudicatorInput) -> str:
    """EXP-7 chained arm: the full evidence corpus accumulated across rounds.

    Renders nothing when `evidence_corpus` is empty (always so in the
    baseline loop), so the user message and the registered prompt version are
    unchanged there. The instruction to synthesise over the corpus travels in
    this block, not the system prompt, so the system prompt stays identical
    across arms.
    """
    items = inp.evidence_corpus
    if not items:
        return ""
    lines = [
        "",
        "--- Full evidence corpus (all rounds) ---",
        "Every snippet and counter-evidence quote both agents gathered across",
        "the whole investigation, not just the per-attempt summaries above.",
        "Synthesise over all of it. Commit to a label only when the corpus",
        "supports a confident answer; otherwise set adjudicator_answer to",
        "'inconclusive'. Cite only a source that appears in this corpus.",
        "",
    ]
    for i, ev in enumerate(items, start=1):
        snippet = ev.snippet[:300] + ("..." if len(ev.snippet) > 300 else "")
        src = ev.source_url or "(no URL)"
        lines.append(
            f"  [{i}] (round {ev.round_index}, {ev.origin}) {src}\n      {snippet}"
        )
    lines.append("")
    return "\n".join(lines)


def _answer_space_block(inp: AdjudicatorInput) -> str:
    bullets = "\n".join(f"  - {a!r}" for a in inp.allowed_answers)
    return (
        "--- Answer space ---\n"
        f"Answer shape: {inp.answer_shape}\n"
        f"`adjudicator_answer` MUST be one of:\n{bullets}\n"
        f"  - 'inconclusive'    (no confident answer can be reached)\n"
        f"  - 'not_applicable'  (question does not apply to this country)\n"
        f"  - null              (only when verdict='escalate_human')"
    )


def build_user_message(
    inp: AdjudicatorInput, *, selection: str = "standard"
) -> str:
    """Render the full history block for the Adjudicator.

    `selection` controls EXP-16 free attempt selection. 'standard' (the
    default) renders no extra block, so the message is byte-identical to the
    pre-EXP-16 behaviour. 'free' appends the free-selection instruction in
    this per-call message, keeping the standard registered prompt untouched.
    """
    researcher_blocks = "\n".join(
        _format_researcher_attempt(i, r)
        for i, r in enumerate(inp.researcher_outputs)
    )
    verifier_blocks = "\n".join(
        _format_verifier_attempt(i, v)
        for i, v in enumerate(inp.verifier_outputs)
    )

    free_block = (
        _free_selection_block(len(inp.researcher_outputs))
        if selection == "free"
        else ""
    )

    return f"""Question ID: {inp.question_id}
Country: {inp.country_name} ({inp.country_code})

Question:
{inp.question_text}

{_answer_space_block(inp)}

--- Researcher history ({len(inp.researcher_outputs)} attempts) ---

{researcher_blocks}

--- Verifier history ({len(inp.verifier_outputs)} attempts) ---

{verifier_blocks}
{_evidence_corpus_block(inp)}{free_block}
Now decide. Return JSON matching the AdjudicatorOutput schema."""
