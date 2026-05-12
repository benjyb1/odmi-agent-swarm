"""The Researcher agent.

Given an ODMI (question, country), search the web, choose the best
evidence, and return a structured candidate answer with a cited source
URL and a literal quote. The Researcher hands off to the Verifier;
it is not the final word.

Two LLM calls per run by design:
1. A small call to generate 2-3 search queries from the question text.
2. The main call to answer based on the snippets.

This is the Python-orchestrated version of the Researcher (no native
Claude tool use). See `docs/AGENT_DESIGN.md` Section 3 for the full
atomic specification.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from agents.models import LLMUsage, ResearcherInput, ResearcherOutput
from agents.prompts import researcher as researcher_prompt
from agents.tools import db as db_helpers
from agents.tools import substring
from agents.tools.fetch import head_ok
from agents.tools.llm import StructuredOutputError, call_for_structured
from agents.tools.search import SearchResult, search_many
from agents.tools.validator import trust_score


# ============================================================
# Query generation prompt (a tiny LLM call before the main one).
# ============================================================


class _Queries(BaseModel):
    queries: List[str] = Field(..., min_length=1, max_length=3)


_QUERY_GEN_NAME = "phase2_researcher_query_gen"
_QUERY_GEN_VERSION = 1
_QUERY_GEN_DESCRIPTION = (
    "Generate 2-3 web search queries for an ODMI question against a "
    "specific country. English query, native-language query if useful."
)

_QUERY_GEN_SYSTEM = """You are a search query generator for an ODMI evaluation pipeline.
Given an ODMI question and a target country, produce 2 or 3 short web
search queries that are likely to surface authoritative evidence.

Guidance:
- Prefer 5-10 word queries, not full-sentence questions.
- One query in English. If the country's national language is not
  English, add a second query in the local language.
- A third query may target the country's national portal (e.g. by
  including a site filter or the portal's name) when relevant.
- Do not invent organisations. Use the country's actual government
  bodies and known portal names.

Return JSON matching the schema."""


def _build_query_gen_message(input: ResearcherInput) -> str:
    return (
        f"Country: {input.country_name} ({input.country_code}, "
        f"language={input.country_language})\n"
        f"Known portal URL: {input.portal_url or '(not provided)'}\n"
        f"\nODMI question:\n{input.question_text}"
    )


def generate_queries(
    input: ResearcherInput,
    *,
    subtrio_id: str | None = None,
) -> tuple[List[str], LLMUsage]:
    prompt_id = db_helpers.ensure_prompt_version(
        _QUERY_GEN_NAME, _QUERY_GEN_VERSION,
        _QUERY_GEN_SYSTEM, _QUERY_GEN_DESCRIPTION,
    )
    parsed, usage = call_for_structured(
        system=_QUERY_GEN_SYSTEM,
        user_message=_build_query_gen_message(input),
        output_schema=_Queries,
        max_tokens=200,
        condition_label="query_gen",
        prompt_version_id=prompt_id,
        usage_context=f"researcher_query_gen:{input.question_id}:{input.country_code}",
        subtrio_id=subtrio_id,
    )
    return parsed.queries, usage


# ============================================================
# Researcher run result
# ============================================================


@dataclass
class ResearcherRunResult:
    """Everything one Researcher run produced.

    The runner script unpacks this into a phase2_researcher_runs row.
    Keeping the dataclass non-Pydantic so it can hold the full
    LLMUsage objects without flattening them prematurely.
    """

    # Outputs (None if the run failed before LLM call)
    output: Optional[ResearcherOutput]

    # Failure mode (None on success). Recorded in the DB.
    failure_mode: Optional[str]

    # Cost receipts: usage from the query-gen call and the main call.
    # Cumulative figures are computed on demand.
    query_gen_usage: Optional[LLMUsage]
    main_usage: Optional[LLMUsage]

    # The actual search runtime data, for the DB row.
    search_queries_used: List[str] = field(default_factory=list)
    fetched_urls: List[str] = field(default_factory=list)
    search_results: List[SearchResult] = field(default_factory=list)

    # The post-call validation outcomes, for diagnostics.
    head_ok: Optional[bool] = None
    head_status: Optional[int] = None
    domain_trust: Optional[float] = None

    notes: Optional[str] = None

    @property
    def cumulative_input_tokens(self) -> int:
        return sum(
            u.input_tokens for u in (self.query_gen_usage, self.main_usage) if u
        )

    @property
    def cumulative_output_tokens(self) -> int:
        return sum(
            u.output_tokens for u in (self.query_gen_usage, self.main_usage) if u
        )

    @property
    def cumulative_wall_clock_ms(self) -> int:
        return sum(
            u.wall_clock_ms for u in (self.query_gen_usage, self.main_usage) if u
        )

    @property
    def cumulative_cost_usd(self) -> Optional[float]:
        parts = [
            u.estimated_cost_usd
            for u in (self.query_gen_usage, self.main_usage)
            if u and u.estimated_cost_usd is not None
        ]
        return sum(parts) if parts else None


# ============================================================
# Researcher entry point
# ============================================================


StepCallback = Callable[[str, dict], None]


def _noop(event: str, payload: dict) -> None:  # pragma: no cover
    return


def run_researcher(
    input: ResearcherInput,
    *,
    condition_label: str = "baseline",
    max_results_per_query: int = 5,
    on_step: StepCallback = _noop,
    subtrio_id: str | None = None,
) -> ResearcherRunResult:
    """Run the Researcher once on a single (question, country).

    See `docs/AGENT_DESIGN.md` Section 3 for the contract. Failure
    modes are recorded on the returned object rather than raised; the
    caller writes a row either way so the audit trail is complete.

    `on_step(event, payload)` is the walkthrough callback. Set to
    something printing in the runner script when --walkthrough is on.
    """
    on_step("start", {"question_id": input.question_id, "country": input.country_code})

    # ----- Step 1: generate search queries -----
    on_step("query_gen_start", {})
    try:
        queries, query_usage = generate_queries(input, subtrio_id=subtrio_id)
    except StructuredOutputError as exc:
        on_step("query_gen_failed", {"error": str(exc)})
        return ResearcherRunResult(
            output=None,
            failure_mode="query_gen_schema_invalid",
            query_gen_usage=None,
            main_usage=None,
            notes=str(exc)[:300],
        )
    on_step("query_gen_complete", {
        "queries": queries,
        "input_tokens": query_usage.input_tokens,
        "output_tokens": query_usage.output_tokens,
        "wall_clock_ms": query_usage.wall_clock_ms,
        "cost_usd": query_usage.estimated_cost_usd,
    })

    # ----- Step 2: search -----
    on_step("search_start", {"queries": queries})
    search_results = search_many(queries, max_results_per_query=max_results_per_query)
    on_step("search_complete", {
        "n_results": len(search_results),
        "top_titles": [r.title[:80] for r in search_results[:5]],
    })

    if not search_results:
        return ResearcherRunResult(
            output=None,
            failure_mode="search_empty",
            query_gen_usage=query_usage,
            main_usage=None,
            search_queries_used=queries,
            notes="No Tavily results across all queries.",
        )

    # ----- Step 3: register prompt version and call the LLM -----
    prompt_id = db_helpers.ensure_prompt_version(
        researcher_prompt.NAME,
        researcher_prompt.VERSION,
        researcher_prompt.SYSTEM,
        researcher_prompt.DESCRIPTION,
    )
    user_message = researcher_prompt.build_user_message(
        input,
        search_results=search_results,
        queries_used=queries,
    )
    on_step("main_call_start", {
        "prompt_version_id": prompt_id,
        "user_message_chars": len(user_message),
    })

    try:
        output, main_usage = call_for_structured(
            system=researcher_prompt.SYSTEM,
            user_message=user_message,
            output_schema=ResearcherOutput,
            max_tokens=2000,
            condition_label=condition_label,
            prompt_version_id=prompt_id,
            usage_context=f"researcher:{input.question_id}:{input.country_code}",
            subtrio_id=subtrio_id,
        )
    except StructuredOutputError as exc:
        on_step("main_call_failed", {"error": str(exc)})
        return ResearcherRunResult(
            output=None,
            failure_mode="schema_invalid",
            query_gen_usage=query_usage,
            main_usage=None,
            search_queries_used=queries,
            search_results=search_results,
            notes=str(exc)[:300],
        )

    on_step("main_call_complete", {
        "answer": output.answer,
        "answer_confidence": output.answer_confidence,
        "retrieval_confidence": output.retrieval_confidence,
        "source_url": str(output.source_url),
        "input_tokens": main_usage.input_tokens,
        "output_tokens": main_usage.output_tokens,
        "wall_clock_ms": main_usage.wall_clock_ms,
        "cost_usd": main_usage.estimated_cost_usd,
    })

    # ----- Step 4: post-call validation -----
    on_step("validation_start", {})
    head_status_ok, head_status = head_ok(str(output.source_url))
    domain = trust_score(str(output.source_url), country_code=input.country_code)
    failure_mode: Optional[str] = None
    notes_parts: List[str] = []

    if not head_status_ok:
        failure_mode = "url_unreachable"
        notes_parts.append(f"HEAD/GET returned status {head_status}")

    # Substring verification of the quote against fetched URLs is the
    # Verifier's job. The Researcher accepts the model's quote here and
    # the Verifier catches fabrications. This is the V1 trade-off
    # called out in AGENT_DESIGN.md.

    # Confidence-quality check from Section 3.5 success criteria.
    if (
        output.answer_confidence < 0.5
        and output.answer != "other"
    ):
        # Not a fatal failure, but flag so the Verifier knows.
        notes_parts.append(
            f"low answer_confidence ({output.answer_confidence}) for non-other answer"
        )

    # Was the cited source_url in our search results? Catches the
    # rare case where the model invents a URL.
    cited = str(output.source_url).rstrip("/")
    in_results = any(str(r.url).rstrip("/") == cited for r in search_results)
    if not in_results:
        notes_parts.append("source_url not among search snippets")

    on_step("validation_complete", {
        "head_ok": head_status_ok,
        "head_status": head_status,
        "domain_trust": domain,
        "failure_mode": failure_mode,
        "notes": notes_parts,
    })

    # We always return the output; failure_mode just annotates the row.
    # Override the model's domain_trust_score with the validator's value
    # since the model only sees what it found.
    output_with_trust = output.model_copy(update={"domain_trust_score": domain})

    return ResearcherRunResult(
        output=output_with_trust,
        failure_mode=failure_mode,
        query_gen_usage=query_usage,
        main_usage=main_usage,
        search_queries_used=queries,
        fetched_urls=[str(r.url) for r in search_results],
        search_results=search_results,
        head_ok=head_status_ok,
        head_status=head_status,
        domain_trust=domain,
        notes="; ".join(notes_parts) if notes_parts else None,
    )
