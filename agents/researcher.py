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
from agents.tools import answer_shapes
from agents.tools import db as db_helpers
from agents.tools import substring
from agents.tools.fetch import head_ok
from agents.tools.llm import StructuredOutputError, call_for_structured
from agents.tools.search import SearchResult, search_many
from agents.tools.trusted_domains import trusted_domains_for
from agents.tools.validator import trust_score


# ============================================================
# Query generation prompt (a tiny LLM call before the main one).
# ============================================================


class _Queries(BaseModel):
    queries: List[str] = Field(..., min_length=1, max_length=3)


_QUERY_GEN_NAME = "phase2_researcher_query_gen"
_QUERY_GEN_VERSION = 2
_QUERY_GEN_DESCRIPTION = (
    "Generate 2-3 web search queries for an ODMI question against a "
    "specific country. English query, native-language query if useful. "
    "On retries, diverges from prior queries using verifier feedback."
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

Retry guidance (applies when a previous rejection reason, a suggested
query, or a list of already-tried queries is provided below):
- Generate queries that are DIFFERENT from the ones already tried.
  Do not repeat or paraphrase the prior queries.
- Pursue the rejection reason and any suggested query by targeting
  different sources, phrasings, or angles (e.g. official government
  announcements, academic references, news articles, archived pages).
- If a specific suggested query is given, treat it as a starting point
  but vary the phrasing or add qualifiers so it diverges from any
  already-tried variant.

Return JSON matching the schema."""


# Foreign-language ablation arm (default OFF). The English-only prompt is the
# production prompt with the single native-language bullet swapped for an
# English-only instruction, so the only variable between arms is the query
# language; the retry-divergence guidance and everything else are byte-identical
# by construction. Registered under its own prompt_versions identity so each arm
# is auditable. See docs/EXPERIMENTS_FOREIGN_LANG.md.
_QUERY_GEN_EN_ONLY_NAME = "phase2_researcher_query_gen_en_only"
_QUERY_GEN_EN_ONLY_VERSION = 1
_QUERY_GEN_EN_ONLY_DESCRIPTION = (
    "Foreign-language ablation: English-only query generation (the "
    "native-language query is removed). Default off; the bilingual prompt is "
    "the production default."
)
_QUERY_GEN_SYSTEM_EN_ONLY = _QUERY_GEN_SYSTEM.replace(
    "- One query in English. If the country's national language is not\n"
    "  English, add a second query in the local language.",
    "- All queries in English only. Do not produce queries in the\n"
    "  country's national language, even when it is not English.",
)
# Fail loudly if the anchor above drifts, so the ablation can never silently
# become a no-op that still issues native-language queries.
assert "local language" not in _QUERY_GEN_SYSTEM_EN_ONLY, (
    "en-only query-gen prompt failed to drop the native-language instruction; "
    "the _QUERY_GEN_SYSTEM bullet text changed and the replace anchor is stale"
)


def _query_gen_spec(query_language: str = "bilingual") -> tuple[str, int, str, str]:
    """Select the query-gen prompt for a language mode.

    Returns (prompt_name, version, system_prompt, description). "bilingual" is
    production (one English query plus a native-language query when the country
    is not English-speaking). "en" is the foreign-language ablation: English
    only. Each mode carries its own prompt_versions identity.
    """
    if query_language == "bilingual":
        return (_QUERY_GEN_NAME, _QUERY_GEN_VERSION,
                _QUERY_GEN_SYSTEM, _QUERY_GEN_DESCRIPTION)
    if query_language == "en":
        return (_QUERY_GEN_EN_ONLY_NAME, _QUERY_GEN_EN_ONLY_VERSION,
                _QUERY_GEN_SYSTEM_EN_ONLY, _QUERY_GEN_EN_ONLY_DESCRIPTION)
    raise ValueError(
        f"unknown query_language {query_language!r}; expected 'bilingual' or 'en'"
    )


def _build_query_gen_message(input: ResearcherInput) -> str:
    """Build the user-turn message for the query-generation LLM call.

    On the first attempt (no feedback, no prior queries) the message is
    just the country/question context. On retries the message appends
    the verifier's rejection reason, the suggested query, and the list
    of queries already tried so the model can diverge.
    """
    base = (
        f"Country: {input.country_name} ({input.country_code}, "
        f"language={input.country_language})\n"
        f"Known portal URL: {input.portal_url or '(not provided)'}\n"
        f"\nODMI question:\n{input.question_text}"
    )

    parts: List[str] = [base]

    if input.verifier_feedback is not None:
        fb = input.verifier_feedback
        parts.append(
            f"\nRejection reason from previous attempt:\n{fb.rejection_reason}"
        )
        if fb.suggested_search_query:
            parts.append(
                f"\nSuggested search query (use as a starting point, "
                f"vary the phrasing):\n{fb.suggested_search_query}"
            )
        # EXP-7 chained arm only: the Verifier's counter-evidence, so the
        # next query targets the gap it exposed. Baseline retries leave this
        # None, so the message is unchanged there.
        if fb.counter_evidence_quote:
            parts.append(
                f"\nCounter-evidence the Verifier found (search to confirm "
                f"or refute it):\n{fb.counter_evidence_quote}"
            )

    if input.previous_search_queries:
        listed = "\n".join(f"  - {q}" for q in input.previous_search_queries)
        parts.append(
            f"\nQueries already tried (generate different ones):\n{listed}"
        )

    return "\n".join(parts)


def generate_queries(
    input: ResearcherInput,
    *,
    subtrio_id: str | None = None,
    model: str | None = None,
    query_language: str = "bilingual",
) -> tuple[List[str], LLMUsage]:
    name, version, system, description = _query_gen_spec(query_language)
    prompt_id = db_helpers.ensure_prompt_version(
        name, version, system, description,
    )
    parsed, usage = call_for_structured(
        system=system,
        user_message=_build_query_gen_message(input),
        output_schema=_Queries,
        model=model,
        max_tokens=400,
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
    search_provider_calls: List[dict] = field(default_factory=list)

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


# Stamped on a catalogue-computed Researcher output so the Verifier
# recomputes deterministically instead of searching the web (D30).
CATALOGUE_NOTE_TAG = "catalogue_computed"


def _try_catalogue(
    input: ResearcherInput, on_step: "StepCallback"
) -> Optional["ResearcherRunResult"]:
    """Deterministic catalogue route (D30).

    Returns a finished ResearcherRunResult when the (question, country)
    can be computed from the national catalogue, else None so the caller
    runs the normal web-search path. Imported lazily to keep the
    catalogue dependency off the hot path for web-answered questions.
    """
    from agents.tools.catalogue import compute as catalogue_compute

    if not catalogue_compute.is_computable(input.question_id, input.country_code):
        return None

    on_step("catalogue_start", {
        "question_id": input.question_id,
        "country": input.country_code,
    })
    try:
        comp = catalogue_compute.compute(input.question_id, input.country_code)
    except Exception as exc:  # noqa: BLE001 - fall back to web on any failure
        on_step("catalogue_failed", {"error": str(exc)[:200]})
        return None
    if comp is None:
        on_step("catalogue_failed", {"error": "not computable / empty harvest"})
        return None

    note = CATALOGUE_NOTE_TAG
    if comp.partial:
        note += "; partial_harvest"
    output = ResearcherOutput(
        answer=comp.band,
        answer_explanation=(
            f"Computed deterministically from {input.country_name}'s national "
            f"open data catalogue, independently of the MQA (D30). "
            f"{comp.evidence_quote}"
        ),
        evidence_quote=comp.evidence_quote,
        source_url=comp.source_url,
        retrieval_confidence=1.0,
        answer_confidence=0.95,
        search_queries_used=[],
        fetched_urls=[comp.source_url],
        domain_trust_score=1.0,
        language_route_used="native",
        notes=note,
    )
    on_step("catalogue_complete", {
        "answer": comp.band,
        "breakdown": comp.evidence_quote,
        "source_url": comp.source_url,
        "snapshot_id": comp.snapshot_id,
    })
    return ResearcherRunResult(
        output=output,
        failure_mode=None,
        query_gen_usage=None,
        main_usage=None,
        search_queries_used=[],
        fetched_urls=[comp.source_url],
        domain_trust=1.0,
        notes=note,
    )


SEARCH_STRATEGIES = ("narrow_then_wide", "wide_only", "narrow_only")


def run_researcher(
    input: ResearcherInput,
    *,
    model: str | None = None,
    prompt_variant: str = "full",
    condition_label: str = "baseline",
    max_results_per_query: int = 5,
    provider: str = "auto",
    num_queries: Optional[int] = None,
    use_snippet_picker: bool = True,
    picker_max_chunks: int = 3,
    page_text_cap: int = 16000,
    max_snippet_chars: int = 600,
    query_language: str = "bilingual",
    search_strategy: str = "wide_only",
    picker_model: Optional[str] = None,
    on_step: StepCallback = _noop,
    subtrio_id: str | None = None,
) -> ResearcherRunResult:
    """Run the Researcher once on a single (question, country).

    See `docs/AGENT_DESIGN.md` Section 3 for the contract. Failure
    modes are recorded on the returned object rather than raised; the
    caller writes a row either way so the audit trail is complete.

    `model` selects the Claude model for both the query-gen and the main
    call (EXP-9 model variants); `None` keeps the wrapper default
    (Sonnet). `prompt_variant` selects the system prompt: `"full"` is the
    untouched baseline, `"compressed"` is the leaner EXP-8 prompt
    (examples dropped, instructions terser) registered as its own row in
    `prompt_versions`.

    `on_step(event, payload)` is the walkthrough callback. Set to
    something printing in the runner script when --walkthrough is on.
    """
    if search_strategy not in SEARCH_STRATEGIES:
        raise ValueError(
            f"search_strategy must be one of {SEARCH_STRATEGIES}, got {search_strategy!r}"
        )
    prompt_spec = researcher_prompt.variant(prompt_variant)
    on_step("start", {"question_id": input.question_id, "country": input.country_code})

    # ----- Step 0: deterministic catalogue route (D30) -----
    # Percentage/count Quality questions that ask for a proportion of the
    # national catalogue are computed from harvested metadata, not the web.
    # Near-zero tokens. On any failure we fall through to the web path.
    catalogue_result = _try_catalogue(input, on_step)
    if catalogue_result is not None:
        return catalogue_result

    # ----- Step 1: generate search queries -----
    on_step("query_gen_start", {})
    try:
        queries, query_usage = generate_queries(
            input, subtrio_id=subtrio_id, model=model,
            query_language=query_language,
        )
    except StructuredOutputError as exc:
        on_step("query_gen_failed", {"error": str(exc)})
        return ResearcherRunResult(
            output=None,
            failure_mode="query_gen_schema_invalid",
            query_gen_usage=None,
            main_usage=None,
            notes=str(exc)[:300],
        )
    # Cap the query count when an experiment requests it (a cost knob).
    if num_queries is not None:
        queries = queries[:num_queries]
    on_step("query_gen_complete", {
        "queries": queries,
        "input_tokens": query_usage.input_tokens,
        "output_tokens": query_usage.output_tokens,
        "wall_clock_ms": query_usage.wall_clock_ms,
        "cost_usd": query_usage.estimated_cost_usd,
    })

    # ----- Step 2: search -----
    # Default (`narrow_then_wide`, SRCH-5/6): narrow to the country's
    # trusted domains so authoritative sources rank above generic ones,
    # then widen on an empty first pass. `wide_only` skips the include
    # list entirely (one wide pass, no widen). `narrow_only` keeps the
    # include list but never widens, so EXP-23 can attribute any
    # wide_only gain to the widening step rather than to the absence of
    # narrowing.
    trusted = trusted_domains_for(input.country_code)
    narrow_first = search_strategy in ("narrow_then_wide", "narrow_only")
    on_step("search_start", {"queries": queries, "trusted_domains": trusted})
    provider_calls: List[dict] = []
    first_pass_include = trusted if (narrow_first and trusted) else None
    search_results = search_many(
        queries,
        max_results_per_query=max_results_per_query,
        include_domains=first_pass_include,
        on_call=provider_calls.append,
        provider=provider,
        use_snippet_picker=use_snippet_picker,
        picker_max_chunks=picker_max_chunks,
        page_text_cap=page_text_cap,
        picker_model=picker_model,
        subtrio_id=subtrio_id,
    )
    wide_fallback_used = False
    if (
        not search_results
        and trusted
        and search_strategy == "narrow_then_wide"
    ):
        on_step("search_widen", {"reason": "narrow search returned nothing"})
        search_results = search_many(
            queries,
            max_results_per_query=max_results_per_query,
            on_call=provider_calls.append,
            provider=provider,
            use_snippet_picker=use_snippet_picker,
            picker_max_chunks=picker_max_chunks,
            page_text_cap=page_text_cap,
            picker_model=picker_model,
            subtrio_id=subtrio_id,
        )
        wide_fallback_used = True
    on_step("search_complete", {
        "n_results": len(search_results),
        "top_titles": [r.title[:80] for r in search_results[:5]],
        "wide_fallback_used": wide_fallback_used,
    })

    if not search_results:
        return ResearcherRunResult(
            output=None,
            failure_mode="search_empty",
            query_gen_usage=query_usage,
            main_usage=None,
            search_queries_used=queries,
            search_provider_calls=provider_calls,
            notes="No results across all queries (narrow and wide).",
        )

    # ----- Step 3: register prompt version and call the LLM -----
    # The variant chooses the system prompt and its prompt_versions row.
    # The baseline ("full") keeps NAME/VERSION/SYSTEM unchanged; the
    # compressed arm carries its own NAME/VERSION so the receipts trace to
    # the exact prompt that ran (EXP-8).
    prompt_id = db_helpers.ensure_prompt_version(
        prompt_spec.name,
        prompt_spec.version,
        prompt_spec.system,
        prompt_spec.description,
    )
    user_message = researcher_prompt.build_user_message(
        input,
        search_results=search_results,
        queries_used=queries,
        max_chars_per_snippet=max_snippet_chars,
    )
    on_step("main_call_start", {
        "prompt_version_id": prompt_id,
        "prompt_variant": prompt_variant,
        "user_message_chars": len(user_message),
    })

    try:
        output, main_usage = call_for_structured(
            system=prompt_spec.system,
            user_message=user_message,
            output_schema=ResearcherOutput,
            model=model,
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
            search_provider_calls=provider_calls,
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
    # `inconclusive` is the per-D28 honest "couldn't tell" label; a low
    # answer_confidence on any other label is suspicious and the
    # Verifier should know.
    if (
        output.answer_confidence < 0.5
        and output.answer != "inconclusive"
    ):
        notes_parts.append(
            f"low answer_confidence ({output.answer_confidence}) for "
            f"non-inconclusive answer {output.answer!r}"
        )

    # D28: validate emitted answer against the per-question allowed
    # set + inconclusive / not_applicable. If the model emitted
    # something off-script (e.g. paraphrased a band label), normalise
    # case-insensitively; if even that fails, mark the run as
    # invalid_answer_shape so the Coordinator can retry.
    shape = answer_shapes.QuestionShape(
        question_id=input.question_id,
        shape=input.answer_shape,
        allowed_answers=tuple(input.allowed_answers),
    )
    normalised = answer_shapes.normalise_answer(output.answer, shape)
    if normalised != output.answer:
        notes_parts.append(
            f"answer normalised from {output.answer!r} to {normalised!r}"
        )
        output = output.model_copy(update={"answer": normalised})
    if not answer_shapes.is_valid_answer(output.answer, shape):
        failure_mode = failure_mode or "invalid_answer_shape"
        notes_parts.append(
            f"answer {output.answer!r} not in allowed set "
            f"{list(shape.all_valid)[:8]}..."
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
        search_provider_calls=provider_calls,
        head_ok=head_status_ok,
        head_status=head_status,
        domain_trust=domain,
        notes="; ".join(notes_parts) if notes_parts else None,
    )
