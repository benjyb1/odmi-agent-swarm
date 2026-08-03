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
from agents.prompts._shared import FORBIDDEN_SOURCES_BULLETS
from agents.tools.search import SearchResult, format_for_prompt

NAME = "phase2_researcher"
VERSION = 5
DESCRIPTION = (
    "Researcher V5: raises the in-prompt abstention floor from 0.5 to "
    "0.65, so the Researcher returns `inconclusive` on exactly the "
    "confidence the Coordinator would refuse to commit anyway. Every "
    "agent now works to one 0.65 floor instead of each carrying its "
    "own. The calibration anchors, the answer space and every other "
    "rule are byte-identical to V4; only the number changed. "
    "V4 was: V3 shape-aware answer space (D28) plus two "
    "wording fixes. Rule 4 (verbatim quote) now states explicitly "
    "that the quote must come from the snippets in the user message "
    "rather than memory or training data, closing a hole the "
    "deterministic substring gate was already catching after the "
    "fact. Rule 6 (forbidden sources) now reads from the canonical "
    "shared list in `agents/prompts/_shared.py`, which adds the "
    "europeandataportal.eu legacy redirect, the archive mirrors, and "
    "the `merged_responses` / `odm-questionnaire` URL patterns that "
    "previously appeared only on the Researcher's list. Behaviour "
    "for everything else is byte-identical to V3."
)


SYSTEM = f"""You are the Researcher agent for the ODMI Agent Swarm.

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
   - your answer_confidence would otherwise be below 0.65
   `inconclusive` is distinct from any literal label in the allowed
   list. It means "we could not determine the answer". Do not collapse
   to `other` for uncertainty; `other` is only valid when it appears
   in the allowed list (some ODMI questions list `other` explicitly).

3. Use `not_applicable` only when the question does not apply to
   this country (e.g. an EFTA country asked about an EU directive
   transposition). Explain in answer_explanation.

4. Quote literally from the snippets shown to you in this message.
   Do not paraphrase, and do not draw on text from memory or training
   data. The evidence_quote must appear verbatim in one of the
   snippets below; a deterministic substring gate will reject any
   quote that does not.

5. Cite one source URL that best supports your answer. The URL must
   be one that appears in the search snippets you were given; do not
   invent URLs.

6. Never cite ODMI's own publications or the EU Data Portal. The
   following sources are forbidden:
{FORBIDDEN_SOURCES_BULLETS}
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
    max_chars_per_snippet: int = 600,
) -> str:
    """Render the user message to send for this question/country.

    `queries_used` is what Python actually ran against Tavily. It is
    echoed in the prompt so the model can copy it into
    `search_queries_used` in the structured output without
    paraphrasing.

    `max_chars_per_snippet` is the EXP-17 per-snippet prompt-truncation
    knob, forwarded to `format_for_prompt`. The default (600) keeps the
    rendered block byte-identical to current production.
    """
    search_block = format_for_prompt(
        search_results, max_chars_per_snippet=max_chars_per_snippet,
    )
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


# Compressed variant (EXP-8 `prompt-compressed` cost arm)
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
   answer_confidence below 0.65. Do not collapse uncertainty to `other`.
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


# Calibrated variant (EXP-A `calibration anchors` arm).
# Same V4 ten-rule structure with concrete anchors added to Rule 8 for
# retrieval_confidence and answer_confidence, so the [0, 1] scores carry a
# consistent meaning across runs and models. Hypothesis: a calibrated
# answer_confidence lets the 0.65 commit floor catch the wrong commits it
# was designed to catch, lowering neg-FPR without much movement in
# abstention. Distinct prompt_versions row so receipts trace to the exact
# text. The full V4 above is the untouched baseline; the compressed arm
# is the existing EXP-8 cost arm and is independent of this one.

CALIBRATED_NAME = "phase2_researcher_calibrated"
CALIBRATED_VERSION = 1
CALIBRATED_DESCRIPTION = (
    "Researcher V4 plus calibration anchors (EXP-A). Rule 8 now gives "
    "concrete worked anchors for retrieval_confidence at 0.3 / 0.6 / 0.9 "
    "(secondary commentary, general primary page, specific authoritative "
    "page) and answer_confidence at 0.5 / 0.7 / 0.9 (on-topic but "
    "inferred, fact maps to the label with light interpretation, quote "
    "states the answer directly). All other rules and the answer space "
    "are byte-identical to the V4 baseline. Selected by "
    "prompt_variant='calibrated'."
)

CALIBRATED_SYSTEM = SYSTEM.replace(
    """8. Two confidence scores in [0.0, 1.0]:
   - retrieval_confidence is how confident you are that the cited
     source is real, current, and authoritative.
   - answer_confidence is how confident you are that the quoted
     evidence supports the specific label you picked.""",
    """8. Two confidence scores in [0.0, 1.0]. Use the worked anchors below
   rather than choosing a number by feel; the scores must carry the
   same meaning across runs so the downstream floor and the
   adjudicator can read them.

   retrieval_confidence is your confidence the cited source is real,
   current, and authoritative for this kind of claim.
     - 0.3 = the source exists but is a secondary commentary (blog,
       consultancy summary, news article that paraphrases an unnamed
       official source).
     - 0.6 = the source is a primary government or EU page but is
       general (a portal homepage, a programme overview, a press
       release that does not name the specific feature).
     - 0.9 = the source is a specific authoritative page on this
       claim (a named law, a portal feature page, an enacted policy
       text, a dated official statement). Interpolate; do not snap to
       these three values.

   answer_confidence is your confidence that the evidence_quote
   actually supports the specific label you picked.
     - 0.5 = the quote is on-topic but does not directly state the
       answer; you are inferring from related context.
     - 0.7 = the quote states a fact that maps to the answer with
       light interpretation (a year, a percentage, a name) but the
       wording does not exactly mirror the question.
     - 0.9 = the quote states the answer directly in the wording of
       the question or its scoring rule. Interpolate; do not snap to
       these three values.""",
)


# Negative-evidence licence variant (EXP-C `neg_licence` arm).
# V4 plus a controlled exception to Rule 2 that licenses a committed
# `no` on a BINARY question after a documented exhaustive non-discovery:
# the queries explicitly targeted the positive existence of the thing,
# at least one query is in the country's national language for
# non-anglophone countries, and the answer_explanation enumerates the
# targeted queries. The substring gate, the forbidden-source rule, the
# in-prompt 0.5 floor, and every other rule are unchanged. The
# adjudicator's absence-of-evidence rule is NOT relaxed by this arm
# (one-variable discipline); EXP-C measures whether the Researcher
# alone, with the licence, lifts commit accuracy on negative golds.

NEG_LICENCE_NAME = "phase2_researcher_neg_licence"
NEG_LICENCE_VERSION = 1
NEG_LICENCE_DESCRIPTION = (
    "Researcher V4 plus a controlled exception to Rule 2 (EXP-C). On a "
    "BINARY question the model MAY answer `no` instead of "
    "`inconclusive` when the queries explicitly targeted the positive "
    "existence of the thing (at least two such queries, at least one "
    "in the national language for non-anglophone countries), the "
    "search snippets contain no evidence the thing exists, and the "
    "answer_explanation enumerates the targeted queries. The substring "
    "gate (Rule 4) and the forbidden-source rule (Rule 6) still apply. "
    "Tests whether licensing a committed `no` after documented "
    "exhaustive non-discovery lifts commit accuracy on negative golds. "
    "Selected by prompt_variant='neg_licence'."
)

NEG_LICENCE_SYSTEM = SYSTEM.replace(
    """2. Use `inconclusive` (NOT a band label, NOT yes/no) when:
   - the evidence is insufficient, ambiguous, or contradictory
   - the only supporting source is on the forbidden-sources list
   - you cannot find a verbatim quote that grounds the claim
   - your answer_confidence would otherwise be below 0.65
   `inconclusive` is distinct from any literal label in the allowed
   list. It means "we could not determine the answer". Do not collapse
   to `other` for uncertainty; `other` is only valid when it appears
   in the allowed list (some ODMI questions list `other` explicitly).""",
    """2. Use `inconclusive` (NOT a band label, NOT yes/no) when:
   - the evidence is insufficient, ambiguous, or contradictory
   - the only supporting source is on the forbidden-sources list
   - you cannot find a verbatim quote that grounds the claim
   - your answer_confidence would otherwise be below 0.65
   `inconclusive` is distinct from any literal label in the allowed
   list. It means "we could not determine the answer". Do not collapse
   to `other` for uncertainty; `other` is only valid when it appears
   in the allowed list (some ODMI questions list `other` explicitly).

   EXCEPTION: licensed `no` after exhaustive non-discovery (BINARY
   questions only, when `no` is in the allowed list). If the question
   asks whether a specific feature, process, policy instrument, API, or
   metric exists, AND ALL of the following hold, you MAY answer `no`
   instead of `inconclusive`:

   (i)   at least two of your search_queries_used directly targeted the
         positive existence of the thing, in different phrasings (for
         example "does Y portal have feature X", "Y open data portal
         feature X documentation");
   (ii)  for a country whose national language is not English, at least
         one of those queries was in the country's national language;
   (iii) the search snippets in this message contain no passage
         supporting the existence of the thing the question asks about;
   (iv)  your answer_explanation enumerates the positive-existence
         queries you ran and states that none returned supporting
         evidence;
   (v)   you cite an evidence_quote from the most authoritative page on
         the country's national portal or government site that your
         queries surfaced (the substring gate still applies; the quote
         documents the reach of your search, not the negation itself).

   When in doubt return `inconclusive`. A committed `no` that turns
   out to be wrong is worse than an abstention. This licence is for
   BINARY questions whose allowed list contains `no`; ordered-band,
   ordinal, count and categorical questions are unaffected.""",
)


_VARIANTS = {
    "full": PromptVariant(NAME, VERSION, SYSTEM, DESCRIPTION),
    "compressed": PromptVariant(
        COMPRESSED_NAME, COMPRESSED_VERSION, COMPRESSED_SYSTEM,
        COMPRESSED_DESCRIPTION,
    ),
    "calibrated": PromptVariant(
        CALIBRATED_NAME, CALIBRATED_VERSION, CALIBRATED_SYSTEM,
        CALIBRATED_DESCRIPTION,
    ),
    "neg_licence": PromptVariant(
        NEG_LICENCE_NAME, NEG_LICENCE_VERSION, NEG_LICENCE_SYSTEM,
        NEG_LICENCE_DESCRIPTION,
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
