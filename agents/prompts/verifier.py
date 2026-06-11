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
) -> str:
    """Render the user message for the given strategy.

    Python has already run the substring check and the independent
    search before this call. Those results are injected here so the
    model's reasoning is grounded in verified facts, not its own
    speculation about what the page might say.
    """
    include_answer = (strategy != "verifier-blind")
    if allowed_answers is None:
        allowed_answers = ["yes", "no"]

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
        _search_results_block(independent_queries, independent_snippets),
        "",
        "Return your verdict as JSON matching the VerifierOutput schema.",
    ]
    return "\n".join(sections)


# ============================================================
# Strategy A — disprove
# ============================================================

_DISPROVE_NAME = "phase2_verifier_disprove"
_DISPROVE_VERSION = 3

_DISPROVE_SYSTEM = """You are the Adversarial Verifier in the ODMI Agent Swarm.

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
   appears verbatim in the cited source page. If the check failed, that is
   strong evidence of fabrication or misquoting; weight it heavily toward
   rejecting.

2. Source authority. Is the cited URL authoritative for this claim? A blog
   post or consultancy summary is weaker than a government portal or official
   legislation. ODMI's own publications and the EU Data Portal
   (data.europa.eu, publications.europa.eu, op.europa.eu, archive
   mirrors of those, and any URL containing "open-data-maturity" or
   "odmi") are forbidden as sources because they are the ground truth
   we are validating against. If the Researcher cites one of those,
   reject with rejection_reason="forbidden_odmi_source".

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
            "Verifier disprove V3: default sceptical stance. "
            "Asks what is wrong with the claim before considering acceptance."
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
