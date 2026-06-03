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

from typing import List

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
    # EXP-7 chained arm: the Verifier's own counter-evidence, handed back so
    # the Researcher can weigh it rather than rediscover it. Only present when
    # the chained arm populated these fields; baseline retries leave them None.
    if fb.counter_evidence_quote:
        parts.append(
            f"Counter-evidence the Verifier found: \"{fb.counter_evidence_quote}\""
        )
    if fb.counter_source_url:
        parts.append(f"Counter-evidence source: {fb.counter_source_url}")
    parts.append("")
    return "\n".join(parts)


def _prior_evidence_block(input: ResearcherInput) -> str:
    """EXP-7 chained arm: the accumulated evidence corpus from prior rounds.

    Renders nothing when `prior_evidence` is empty, which is always the case
    in the baseline (independent-retry) loop, so the user message is
    byte-identical there. The using instruction lives in this block rather
    than the system prompt so the system prompt, and therefore the registered
    prompt version, stays unchanged across both arms.
    """
    items = input.prior_evidence
    if not items:
        return ""
    lines = [
        "",
        "--- Evidence gathered on earlier attempts in this investigation ---",
        "This is the running corpus from previous rounds (both your earlier",
        "searches and the Verifier's). Use it as additional context alongside",
        "the fresh snippets above. You must still cite a source URL that",
        "appears in the snippets you were given on this attempt.",
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
{_verifier_feedback_block(input)}{_prior_evidence_block(input)}
Return your answer as JSON matching the ResearcherOutput schema."""
