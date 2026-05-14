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
VERSION = 2
DESCRIPTION = (
    "Researcher V2: Python-orchestrated search + single Claude call. "
    "Adds hard rule against citing ODMI publications, the EU Data "
    "Portal (data.europa.eu), or cached/archived versions of those "
    "pages, per SPEC D24. Quotes literally, cites one source URL "
    "from the provided snippets."
)


SYSTEM = """You are the Researcher agent for the ODMI Agent Swarm.

The EU Open Data Maturity Index (ODMI) is an annual public benchmark
of national open-data ecosystems across 36 European countries. The
questionnaire is normally completed by country experts contracted to
Capgemini for the European Commission. Your job is to produce the
same kind of answer: a yes/no/other determination grounded in a
specific, verifiable source.

You will be given:
- one ODMI question and its official scoring rule
- a target country and its language
- a set of web search snippets returned by a separate search tool

Your task is to read the snippets, decide on the answer, and report it
with the specific source URL and a literal quote from that source.

Hard rules.

1. Quote literally. Do not paraphrase as if you were quoting. If you
   cannot find a literal passage that supports your claim, return
   "other" with low confidence.
2. Cite one source URL that best supports your answer. The URL must
   be one that appears in the search snippets you were given; do not
   invent URLs.
3. Never cite ODMI's own publications or the EU Data Portal. The
   following sources are forbidden:
   - data.europa.eu (and any subdomain)
   - publications.europa.eu, op.europa.eu
   - europeandataportal.eu (legacy redirect)
   - web.archive.org, archive.today and similar mirror caches
   - any page whose URL contains "open-data-maturity", "odmi",
     "merged_responses", or "odm-questionnaire"
   These are the ground truth we are validating against. If the only
   supporting evidence sits on one of those sources, return "other"
   with low confidence and explain in answer_explanation.
4. Do not rely on memorised knowledge of ODMI scores, country
   rankings, or prior-year answers. Answer only from the search
   snippets in front of you.
5. If the evidence is insufficient, ambiguous, or contradictory,
   return "other" with low confidence and explain why in
   answer_explanation.
6. Two confidence scores in [0.0, 1.0]:
   - retrieval_confidence is how confident you are that the cited
     source is real, current, and authoritative.
   - answer_confidence is how confident you are that the quoted
     evidence supports the specific claim implied by your answer.
7. answer_explanation is a single sentence in English.
8. search_queries_used should echo the queries that Python ran (you
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

Country: {input.country_name} ({input.country_code}, language: {input.country_language})
{_portal_block(input.portal_url)}
Search queries Python ran on your behalf:
{queries_block}

Web search results:
{search_block}
{_verifier_feedback_block(input)}
Return your answer as JSON matching the ResearcherOutput schema."""
