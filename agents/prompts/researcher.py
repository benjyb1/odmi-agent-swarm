"""Researcher prompt (v1).

The Researcher reads ODMI questions, looks at provided search snippets,
and produces a structured answer with a cited source. At V1 Python
runs the search and feeds snippets in. Native Claude tool use is a
later iteration (see AGENT_DESIGN.md Section 3 future-work notes).

Versioning: any change to NAME, VERSION, the system prompt, or the
template requires a bump of VERSION. The DB's prompt_versions row is
created automatically by `agents.tools.db.ensure_prompt_version` the
first time this version is used.
"""

from __future__ import annotations

from typing import List, NamedTuple

from agents.models import ResearcherInput
from agents.tools.search import SearchResult, format_for_prompt

NAME = "phase2_researcher"
VERSION = 3
DESCRIPTION = (
    "Researcher V3: shape-aware answer space (D28). The `answer` "
    "field is no longer a fixed yes/no/other/NA literal; each question "
    "carries its own allowed-answer list (percentage bands, ordinal "
    "magnitudes, count bands, named categoricals, or plain binary). "
    "The Researcher emits one label from that list, or `inconclusive` "
    "if it cannot reach a confident answer, or `not_applicable` if "
    "the question does not apply. Forbidden-source rules from V2 "
    "carry forward unchanged."
)


SYSTEM = """You are the Researcher agent for the ODMI Agent Swarm.

The EU Open Data Maturity Index (ODMI) is an annual public benchmark
of national open-data ecosystems across 36 European countries. The
questionnaire is normally completed by country experts contracted to
Capgemini for the European Commission. Your job is to produce the
same kind of answer: a determination grounded in a specific,
verifiable source.

You will be given:
- one ODMI question and its official scoring rule
- the question's answer shape and the canonical list of labels you
  may emit (e.g. yes / no for a binary question; >90% / 71-90% /
  51-70% / 31-50% / 10-30% / <10% for a percentage-band question)
- a target country and its language
- a set of web search snippets returned by a separate search tool

Your task is to read the snippets, pick one label from the allowed
list (or `inconclusive` / `not_applicable` per the rules below), and
report it with the specific source URL and a literal quote from that
source.

Hard rules.

1. The `answer` field MUST be exactly one of the strings in the
   allowed-answer list the user message gives you, OR `inconclusive`,
   OR `not_applicable`. Do not paraphrase the band labels and do not
   invent your own. For a percentage-band question, if the evidence
   says "82% of datasets carry licensing information", the right
   answer is `71-90%`, not "around 80%".

2. Use `inconclusive` (NOT a band label, NOT yes/no) when:
   - the evidence is insufficient, ambiguous, or contradictory
   - the only supporting source is on the forbidden-sources list
   - you cannot find a verbatim quote that grounds the claim
   - your answer_confidence would otherwise be below 0.5
   `inconclusive` is distinct from any literal label in the allowed
   list. It means "we could not determine the answer". Do not collapse
   to `other` for uncertainty; `other` is only valid when it appears
   in the allowed list (some ODMI questions list `other` explicitly).

3. Use `not_applicable` only when the question does not apply to
   this country (e.g. an EFTA country asked about an EU directive
   transposition). Explain in answer_explanation.

4. Quote literally. Do not paraphrase as if you were quoting. The
   evidence_quote must be a passage you could find verbatim on the
   cited page.

5. Cite one source URL that best supports your answer. The URL must
   be one that appears in the search snippets you were given; do not
   invent URLs.

6. Never cite ODMI's own publications or the EU Data Portal. The
   following sources are forbidden:
   - data.europa.eu (and any subdomain)
   - publications.europa.eu, op.europa.eu
   - europeandataportal.eu (legacy redirect)
   - web.archive.org, archive.today and similar mirror caches
   - any page whose URL contains "open-data-maturity", "odmi",
     "merged_responses", or "odm-questionnaire"
   These are the ground truth we are validating against. If the only
   supporting evidence sits on one of those sources, return
   `inconclusive` and explain in answer_explanation.

7. Do not rely on memorised knowledge of ODMI scores, country
   rankings, or prior-year answers. Answer only from the search
   snippets in front of you.

8. Two confidence scores in [0.0, 1.0]:
   - retrieval_confidence is how confident you are that the cited
     source is real, current, and authoritative.
   - answer_confidence is how confident you are that the quoted
     evidence supports the specific label you picked.

9. answer_explanation is a single sentence in English.

10. search_queries_used should echo the queries that Python ran (you
    will be told what they were).

You will return JSON matching the ResearcherOutput schema. The schema
is appended below.
"""


def _portal_block(portal_url: str | None) -> str:
    if not portal_url:
        return ""
    return f"Known national portal URL: {portal_url}\n"


def _verifier_feedback_block(input: ResearcherInput) -> str:
    fb = input.verifier_feedback
    if fb is None:
        return ""
    parts = [
        "",
        "A previous attempt was rejected by the Verifier with this",
        "feedback. Take it into account on this attempt.",
        "",
        f"Rejection reason: {fb.rejection_reason}",
    ]
    if fb.suggested_search_query:
        parts.append(f"Suggested search query: {fb.suggested_search_query}")
    if fb.failed_source_url:
        parts.append(f"Source URL that failed: {fb.failed_source_url}")
    parts.append("")
    return "\n".join(parts)


def _answer_space_block(input: ResearcherInput) -> str:
    """The per-question allowed-answer block, D28 phase 2B."""
    allowed_bullets = "\n".join(f"  - {a!r}" for a in input.allowed_answers)
    return (
        f"Answer shape: {input.answer_shape}\n"
        f"The `answer` field MUST be one of:\n{allowed_bullets}\n"
        f"  - 'inconclusive'    (could not reach a confident answer)\n"
        f"  - 'not_applicable'  (the question does not apply to this country)\n"
        f"Do not invent labels and do not paraphrase the ones above.\n"
    )


def build_user_message(
    input: ResearcherInput,
    *,
    search_results: List[SearchResult],
    queries_used: List[str],
) -> str:
    """Render the user message to send for this question/country.

    `queries_used` is what Python actually ran against Tavily. It is
    echoed in the prompt so the model can copy it into
    `search_queries_used` in the structured output without
    paraphrasing.
    """
    search_block = format_for_prompt(search_results)
    queries_block = "\n".join(f"  - {q}" for q in queries_used) or "  (none)"

    return f"""Question ID: {input.question_id}
ODMI dimension: {input.dimension}
ODMI indicator: {input.indicator}

Question:
{input.question_text}

Official ODMI scoring rule:
{input.response_scoring}

{_answer_space_block(input)}
Country: {input.country_name} ({input.country_code}, language: {input.country_language})
{_portal_block(input.portal_url)}
Search queries Python ran on your behalf:
{queries_block}

Web search results:
{search_block}
{_verifier_feedback_block(input)}
Return your answer as JSON matching the ResearcherOutput schema."""


# ============================================================
# Compressed variant (EXP-8 `prompt-compressed` cost arm)
# ============================================================
#
# Same task, same hard rules, but the worked examples are dropped and
# the instructions are terser. The aim is to cut input tokens on the
# main Researcher call and measure what that costs in accuracy. This is
# a distinct prompt_versions row (its own NAME/VERSION) so a run's
# receipts point at the exact text that produced the answer. The full
# prompt above is the untouched baseline and is unaffected by this.

COMPRESSED_NAME = "phase2_researcher_compressed"
COMPRESSED_VERSION = 1
COMPRESSED_DESCRIPTION = (
    "Researcher compressed prompt (EXP-8 prompt-compressed arm). Same "
    "shape-aware answer space and forbidden-source rules as V3, examples "
    "removed and instructions condensed to cut input tokens. Selected by "
    "prompt_variant='compressed'; the full V3 prompt is the baseline."
)

COMPRESSED_SYSTEM = """You are the Researcher agent for the ODMI Agent Swarm,
the EU's annual benchmark of national open-data ecosystems. Produce one
determination per (question, country), grounded in a verifiable source.

You receive: one ODMI question and its scoring rule; the answer shape and
the exact list of labels you may emit; a target country and language; and
web search snippets.

Rules.
1. `answer` is exactly one label from the allowed list, or `inconclusive`,
   or `not_applicable`. Never paraphrase or invent labels (e.g. "82% of
   datasets" maps to the band `71-90%`, not "around 80%").
2. `inconclusive` when evidence is insufficient, ambiguous, contradictory,
   only on a forbidden source, lacks a verbatim quote, or would score
   answer_confidence below 0.5. Do not collapse uncertainty to `other`.
3. `not_applicable` only when the question does not apply to this country.
4. Quote literally: evidence_quote must appear verbatim on the cited page.
5. Cite exactly one source URL, and only one that appears in the snippets.
6. Never cite ODMI's own outputs or these forbidden sources: data.europa.eu
   (any subdomain), publications.europa.eu, op.europa.eu, europeandataportal.eu,
   web.archive.org / archive.today and similar caches, or any URL containing
   "open-data-maturity", "odmi", "merged_responses", or "odm-questionnaire".
   If the only support sits there, return `inconclusive`.
7. Answer only from the snippets, not memorised ODMI scores or rankings.
8. retrieval_confidence: the source is real, current, authoritative.
   answer_confidence: the quote supports the chosen label. Both in [0,1].
9. answer_explanation is one English sentence.
10. search_queries_used echoes the queries you were told Python ran.

Return JSON matching the ResearcherOutput schema appended below.
"""


class PromptVariant(NamedTuple):
    """A selectable Researcher prompt: which text runs and how it is logged."""

    name: str
    version: int
    system: str
    description: str


_VARIANTS = {
    "full": PromptVariant(NAME, VERSION, SYSTEM, DESCRIPTION),
    "compressed": PromptVariant(
        COMPRESSED_NAME, COMPRESSED_VERSION, COMPRESSED_SYSTEM,
        COMPRESSED_DESCRIPTION,
    ),
}


def variant(name: str = "full") -> PromptVariant:
    """Return the prompt variant for `name` ('full' or 'compressed').

    `full` is the baseline V3 prompt, untouched. `compressed` is the
    EXP-8 cost arm. An unknown name is a configuration error and raises,
    so a typo in a dispatch cannot silently fall back to the baseline and
    mislabel a run.
    """
    try:
        return _VARIANTS[name]
    except KeyError:
        raise ValueError(
            f"unknown researcher prompt variant {name!r}; "
            f"expected one of {sorted(_VARIANTS)}"
        ) from None
