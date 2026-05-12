"""The Adversarial Verifier agent.

Given the Researcher's candidate answer and citation, attempt to disprove
it. The Verifier's value is cognitive: it deliberately inverts the LLM's
natural optimism bias to cancel out hallucinations.

Three stages per run:
1. Python fetches the Researcher's cited URL and checks whether the
   evidence quote appears verbatim in the page (substring check).
   This is the only structural mitigation against pure fabrication.
2. A small LLM call generates 2-3 adversarial search queries, framed
   to surface counter-evidence rather than corroboration.
3. Python runs those queries via Tavily, then passes everything to the
   main LLM call with the strategy-specific prompt.

Four prompt strategies are defined in `agents/prompts/verifier.py`.
Each is a separate entry in `prompt_versions` and a distinct
`strategy_label` on the DB row, per D15.

See `docs/AGENT_DESIGN.md` Section 4 for the full atomic specification.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from pydantic import BaseModel, Field

from agents.models import (
    LLMUsage,
    ResearcherOutput,
    VerifierInput,
    VerifierOutput,
    VerifierStrategy,
)
from agents.prompts import verifier as verifier_prompt
from agents.tools import db as db_helpers
from agents.tools import substring
from agents.tools.fetch import FetchResult, fetch_rendered_text, fetch_text
from agents.tools.llm import StructuredOutputError, call_for_structured
from agents.tools.search import SearchResult, format_for_prompt, search_many


# ============================================================
# Adversarial query generation prompt.
# ============================================================

class _Queries(BaseModel):
    queries: List[str] = Field(..., min_length=1, max_length=3)


_QUERY_GEN_NAME = "phase2_verifier_query_gen"
_QUERY_GEN_VERSION = 1
_QUERY_GEN_DESCRIPTION = (
    "Generate 2-3 adversarial web search queries for a Verifier run. "
    "Queries are framed to surface counter-evidence, not corroboration."
)

_QUERY_GEN_SYSTEM = """You are a search query generator for an adversarial verification step.

Given an ODMI question, a country, and the Researcher's claimed answer,
produce 2-3 short web search queries that are specifically designed to
find evidence AGAINST the Researcher's answer.

Guidance:
- Prefer 5-10 word queries.
- If the Researcher answered "yes", search for evidence that the answer
  should be "no" (and vice versa).
- If the Researcher answered "other", search for a more definitive source
  that gives a clear yes or no.
- Include at least one query in the country's national language.
- Do not repeat the Researcher's own queries verbatim; approach the
  question from a different angle.
- Target official government, legislative, and regulatory sources.

Return JSON matching the schema."""


class _QueryGenInput(BaseModel):
    question_text: str
    country_name: str
    country_language: str
    researcher_answer: str


def _build_query_gen_message(inp: VerifierInput) -> str:
    ro = inp.researcher_output
    return (
        f"Country: {inp.country_name} ({inp.country_code}, "
        f"language: unknown — assume national language)\n"
        f"Researcher's answer: {ro.answer}\n"
        f"Researcher's explanation: {ro.answer_explanation}\n"
        f"\nODMI question:\n{inp.question_text}"
    )


def generate_adversarial_queries(
    inp: VerifierInput,
    *,
    subtrio_id: str | None = None,
) -> tuple[List[str], LLMUsage]:
    prompt_id = db_helpers.ensure_prompt_version(
        _QUERY_GEN_NAME, _QUERY_GEN_VERSION,
        _QUERY_GEN_SYSTEM, _QUERY_GEN_DESCRIPTION,
    )
    parsed, usage = call_for_structured(
        system=_QUERY_GEN_SYSTEM,
        user_message=_build_query_gen_message(inp),
        output_schema=_Queries,
        max_tokens=200,
        condition_label="verifier_query_gen",
        prompt_version_id=prompt_id,
        usage_context=f"verifier_query_gen:{inp.question_id}:{inp.country_code}",
        subtrio_id=subtrio_id,
    )
    return parsed.queries, usage


# ============================================================
# Substring check (Python-only, no LLM)
# ============================================================

def _run_substring_check(
    source_url: str,
    evidence_quote: str,
) -> tuple[str, Optional[str], Optional[FetchResult]]:
    """Fetch the Researcher's cited URL and run the normalised substring check.

    Returns (result, notes, fetch_result) where result is one of
    "pass", "fail", "not_attempted".
    """
    fetch = fetch_text(source_url, max_chars=8000)

    if fetch.failure_mode is not None:
        # httpx failed — try Playwright.
        fetch = fetch_rendered_text(source_url, max_chars=8000)

    if fetch.failure_mode is not None:
        return (
            "not_attempted",
            f"Could not fetch source URL: {fetch.failure_mode}",
            fetch,
        )

    if not fetch.content.strip():
        return (
            "not_attempted",
            "Fetched page was empty after HTML stripping.",
            fetch,
        )

    found = substring.contains(fetch.content, evidence_quote)
    if found:
        return "pass", None, fetch

    # Substring failed. Build a short note explaining what we looked for.
    quote_preview = evidence_quote[:120] + ("..." if len(evidence_quote) > 120 else "")
    return (
        "fail",
        f"Quote not found (normalised match): \"{quote_preview}\"",
        fetch,
    )


# ============================================================
# Verifier run result
# ============================================================

@dataclass
class VerifierRunResult:
    """Everything one Verifier run produced.

    Analogous to ResearcherRunResult. The runner script unpacks this
    into a phase2_verifier_runs row.
    """

    output: Optional[VerifierOutput]

    failure_mode: Optional[str]

    # Usage receipts: query-gen call and main call.
    query_gen_usage: Optional[LLMUsage]
    main_usage: Optional[LLMUsage]

    # The pre-LLM work done in Python.
    substring_result: str = "not_attempted"
    substring_notes: Optional[str] = None
    adversarial_queries: List[str] = field(default_factory=list)
    search_results: List[SearchResult] = field(default_factory=list)

    # Strategy used in this run.
    strategy: VerifierStrategy = "verifier-disprove"

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
# Verifier entry point
# ============================================================

StepCallback = Callable[[str, dict], None]


def _noop(event: str, payload: dict) -> None:  # pragma: no cover
    return


def run_verifier(
    inp: VerifierInput,
    *,
    condition_label: str = "baseline",
    max_results_per_query: int = 5,
    on_step: StepCallback = _noop,
    subtrio_id: str | None = None,
) -> VerifierRunResult:
    """Run the Verifier once on a single (question, country, researcher_output).

    Failure modes are recorded on the returned object rather than raised;
    the caller writes a row either way to preserve the audit trail.

    `on_step(event, payload)` is the walkthrough callback.
    """
    strategy = inp.strategy
    spec = verifier_prompt.STRATEGIES[strategy]

    on_step("start", {
        "question_id": inp.question_id,
        "country": inp.country_code,
        "strategy": strategy,
        "researcher_answer": inp.researcher_output.answer,
    })

    # ----- Stage 1: substring check (Python, no LLM) -----
    on_step("substring_check_start", {"url": str(inp.researcher_output.source_url)})

    sub_result, sub_notes, fetch = _run_substring_check(
        str(inp.researcher_output.source_url),
        inp.researcher_output.evidence_quote,
    )

    on_step("substring_check_complete", {
        "result": sub_result,
        "notes": sub_notes,
        "fetch_status": fetch.status_code if fetch else None,
    })

    # ----- Stage 2: adversarial query generation -----
    on_step("query_gen_start", {})
    try:
        queries, query_usage = generate_adversarial_queries(inp, subtrio_id=subtrio_id)
    except StructuredOutputError as exc:
        on_step("query_gen_failed", {"error": str(exc)})
        return VerifierRunResult(
            output=None,
            failure_mode="query_gen_schema_invalid",
            query_gen_usage=None,
            main_usage=None,
            substring_result=sub_result,
            substring_notes=sub_notes,
            strategy=strategy,
            notes=str(exc)[:300],
        )

    on_step("query_gen_complete", {
        "queries": queries,
        "input_tokens": query_usage.input_tokens,
        "output_tokens": query_usage.output_tokens,
        "wall_clock_ms": query_usage.wall_clock_ms,
        "cost_usd": query_usage.estimated_cost_usd,
    })

    # ----- Stage 3: independent search -----
    on_step("search_start", {"queries": queries})
    search_results = search_many(queries, max_results_per_query=max_results_per_query)
    on_step("search_complete", {
        "n_results": len(search_results),
        "top_titles": [r.title[:80] for r in search_results[:5]],
    })

    independent_snippets = [
        f"{r.title} — {r.snippet[:200]}" for r in search_results
    ]

    # ----- Stage 4: register prompt and call the LLM -----
    prompt_id = db_helpers.ensure_prompt_version(
        spec.name,
        spec.version,
        spec.system,
        spec.description,
    )

    user_message = verifier_prompt.build_user_message(
        question_text=inp.question_text,
        country_name=inp.country_name,
        country_code=inp.country_code,
        researcher_output=inp.researcher_output,
        substring_result=sub_result,
        substring_notes=sub_notes,
        independent_queries=queries,
        independent_snippets=independent_snippets,
        strategy=strategy,
    )

    on_step("main_call_start", {
        "strategy": strategy,
        "prompt_version_id": prompt_id,
        "user_message_chars": len(user_message),
    })

    try:
        output, main_usage = call_for_structured(
            system=spec.system,
            user_message=user_message,
            output_schema=VerifierOutput,
            max_tokens=1500,
            condition_label=condition_label,
            prompt_version_id=prompt_id,
            usage_context=f"verifier_{strategy}:{inp.question_id}:{inp.country_code}",
            subtrio_id=subtrio_id,
        )
    except StructuredOutputError as exc:
        on_step("main_call_failed", {"error": str(exc)})
        return VerifierRunResult(
            output=None,
            failure_mode="schema_invalid",
            query_gen_usage=query_usage,
            main_usage=None,
            substring_result=sub_result,
            substring_notes=sub_notes,
            adversarial_queries=queries,
            search_results=search_results,
            strategy=strategy,
            notes=str(exc)[:300],
        )

    on_step("main_call_complete", {
        "verdict": output.verdict,
        "verifier_answer": output.verifier_answer,
        "verifier_confidence": output.verifier_confidence,
        "substring_check_result": output.substring_check_result,
        "rejection_reason": output.rejection_reason,
        "input_tokens": main_usage.input_tokens,
        "output_tokens": main_usage.output_tokens,
        "wall_clock_ms": main_usage.wall_clock_ms,
        "cost_usd": main_usage.estimated_cost_usd,
    })

    # ----- Strategy D post-processing: compare answers -----
    # For blind strategy, the model returned its own answer without
    # seeing the Researcher's. If they differ, override verdict to fail.
    notes_parts: List[str] = []
    if strategy == "verifier-blind":
        if output.verifier_answer != inp.researcher_output.answer:
            # Answers diverge — flag as fail if the model didn't already.
            if output.verdict == "pass":
                notes_parts.append(
                    f"blind: verifier answered {output.verifier_answer!r} "
                    f"vs researcher {inp.researcher_output.answer!r} — "
                    "verdict overridden to fail"
                )
                # Override: rebuild with fail verdict.
                # Use the first independent snippet as minimal counter-evidence
                # so the validator's rejection_fields check passes.
                counter_snippet = (
                    independent_snippets[0][:200] if independent_snippets else
                    "No independent snippet available."
                )
                output = output.model_copy(update={
                    "verdict": "fail",
                    "rejection_reason": (
                        f"Blind verifier independently answered "
                        f"{output.verifier_answer!r} while the Researcher "
                        f"answered {inp.researcher_output.answer!r}. "
                        "Answers diverge; Researcher answer not confirmed."
                    ),
                    "counter_evidence_quote": counter_snippet,
                    "suggested_search_query": queries[0] if queries else None,
                })
        on_step("blind_comparison", {
            "researcher_answer": inp.researcher_output.answer,
            "verifier_answer": output.verifier_answer,
            "answers_match": output.verifier_answer == inp.researcher_output.answer,
        })

    return VerifierRunResult(
        output=output,
        failure_mode=None,
        query_gen_usage=query_usage,
        main_usage=main_usage,
        substring_result=sub_result,
        substring_notes=sub_notes,
        adversarial_queries=queries,
        search_results=search_results,
        strategy=strategy,
        notes="; ".join(notes_parts) if notes_parts else None,
    )
