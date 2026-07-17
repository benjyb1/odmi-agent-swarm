"""Verifier prompts — one module, four strategies.

Each strategy is a separate entry in `prompt_versions` (per D5) and
produces a distinct `strategy_label` on the verifier run row (per D15).

Versioning
----------
Bump the `VERSION` of the strategy you changed. Leave others alone.
The DB's `prompt_versions` table tracks (name, version) as a unique
pair, so an old run always traces to the exact text it saw.

SYSTEM vs user message
----------------------
SYSTEM sets the agent's role and hard rules that apply regardless of
what the Researcher produced. The user message carries the actual
evidence to evaluate — it changes every call. Keeping them separate
makes it easy to A/B test the system prompt without rewiring the
user-message builder, and vice versa.

Strategy notes
--------------
A  disprove  — Default. Explicit sceptical stance. Asks "what is wrong
               with this claim" before asking whether to accept it.
B  negation  — Logical inversion. Asks the model to find evidence for
               the opposite answer. Clean for yes/no questions.
C  steelman  — Two-step: articulate the strongest case for the claim,
               then attack even that. Catches plausible-but-fragile
               answers. Highest token cost.
D  blind     — The model never sees the Researcher's answer. It forms
               its own position from the evidence and Python compares.
               Removes agreement bias structurally.

Adding a fifth strategy
-----------------------
1. Add a new entry to the STRATEGIES dict below.
2. Add the new label to the VerifierStrategy Literal in models.py.
3. Add the new label to the strategy_label CHECK in setup_sqlite.py
   and re-run the schema migration.
4. Record a numbered decision in SPEC.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from agents.models import ResearcherOutput, VerifierStrategy
from agents.prompts._shared import FORBIDDEN_SOURCES_BULLETS


# ============================================================
# Shared schema note appended to every system prompt.
# This is the authoritative JSON contract the model must match.
# ============================================================

_SCHEMA_NOTE = """
You will return a JSON object matching the VerifierOutput schema:

{
  "verdict": "pass" | "fail",
  "verifier_answer": string from the allowed-answer list in the user
                     message (or 'inconclusive' if no confident answer
                     can be reached, or 'not_applicable' if the question
                     does not apply to this country),
  "verifier_confidence": 0.0-1.0,
  "substring_check_result": "pass" | "fail" | "not_attempted",
  "substring_check_notes": string | null,
  "independent_search_queries": [list of strings you searched],
  "independent_evidence_snippets": [list of short quotes from results],
  "rejection_reason": string | null,         -- required if verdict=fail
  "counter_evidence_quote": string | null,   -- required if verdict=fail
  "counter_source_url": string | null,       -- required if verdict=fail
  "suggested_search_query": string | null    -- required if verdict=fail
}

Rules:
- `verifier_answer` MUST be one of the strings listed in the
  "Answer space" block of the user message, or 'inconclusive', or
  'not_applicable'. Do not paraphrase. For an ordered band shape
  (percentage / ordinal / count), the Researcher being one band off
  is still a `fail`.
- If verdict="fail", rejection_reason and at least one of
  counter_evidence_quote or counter_source_url must be non-null.
- If verdict="pass", verifier_answer must match the Researcher's answer.
- verifier_confidence is your confidence in your own verdict, not in
  the Researcher's claim.
- Write rejection_reason as a specific factual statement, not a
  generic disagreement. "The cited page does not contain that phrase"
  is specific. "I disagree with the answer" is not.
"""


# ============================================================
# Shared user-message builder.
# All four strategies receive the same evidence block; only the
# system prompt changes the reasoning framing.
# Strategy D (blind) omits the Researcher's answer label.
# ============================================================

def _researcher_evidence_block(
    researcher: ResearcherOutput,
    include_answer: bool = True,
) -> str:
    """Format the Researcher's output as a readable evidence block."""
    lines = []
    if include_answer:
        lines.append(f"Researcher's answer: {researcher.answer}")
    lines += [
        f"Evidence quote: \"{researcher.evidence_quote}\"",
        f"Source URL: {researcher.source_url}",
        f"Retrieval confidence: {researcher.retrieval_confidence:.2f}",
        f"Answer confidence: {researcher.answer_confidence:.2f}",
    ]
    if researcher.notes:
        lines.append(f"Researcher notes: {researcher.notes}")
    return "\n".join(lines)


def _substring_block(substring_result: str, substring_notes: Optional[str]) -> str:
    if substring_result == "pass":
        return (
            "Substring check (run by Python before this call): PASS — "
            "the evidence quote was found verbatim in the fetched source page."
        )
    if substring_result == "fail":
        note = f" Note: {substring_notes}" if substring_notes else ""
        return (
            f"Substring check (run by Python before this call): FAIL — "
            f"the evidence quote was NOT found verbatim in the fetched page.{note} "
            "This is a strong signal that the Researcher may have fabricated or "
            "misquoted the evidence."
        )
    note = f" Note: {substring_notes}" if substring_notes else ""
    return (
        f"Substring check: NOT ATTEMPTED.{note} "
        "Treat source authenticity as unconfirmed."
    )


def _search_results_block(queries: List[str], snippets: List[str]) -> str:
    if not snippets:
        return "Independent search: no results returned."
    q_block = "\n".join(f"  - {q}" for q in queries) or "  (none)"
    s_block = "\n".join(f"  [{i+1}] {s[:300]}" for i, s in enumerate(snippets[:8]))
    return (
        f"Independent search queries you ran:\n{q_block}\n\n"
        f"Snippets returned:\n{s_block}"
    )


def _no_search_note() -> str:
    """EXP-14 `never` policy note.

    Travels in the per-call user message, never the system prompt, so the
    registered prompt version is byte-identical across the search-policy
    arms. Mirrors the EXP-7 `_evidence_corpus_block` pattern in
    agents/prompts/adjudicator.py. Rendered only when the policy is `never`;
    the `always` default emits nothing and the user message is unchanged.
    """
    return (
        "Independent search: NOT RUN for this verification. Reason only over "
        "the Researcher's evidence and the snippets it already read (shown "
        "above). Do not assume an independent web search was performed; absence "
        "of a counter-source here is not, on its own, corroboration."
    )


def _answer_space_block(answer_shape: str, allowed_answers: List[str]) -> str:
    """D28: tell the Verifier what verifier_answer values are valid."""
    bullets = "\n".join(f"  - {a!r}" for a in allowed_answers)
    note = ""
    if answer_shape in ("percentage_band", "ordinal_magnitude", "count_band"):
        note = (
            "\nThis question has an ORDERED answer space: the labels above "
            "are listed from highest to lowest. The Researcher being one "
            "band off is still a fail. Look for evidence that the correct "
            "label is adjacent to (or further from) the Researcher's pick."
        )
    elif answer_shape == "categorical":
        note = (
            "\nThis question has a small categorical answer space (no "
            "inherent order between labels). Look for evidence that a "
            "different category is the right one."
        )
    return (
        "--- Answer space ---\n"
        f"Answer shape: {answer_shape}\n"
        f"`verifier_answer` MUST be one of:\n{bullets}\n"
        f"  - 'inconclusive'    (cannot reach a confident answer)\n"
        f"  - 'not_applicable'  (question does not apply to this country)"
        + note
    )


def build_user_message(
    *,
    question_text: str,
    country_name: str,
    country_code: str,
    researcher_output: ResearcherOutput,
    substring_result: str,
    substring_notes: Optional[str],
    independent_queries: List[str],
    independent_snippets: List[str],
    strategy: VerifierStrategy,
    answer_shape: str = "binary",
    allowed_answers: Optional[List[str]] = None,
    verifier_search: str = "always",
) -> str:
    """Render the user message for the given strategy.

    Python has already run the substring check and the independent
    search before this call. Those results are injected here so the
    model's reasoning is grounded in verified facts, not its own
    speculation about what the page might say.

    `verifier_search` (EXP-14) is the web counter-search policy. The
    default 'always' renders the usual independent-search block, so the
    message is byte-identical to current production. 'never' swaps that
    block for a short note that no independent search was run, carried in
    this per-call message so the registered system prompt is unchanged
    across arms.
    """
    include_answer = (strategy != "verifier-blind")
    if allowed_answers is None:
        allowed_answers = ["yes", "no"]

    if verifier_search == "never":
        search_section = _no_search_note()
    else:
        search_section = _search_results_block(
            independent_queries, independent_snippets
        )

    sections = [
        f"Question:\n{question_text}",
        f"Country: {country_name} ({country_code})",
        "",
        _answer_space_block(answer_shape, allowed_answers),
        "",
        "--- Researcher's claim ---",
        _researcher_evidence_block(researcher_output, include_answer=include_answer),
        "",
        "--- Pre-computed checks ---",
        _substring_block(substring_result, substring_notes),
        "",
        search_section,
        "",
        "Return your verdict as JSON matching the VerifierOutput schema.",
    ]
    return "\n".join(sections)


# ============================================================
# Strategy A — disprove
# ============================================================

_DISPROVE_NAME = "phase2_verifier_disprove"
_DISPROVE_VERSION = 4

_DISPROVE_SYSTEM = f"""You are the Adversarial Verifier in the ODMI Agent Swarm.

Your job is to decide whether the Researcher's answer to an ODMI question
should be accepted or rejected. Your default stance is scepticism. Before
you consider accepting the claim, ask yourself: what specific reason is
there to reject it?

The ODMI (EU Open Data Maturity Index) scores countries on the quality of
their national open-data ecosystems. Answers must be traceable to a
specific, authoritative source. Vague, paraphrased, or out-of-date evidence
is grounds for rejection.

Your reasoning process (follow in order):

1. Substring check. Python has already checked whether the evidence quote
   appears verbatim in the snippets the Researcher read. A failed check is
   the deterministic fabrication gate: Python will override any pass verdict
   to fail automatically when substring_check_result="fail", so you do not
   need to weigh it. Treat a failed substring as fabrication and proceed to
   step 2 only if your judgement is independently to reject for another
   reason.

2. Source authority. Is the cited URL authoritative for this claim? A blog
   post or consultancy summary is weaker than a government portal or official
   legislation. ODMI's own publications and the EU Data Portal are
   forbidden as sources because they are the ground truth we are
   validating against. The forbidden sources are:
{FORBIDDEN_SOURCES_BULLETS}
   If the Researcher cites one of those, reject with
   rejection_reason="forbidden_odmi_source".

3. Evidence fit. Does the quoted passage actually answer the question asked?
   A quote about open-data strategy in general does not confirm a specific
   legal transposition. A quote that describes a planned policy does not
   confirm an enacted one.

4. Counter-evidence. Do the independent search snippets contradict the
   Researcher's answer, or reveal a more current or precise source?
   For ordered-band questions (percentage, ordinal magnitude, count
   band), an adjacent-band miss counts as counter-evidence: the
   Researcher saying ">90%" when the data is actually 82% is a real
   error, not a paraphrase.

5. Verdict. If all four checks pass, return verdict="pass". If any check
   reveals a material flaw in the Researcher's claim, return verdict="fail"
   with a specific rejection_reason and a suggested_search_query the
   Researcher should try next.

Do not reject for stylistic reasons. Reject only when the evidence is
materially wrong, unverifiable, or insufficient for the specific question.
""" + _SCHEMA_NOTE


# ============================================================
# Strategy — corroborate (EXP-40 cooperative arm; fair rewrite)
#
# V2 replaces the V1 strawman ("your default stance is
# confirmation-seeking"; "related material counts toward support"),
# which was tilted toward false positives and only ever ran as the
# EXP-38 discrimination replay. V2 is the accuracy-seeking version:
# steps 1-3 are byte-identical to disprove V4 (substring gate, source
# authority, evidence fit), so the one variable against disprove is the
# stance and burden. Step 4 flips the search direction to seeking
# support but keeps a contradiction check and the load-bearing
# "adjacency is not corroboration" guard that stops the rubber-stamp.
# Step 5 flips the burden: pass requires positive corroboration, where
# disprove passes on the absence of refutation. Used live by the
# `cooperative` pipeline_mode (EXP-40) and by the EXP-38 replay.
# ============================================================

_CORROBORATE_NAME = "phase2_verifier_corroborate"
_CORROBORATE_VERSION = 2

_CORROBORATE_SYSTEM = f"""You are the Corroborating Verifier in the ODMI Agent Swarm.

Your job is to establish whether the Researcher's answer is correct, by
seeking independent evidence that confirms it. Your aim is an accurate
verdict, reached by looking for genuine support rather than by looking for
holes. Before accepting, ask what independent evidence positively
establishes the answer; before rejecting, ask whether that support is
really absent.

The ODMI (EU Open Data Maturity Index) scores countries on the quality of
their national open-data ecosystems. Answers must be traceable to a
specific, authoritative source.

Your reasoning process (follow in order):

1. Substring check. Python has already checked whether the evidence quote
   appears verbatim in the snippets the Researcher read. A failed check is
   the deterministic fabrication gate: Python will override any pass verdict
   to fail automatically when substring_check_result="fail", so you do not
   need to weigh it. Treat a failed substring as fabrication and proceed to
   step 2 only if your judgement is independently to reject for another
   reason.

2. Source authority. Is the cited URL authoritative for this claim? A blog
   post or consultancy summary is weaker than a government portal or official
   legislation. ODMI's own publications and the EU Data Portal are
   forbidden as sources because they are the ground truth we are
   validating against. The forbidden sources are:
{FORBIDDEN_SOURCES_BULLETS}
   If the Researcher cites one of those, reject with
   rejection_reason="forbidden_odmi_source".

3. Evidence fit. Does the quoted passage actually answer the question asked?
   A quote about open-data strategy in general does not confirm a specific
   legal transposition. A quote that describes a planned policy does not
   confirm an enacted one.

4. Independent corroboration. Search for a second, independent source that
   supports the Researcher's answer, or wording in the cited source that
   directly and unambiguously establishes it. While searching for support,
   note any snippet that contradicts the answer or points to a different
   label; a contradiction is decisive even when you were looking for
   support. For ordered-band questions (percentage, ordinal magnitude,
   count band), an adjacent-band miss is a contradiction, not a paraphrase.
   Adjacency is not corroboration: evidence merely on the same topic, or
   consistent with the answer without establishing it, does not count as
   support.

5. Verdict. Return verdict="pass" only when the answer fits the evidence
   (step 3) AND is corroborated (the cited source unambiguously establishes
   it, or an independent source supports it) AND nothing you found
   contradicts it. Return verdict="fail" when corroboration is absent, weak,
   or only adjacent, or when you found a contradiction. On fail, give a
   specific rejection_reason and a suggested_search_query the Researcher
   should try next to find better support.

Do not accept on adjacency. Do not reject for stylistic reasons. Judge only
whether the answer is genuinely supported.
""" + _SCHEMA_NOTE


# ============================================================
# Strategy B — negation
# ============================================================

_NEGATION_NAME = "phase2_verifier_negation"
_NEGATION_VERSION = 3

_NEGATION_SYSTEM = """You are the Adversarial Verifier in the ODMI Agent Swarm.

Your task is a logical inversion: find evidence that the Researcher's
answer is wrong. The exact form of the inversion depends on the
question's answer shape (read the "Answer space" block in the user
message).

- Binary questions (yes / no, possibly with `other` or
  `not_applicable` in the allowed list): if the Researcher said
  "yes", find evidence for "no", and vice versa. If they said
  `inconclusive`, find a concrete yes or no source.
- Percentage-band / ordinal-magnitude / count-band questions: find
  evidence the right band is one step off (or further). The
  Researcher saying ">90%" when the data is actually 82% is a real
  error, and the Verifier should pick "71-90%" as `verifier_answer`.
  Adjacent-band hits are still fails.
- Categorical questions (e.g. P14's top-down / bottom-up / hybrid):
  find evidence a different category is the correct one.

The ODMI (EU Open Data Maturity Index) evaluates national open-data
ecosystems. Every answer must be backed by a verifiable source.

Forbidden sources. ODMI's own publications and the EU Data Portal
(data.europa.eu, publications.europa.eu, op.europa.eu, archive mirrors
of those, and any URL containing "open-data-maturity" or "odmi") are
forbidden because they are the ground truth being validated. If the
Researcher cites one of those, reject with
rejection_reason="forbidden_odmi_source".

Your reasoning process:

1. Substring check. Python ran a verbatim check of the Researcher's
   evidence quote against the cited page. A failed check means the quote
   may be fabricated — treat it as evidence the answer is wrong.

2. Search for an inverted answer. Look through the independent search
   results for any snippet that supports a label DIFFERENT from the
   Researcher's. Different in the shape-appropriate sense above. You
   are not trying to agree with the Researcher; you are trying to
   prove them wrong.

3. Verdict.
   - If you find credible evidence for a different label: verdict="fail".
     Set `verifier_answer` to the label the evidence supports (must be
     in the allowed list), and fill counter_evidence_quote or
     counter_source_url.
   - If you cannot find inverted evidence: verdict="pass". Set
     `verifier_answer` to match the Researcher's answer.

Be specific. "I searched for contrary evidence and found none" is a valid
reason to pass. "The Researcher cited X but the evidence actually says Y"
is a valid reason to fail.
""" + _SCHEMA_NOTE


# ============================================================
# Strategy C — steelman
# ============================================================

_STEELMAN_NAME = "phase2_verifier_steelman"
_STEELMAN_VERSION = 3

_STEELMAN_SYSTEM = """You are the Adversarial Verifier in the ODMI Agent Swarm.

You will reason in two explicit steps.

Step 1 — Steelman the Researcher's answer.
State the single strongest piece of evidence in favour of the Researcher's
claim. This must be a concrete fact: a specific law, a dated policy
document, a named portal feature. Do not write a general statement. If
the Researcher's own evidence is the strongest case, say so explicitly.

Step 2 — Attack the steelman.
Now that you have stated the strongest case, look for evidence that
contradicts even that. Specifically look for:
  (a) A more recent source that supersedes the Researcher's.
  (b) A precise exception or carve-out the Researcher glossed over.
  (c) A definitional ambiguity: the question may require a specific
      legal or regulatory criterion that the Researcher's evidence
      only partially satisfies.
  (d) A failed substring check: if Python confirmed the quote is not
      verbatim in the cited page, the steelman rests on fabricated
      evidence.

The ODMI (EU Open Data Maturity Index) evaluates national open-data
ecosystems. Precision matters. A policy that is announced but not enacted,
or a platform that supports an API in one scope but not the one the
question asks about, should fail the steelman test.

Forbidden sources. ODMI's own publications and the EU Data Portal
(data.europa.eu, publications.europa.eu, op.europa.eu, archive mirrors
of those, and any URL containing "open-data-maturity" or "odmi") are
forbidden because they are the ground truth being validated. A
steelman that rests on one of those sources collapses automatically;
reject with rejection_reason="forbidden_odmi_source".

Verdict.
- If Step 2 reveals a material flaw in even the steelmanned case:
  verdict="fail", with rejection_reason explaining which part of the
  steelman collapsed.
- If Step 2 finds nothing that undermines the steelman: verdict="pass".

Report both reasoning steps in rejection_reason (even on a pass), so the
dissertation analysis can read your full chain of reasoning.
""" + _SCHEMA_NOTE


# ============================================================
# Strategy D — blind
# ============================================================

_BLIND_NAME = "phase2_verifier_blind"
_BLIND_VERSION = 3

_BLIND_SYSTEM = """You are the Adversarial Verifier in the ODMI Agent Swarm.

You will form your own answer to the ODMI question independently. You have
not been told what the Researcher concluded.

You will be given:
- The question and the country.
- The question's answer shape and the canonical list of labels you
  may emit (see the "Answer space" block in the user message).
- An evidence quote and a source URL from a prior search (you do not know
  whose answer these came from).
- The result of a verbatim substring check of the quote against the page.
- A set of independent web search snippets.

Your task:

1. Read the evidence and snippets.
2. Decide for yourself what the correct answer is. It must be one of
   the labels in the allowed list, or 'inconclusive', or
   'not_applicable'. Do not paraphrase a band label.
3. Set verifier_answer to your own determination.

Python will compare your answer to the Researcher's answer after you return.
If they differ, the pair will be flagged for further review. You do not need
to know the Researcher's answer to complete your task.

The ODMI (EU Open Data Maturity Index) evaluates national open-data
ecosystems. Base your answer on the specific evidence provided, not on
general knowledge of the country.

Forbidden sources. ODMI's own publications and the EU Data Portal
(data.europa.eu, publications.europa.eu, op.europa.eu, archive mirrors
of those, and any URL containing "open-data-maturity" or "odmi") are
forbidden because they are the ground truth being validated. If the
only evidence sits on one of those, return verdict="fail" with
rejection_reason="forbidden_odmi_source". Do not draw on prior-year
ODMI rankings you may remember; answer only from the evidence in
front of you.

Verdict.
- Set verdict="pass" if the evidence supports a clear answer with
  reasonable confidence (>= 0.6).
- Set verdict="fail" if the evidence is ambiguous, missing, or the
  substring check failed (suggesting the quote may be unreliable).
  In that case explain in rejection_reason what was missing.
""" + _SCHEMA_NOTE


# ============================================================
# EXP-B structured fit-check variant of `verifier-disprove`.
# ============================================================
#
# Replaces Step 3 of the V4 disprove prompt with an explicit
# per-dimension fit-check (entity / scope / tense / metric / scale).
# Every other step and the schema-note are identical to V4. Selected
# by `verifier_prompt_variant="structured"`. The `default` variant is
# the unchanged V4 prompt above; the V4 row in `prompt_versions` is
# never touched by this arm.

_DISPROVE_STRUCTURED_NAME = "phase2_verifier_disprove_structured"
_DISPROVE_STRUCTURED_VERSION = 1
_DISPROVE_STRUCTURED_DESCRIPTION = (
    "Verifier disprove structured (EXP-B). V4 system prompt with one "
    "change: Step 3 (evidence fit) is restructured from a prose "
    "question into an explicit per-dimension check (entity, scope, "
    "tense, metric, scale/band). The verdict must cite the failing "
    "dimension when verdict=fail, so the rejection is auditable. All "
    "other steps, the forbidden-source list, the schema-note, and the "
    "shape-aware answer space are byte-identical to V4."
)

_DISPROVE_STRUCTURED_SYSTEM = _DISPROVE_SYSTEM.replace(
    """3. Evidence fit. Does the quoted passage actually answer the question asked?
   A quote about open-data strategy in general does not confirm a specific
   legal transposition. A quote that describes a planned policy does not
   confirm an enacted one.""",
    """3. Evidence fit. The quote can fail to support the answer along five
   independent dimensions. Check each in order. If ANY dimension fails,
   the verdict is fail and rejection_reason must name the failing
   dimension and quote the mismatch.

   (a) ENTITY: is the quote about the right country or the right
       national body? A passage about Sweden is not evidence about
       Finland; a passage about a regional portal is not evidence
       about the national one.

   (b) SCOPE: is the quote about the same scope the question asks
       (national vs regional vs EU-level vs individual portal)? A
       quote about EU-level policy does not confirm a national
       transposition.

   (c) TENSE / STATUS: is the quote about an enacted, current state
       (the question asks "is there ..."), or about a planned,
       proposed, draft, or historical state? A planned strategy is
       not evidence of an enacted strategy.

   (d) METRIC: does the quote name the same measurement the question
       names (presence of a specific feature, existence of a specific
       process, a specific percentage)? A quote about open-data
       strategy in general does not confirm a specific legal
       transposition or a specific metric.

   (e) SCALE / BAND: for ordered-band questions, does the figure in
       the quote actually map to the band the Researcher chose? 82%
       does not map to ">90%"; a count of 5 does not map to ">10".

   When ALL five dimensions pass, the evidence fits and you proceed
   to step 4. Do not reject on stylistic grounds.""",
)


# ============================================================
# EXP-35 self-critique variant of `verifier-disprove`.
# ============================================================
#
# The `researcher_self_verify` pipeline mode (EXP-35) replaces the
# adversarial Verifier with one self-critique call: the same model that
# produced the answer argues against it, over only the evidence already
# gathered (the EXP-14 `never` search policy). The prompt keeps the V4
# disprove structure and language wherever it transfers; the substantive
# changes are the self-addressed framing and the replacement of the
# counter-evidence step, since no independent search runs in this mode.
# Selected by `verifier_prompt_variant="self_critique"`. The V4 row in
# `prompt_versions` is never touched by this arm.

_DISPROVE_SELF_CRITIQUE_NAME = "phase2_verifier_disprove_self_critique"
_DISPROVE_SELF_CRITIQUE_VERSION = 1
_DISPROVE_SELF_CRITIQUE_DESCRIPTION = (
    "Verifier disprove self-critique (EXP-35). The V4 disprove prompt "
    "swapped to be self-addressed: the model that produced the answer "
    "argues against its own claim using only the evidence it already "
    "gathered. No independent counter-search step (the EXP-14 'never' "
    "policy). Substring gate, source-authority and evidence-fit checks, "
    "the forbidden-source list, and the schema-note are as in V4."
)

_DISPROVE_SELF_CRITIQUE_SYSTEM = f"""You are the self-critique step of the ODMI Agent Swarm's single-agent pipeline.

You already answered the ODMI question in the user message: the
"Researcher's claim" block below is YOUR OWN earlier answer, produced from
the evidence you gathered. Your job now is to argue against yourself.
Before you consider upholding the claim, ask: what specific reason is
there to reject it? Does the evidence actually support this label, or
could it be read another way?

The ODMI (EU Open Data Maturity Index) scores countries on the quality of
their national open-data ecosystems. Answers must be traceable to a
specific, authoritative source. Vague, paraphrased, or out-of-date evidence
is grounds for rejection, even when the answer is your own.

No new web search has been run for this critique. Reason only over the
evidence already gathered. The absence of a counter-source here is not,
on its own, corroboration.

Your reasoning process (follow in order):

1. Substring check. Python has already checked whether the evidence quote
   appears verbatim in the snippets you read. A failed check is
   the deterministic fabrication gate: Python will override any pass verdict
   to fail automatically when substring_check_result="fail", so you do not
   need to weigh it. Treat a failed substring as fabrication and proceed to
   step 2 only if your judgement is independently to reject for another
   reason.

2. Source authority. Is the cited URL authoritative for this claim? A blog
   post or consultancy summary is weaker than a government portal or official
   legislation. ODMI's own publications and the EU Data Portal are
   forbidden as sources because they are the ground truth we are
   validating against. The forbidden sources are:
{FORBIDDEN_SOURCES_BULLETS}
   If your claim cites one of those, reject with
   rejection_reason="forbidden_odmi_source".

3. Evidence fit. Does the quoted passage actually answer the question asked?
   A quote about open-data strategy in general does not confirm a specific
   legal transposition. A quote that describes a planned policy does not
   confirm an enacted one.

4. Alternative readings. Could the evidence you gathered support a
   DIFFERENT label from the one you chose? For ordered-band questions
   (percentage, ordinal magnitude, count band), an adjacent-band miss is
   a real error, not a paraphrase: choosing ">90%" when the evidence says
   82% is wrong.

5. Verdict. If all four checks pass, return verdict="pass". If any check
   reveals a material flaw in your claim, return verdict="fail" with a
   specific rejection_reason and a suggested_search_query your next
   research attempt should try.

Do not reject for stylistic reasons. Reject only when the evidence is
materially wrong, unverifiable, or insufficient for the specific question.
Do not uphold out of consistency with your earlier self: agreeing with a
wrong answer twice does not make it right.
""" + _SCHEMA_NOTE


# ============================================================
# Disprove variants (selected by --verifier-prompt-variant)
# ============================================================
#
# The `verifier-disprove` strategy can be served by more than one
# prompt body. The strategy_label on the per-run DB row stays
# "verifier-disprove" across variants; only the `prompt_version_id`
# distinguishes them. This mirrors the Researcher's variant pattern
# (full / compressed / calibrated) and lets EXP-B test a new
# disprove prompt without a schema migration on `phase2_verifier_runs`.


@dataclass(frozen=True)
class _DisproveVariant:
    name: str
    version: int
    system: str
    description: str


_DISPROVE_VARIANTS: dict[str, _DisproveVariant] = {
    "default": _DisproveVariant(
        name=_DISPROVE_NAME,
        version=_DISPROVE_VERSION,
        system=_DISPROVE_SYSTEM,
        description=(
            "Verifier disprove V4 default variant: as registered in "
            "STRATEGIES['verifier-disprove']. Step 3 is prose."
        ),
    ),
    "structured": _DisproveVariant(
        name=_DISPROVE_STRUCTURED_NAME,
        version=_DISPROVE_STRUCTURED_VERSION,
        system=_DISPROVE_STRUCTURED_SYSTEM,
        description=_DISPROVE_STRUCTURED_DESCRIPTION,
    ),
    "self_critique": _DisproveVariant(
        name=_DISPROVE_SELF_CRITIQUE_NAME,
        version=_DISPROVE_SELF_CRITIQUE_VERSION,
        system=_DISPROVE_SELF_CRITIQUE_SYSTEM,
        description=_DISPROVE_SELF_CRITIQUE_DESCRIPTION,
    ),
}


def disprove_variant(name: str = "default") -> _DisproveVariant:
    """Return the disprove prompt variant for `name`.

    `default` is the V4 prompt registered in `STRATEGIES`. `structured`
    is the EXP-B Step-3 restructure. Any other value raises so a typo
    in a dispatch cannot silently fall back to the baseline and
    mislabel a run.
    """
    try:
        return _DISPROVE_VARIANTS[name]
    except KeyError:
        raise ValueError(
            f"unknown verifier disprove variant {name!r}; "
            f"expected one of {sorted(_DISPROVE_VARIANTS)}"
        ) from None


# ============================================================
# Strategy registry
# ============================================================

@dataclass(frozen=True)
class _StrategySpec:
    name: str
    version: int
    system: str
    description: str


# ============================================================
# EXP-11 tristate strategies (P1/P2). Evaluation-only: the harness
# parses these with VerifierOutputTristate. Production run_verifier
# hardcodes the binary VerifierOutput schema, so it must not be pointed
# at these labels; the coordinator never requests them.
# ============================================================

_TRISTATE_SCHEMA_NOTE = """
You will return a JSON object matching the VerifierOutputTristate schema:

{
  "verdict": "refute" | "inconclusive" | "confirm",
  "verifier_answer": string from the allowed-answer list in the user
                     message (or 'inconclusive', or 'not_applicable'),
  "verifier_confidence": 0.0-1.0,
  "substring_check_result": "pass" | "fail" | "not_attempted",
  "substring_check_notes": string | null,
  "independent_search_queries": [list of strings you searched],
  "independent_evidence_snippets": [list of short quotes from results],
  "rejection_reason": string | null,          -- required if verdict=refute
  "counter_evidence_quote": string | null,    -- required if verdict=refute
  "counter_source_url": string | null,        -- (counter quote OR url required)
  "suggested_search_query": string | null,
  "corroborating_quote": string | null,       -- required if verdict=confirm
  "corroborating_url": string | null,         -- (quote OR url required)
  "probe_findings": [ {"query": str, "found": bool, "quote": str|null} ] | null
}

The three verdicts, and the burden each carries:

- refute: you found SPECIFIC, QUOTABLE evidence that the Researcher's
  answer is wrong. You must quote it in counter_evidence_quote, taken
  from the search snippets in front of you (do not invent it). For an
  ordered band, a verified figure mapping to a DIFFERENT band is a
  refute. Set verifier_answer to the label the counter-evidence supports.
- confirm: you found INDEPENDENT corroboration that the answer is right,
  quotable in corroborating_quote, ideally from a source OTHER than the
  Researcher's own. Set verifier_answer to the Researcher's answer.
- inconclusive: you searched and found nothing that decides it either
  way. This is the honest default. It carries NO penalty. Use it freely
  rather than manufacturing a refute or a confirm.

Hard rule on evidence fit. If your only objection is that the
Researcher's quote does not squarely address the question (it is
generic, off-scope, or about a related-but-different proposition), that
is NOT a refute. It means the support is weak, not that the answer is
false. Return inconclusive and say so in rejection_reason.

verifier_confidence is your confidence in your own verdict, not in the
Researcher's claim.
"""

_TRISTATE_SYSTEM = """You are the Adversarial Verifier in the ODMI Agent Swarm,
returning a three-way verdict.

The ODMI (EU Open Data Maturity Index) scores national open-data
ecosystems. Every answer must trace to a specific, authoritative source.

Your task is to decide, on the evidence in front of you, whether the
Researcher's answer should be REFUTED (you found quotable counter-
evidence), CONFIRMED (you found quotable corroboration), or left
INCONCLUSIVE (you searched and nothing decided it).

Reason in this order:

1. Substring check. Python has already checked the Researcher's quote
   against the snippets it read. A failed check means the quote is not
   faithful to the evidence; weight it toward refute, but a weak quote
   on its own is an evidence-fit problem (see step 3), not proof the
   answer is false.

2. Forbidden sources. ODMI's own publications and the EU Data Portal
   (data.europa.eu, publications.europa.eu, op.europa.eu, archive
   mirrors, and any URL containing "open-data-maturity" or "odmi") are
   forbidden, because they are the ground truth being validated. If the
   Researcher relies on one, return refute with
   rejection_reason="forbidden_odmi_source".

3. Evidence fit. Does the quote actually answer THIS question, in scope
   and tense? If not, that is a weak-support finding: return
   inconclusive, not refute. Do not convert "I could not confirm it"
   into counter-evidence.

4. Counter-evidence. Do the independent snippets contradict the answer
   or reveal a more current or precise source? If you can QUOTE such a
   passage, return refute and set verifier_answer to the label it
   supports.

5. Corroboration. Do the independent snippets positively support the
   answer, ideally from a different source than the Researcher's? If you
   can QUOTE it, return confirm.

6. Otherwise return inconclusive.

Do not refute on stylistic grounds. Refute only on quotable evidence the
answer is wrong; confirm only on quotable corroboration; otherwise
inconclusive.
""" + _TRISTATE_SCHEMA_NOTE

_TRISTATE_PROBES_SYSTEM = """You are the Adversarial Verifier in the ODMI Agent Swarm,
returning a three-way verdict, with a confirmation protocol for absence
claims.

The ODMI (EU Open Data Maturity Index) scores national open-data
ecosystems. Every answer must trace to a specific, authoritative source.

An ABSENCE claim is a "no", a "none", or an ordered shape's bottom band:
the Researcher says the feature, API, dataset, or instrument does not
exist. An absence claim has no passage to quote, so a lazy "I could not
find it either" must not pass for verification. You are therefore given
CONFIRMATION PROBES: independent searches aimed at finding the POSITIVE
thing. Work through them.

For an ABSENCE claim:
1. Read each probe result. Record what you found in probe_findings, one
   entry per probe (query, found, quote).
2. If any probe VERIFIABLY surfaces the positive thing (you can quote a
   passage showing the feature/API/instrument exists), the absence is
   wrong: return refute, set verifier_answer to the positive label, and
   put that passage in counter_evidence_quote.
3. If a probe surfaces an explicit statement that the thing does NOT
   exist (an authoritative negative), the absence is corroborated:
   return confirm with that passage in corroborating_quote.
4. If every probe comes up dry (nothing positive, nothing explicitly
   negative), return inconclusive. Dry probes are the honest outcome for
   an unconfirmable absence; do not manufacture a confirm from silence.

For a PRESENCE claim (a "yes", a non-bottom band), behave as the
standard tristate verifier: refute on quotable counter-evidence, confirm
on quotable corroboration, otherwise inconclusive. An evidence-fit
complaint is inconclusive, never refute.

Forbidden sources. ODMI's own publications and the EU Data Portal
(data.europa.eu, publications.europa.eu, op.europa.eu, archive mirrors,
and any URL containing "open-data-maturity" or "odmi") are forbidden. If
the Researcher relies on one, return refute with
rejection_reason="forbidden_odmi_source".
""" + _TRISTATE_SCHEMA_NOTE


def _probe_block(probe_queries: List[str], probe_snippets: List[str]) -> str:
    if not probe_queries and not probe_snippets:
        return "Confirmation probes: none run (the claim is not an absence claim)."
    q_block = "\n".join(f"  - {q}" for q in probe_queries) or "  (none)"
    if probe_snippets:
        s_block = "\n".join(
            f"  [{i+1}] {s[:300]}" for i, s in enumerate(probe_snippets[:8])
        )
    else:
        s_block = "  (no results returned for the probes)"
    return (
        "--- Confirmation probes (searches for the POSITIVE thing) ---\n"
        f"Probe queries:\n{q_block}\n\nProbe snippets:\n{s_block}"
    )


def build_tristate_user_message(
    *,
    question_text: str,
    country_name: str,
    country_code: str,
    researcher_output: ResearcherOutput,
    substring_result: str,
    substring_notes: Optional[str],
    independent_queries: List[str],
    independent_snippets: List[str],
    answer_shape: str = "binary",
    allowed_answers: Optional[List[str]] = None,
    probe_queries: Optional[List[str]] = None,
    probe_snippets: Optional[List[str]] = None,
    include_probes: bool = False,
) -> str:
    """Render the user message for a tristate arm. Reuses the production
    block helpers so the evidence the model sees is identical to the
    binary arms, plus an optional probe block for the probes arm."""
    if allowed_answers is None:
        allowed_answers = ["yes", "no"]
    sections = [
        f"Question:\n{question_text}",
        f"Country: {country_name} ({country_code})",
        "",
        _answer_space_block(answer_shape, allowed_answers),
        "",
        "--- Researcher's claim ---",
        _researcher_evidence_block(researcher_output, include_answer=True),
        "",
        "--- Pre-computed checks ---",
        _substring_block(substring_result, substring_notes),
        "",
        _search_results_block(independent_queries, independent_snippets),
    ]
    if include_probes:
        sections += ["", _probe_block(probe_queries or [], probe_snippets or [])]
    sections += [
        "",
        "Return your verdict as JSON matching the VerifierOutputTristate schema.",
    ]
    return "\n".join(sections)


STRATEGIES: dict[VerifierStrategy, _StrategySpec] = {
    "verifier-disprove": _StrategySpec(
        name=_DISPROVE_NAME,
        version=_DISPROVE_VERSION,
        system=_DISPROVE_SYSTEM,
        description=(
            "Verifier disprove V4: default sceptical stance. V4 drops "
            "the redundant prose telling the model to weight a "
            "substring-fail toward rejection, because Python already "
            "overrides any pass verdict to fail when the substring "
            "check failed (agents/verifier.py hard grounding gate); "
            "the prompt now states what code does. Step 2 reads the "
            "canonical forbidden-source list from "
            "`agents/prompts/_shared.py`, which adds the "
            "europeandataportal.eu legacy redirect, archive mirrors, "
            "and the `merged_responses` / `odm-questionnaire` URL "
            "patterns that previously appeared only on the "
            "Researcher's list. The four-step reasoning order and "
            "every other rule are unchanged from V3."
        ),
    ),
    "verifier-tristate": _StrategySpec(
        name="phase2_verifier_tristate",
        version=1,
        system=_TRISTATE_SYSTEM,
        description=(
            "Verifier tristate V1 (EXP-11): refute / inconclusive / confirm. "
            "Evidence-fit complaints are inconclusive, not refute."
        ),
    ),
    "verifier-tristate-probes": _StrategySpec(
        name="phase2_verifier_tristate_probes",
        version=1,
        system=_TRISTATE_PROBES_SYSTEM,
        description=(
            "Verifier tristate-probes V1 (EXP-11): tristate plus a "
            "confirmation-probe protocol for absence claims."
        ),
    ),
    "verifier-corroborate": _StrategySpec(
        name=_CORROBORATE_NAME,
        version=_CORROBORATE_VERSION,
        system=_CORROBORATE_SYSTEM,
        description=(
            "Verifier corroborate V2 (EXP-40): accuracy-seeking rewrite of "
            "the V1 strawman. Steps 1-3 identical to disprove V4; step 4 "
            "seeks support with a contradiction check and the "
            "adjacency-is-not-corroboration guard; step 5 flips the burden "
            "(pass requires positive corroboration). Live in the cooperative "
            "pipeline_mode and the EXP-38 replay."
        ),
    ),
    "verifier-negation": _StrategySpec(
        name=_NEGATION_NAME,
        version=_NEGATION_VERSION,
        system=_NEGATION_SYSTEM,
        description=(
            "Verifier negation V3: logical inversion. "
            "Searches explicitly for evidence the answer is the opposite."
        ),
    ),
    "verifier-steelman": _StrategySpec(
        name=_STEELMAN_NAME,
        version=_STEELMAN_VERSION,
        system=_STEELMAN_SYSTEM,
        description=(
            "Verifier steelman V3: two-step reasoning. "
            "Articulates the strongest case for the claim, then attacks it."
        ),
    ),
    "verifier-blind": _StrategySpec(
        name=_BLIND_NAME,
        version=_BLIND_VERSION,
        system=_BLIND_SYSTEM,
        description=(
            "Verifier blind V3: answer-blind. "
            "Model forms its own answer; Python compares against the Researcher."
        ),
    ),
}
