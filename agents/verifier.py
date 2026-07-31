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

from dataclasses import dataclass, field
from typing import Callable, List, Literal, Optional

from pydantic import BaseModel, Field

from agents.models import (
    LLMUsage,
    ResearcherOutput,
    VerifierInput,
    VerifierOutput,
    VerifierStrategy,
)
from agents.prompts import verifier as verifier_prompt
from agents.tools import answer_shapes
from agents.tools import db as db_helpers
from agents.tools import substring
from agents.tools.blocked_domains import is_blocked
from agents.tools.fetch import FetchResult, fetch_rendered_text, fetch_text
from agents.tools.llm import StructuredOutputError, call_for_structured
from agents.tools.search import SearchResult, search_many


# EXP-14: Verifier web counter-search policy.
# The Verifier's own live web counter-search (the adversarial query-gen
# plus search_many call) poisons its evidence: production discrimination
# was Youden's J=0.10 with the search on against J=0.42 with it off. This
# knob lets an experiment turn that independent search off without touching
# the verdict, substring gate, or the counter-evidence-from-Researcher-
# snippets logic.
#
#   "always"   — DEFAULT, current production behaviour, byte-identical.
#                Generate adversarial queries, run them live, feed the
#                snippets to the verdict call.
#   "never"    — skip the independent query-gen and search entirely. The
#                Verifier reasons only over the evidence the Researcher
#                already gathered (its snippets remain in the substring
#                gate and are surfaced to the verdict call).
#   "elective" — let the Verifier decide whether to counter-search after
#                reading the Researcher's evidence. NOT IMPLEMENTED yet;
#                wired to the flag but raises NotImplementedError.
#
# When the policy is anything other than "always" a one-line note is added
# to the per-call USER message (never the system prompt), so prompt_versions
# is byte-identical across arms. This mirrors the EXP-7 `--chained`
# `_evidence_corpus_block` pattern in agents/prompts/adjudicator.py.

VerifierSearchPolicy = Literal["always", "never", "elective"]


# Adversarial query generation prompt.

class _Queries(BaseModel):
    queries: List[str] = Field(..., min_length=1, max_length=3)


class _Probes(BaseModel):
    # The probe generator asks for 3-4 angles (portal, API, policy
    # register, national-language), so it needs a wider cap than the
    # adversarial _Queries (max 3) or a 4-query response fails validation.
    queries: List[str] = Field(..., min_length=1, max_length=4)


_QUERY_GEN_NAME = "phase2_verifier_query_gen"
_QUERY_GEN_VERSION = 2
_QUERY_GEN_DESCRIPTION = (
    "Generate 2-3 adversarial web search queries for a Verifier run. "
    "Queries are framed to surface counter-evidence, not corroboration. "
    "V2 makes the inversion shape-aware: for ordered-band questions, "
    "queries target a different band; for categoricals, a different "
    "category; for binary, the opposite label."
)

_QUERY_GEN_SYSTEM = """You are a search query generator for an adversarial verification step.

Given an ODMI question, a country, and the Researcher's claimed answer,
produce 2-3 short web search queries that are specifically designed to
find evidence AGAINST the Researcher's answer.

Guidance:
- Prefer 5-10 word queries.
- Adversarial direction depends on the question's answer shape:
  * binary: search for the opposite label (yes -> no, no -> yes).
  * percentage_band / ordinal_magnitude / count_band: search for
    evidence the right band is one step off, or for a precise
    underlying figure that contradicts the Researcher's bucket.
  * categorical: search for evidence a different named category is
    the right one.
  If the Researcher answered 'inconclusive', search for a more
  definitive source that yields a confident label.
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
    allowed_block = ", ".join(repr(a) for a in inp.allowed_answers)
    return (
        f"Country: {inp.country_name} ({inp.country_code}, "
        f"language: unknown - assume national language)\n"
        f"Researcher's answer: {ro.answer}\n"
        f"Researcher's explanation: {ro.answer_explanation}\n"
        f"\nAnswer shape: {inp.answer_shape}\n"
        f"Allowed labels: [{allowed_block}]\n"
        f"\nODMI question:\n{inp.question_text}"
    )


def generate_adversarial_queries(
    inp: VerifierInput,
    *,
    subtrio_id: str | None = None,
    model: str | None = None,
) -> tuple[List[str], LLMUsage]:
    prompt_id = db_helpers.ensure_prompt_version(
        _QUERY_GEN_NAME, _QUERY_GEN_VERSION,
        _QUERY_GEN_SYSTEM, _QUERY_GEN_DESCRIPTION,
    )
    parsed, usage = call_for_structured(
        system=_QUERY_GEN_SYSTEM,
        user_message=_build_query_gen_message(inp),
        output_schema=_Queries,
        model=model,
        max_tokens=200,
        condition_label="verifier_query_gen",
        prompt_version_id=prompt_id,
        usage_context=f"verifier_query_gen:{inp.question_id}:{inp.country_code}",
        subtrio_id=subtrio_id,
    )
    return parsed.queries, usage


# Corroborative query generation (EXP-42).
#
# The mirror of the adversarial generator above: same shape-awareness,
# opposite direction. Until EXP-42 the cooperative arm shared the
# adversarial generator, so the corroborating verifier was handed
# counter-evidence and asked to corroborate from it while its own step 4
# told it to look for support. That measures neither stance. A verifier
# that searches one way and judges the other measures nothing, so the
# search direction and the verdict burden move together.
#
# EXP-38's search-free replay isolates the verdict rule on its own, so
# the decomposition sits across the two experiments rather than inside
# this one. See docs/EXPERIMENTS_EXP42_STANCE_HELDOUT.md.

_CORROBORATIVE_QUERY_GEN_NAME = "phase2_verifier_corroborative_query_gen"
_CORROBORATIVE_QUERY_GEN_VERSION = 1
_CORROBORATIVE_QUERY_GEN_DESCRIPTION = (
    "Generate 2-3 corroborative web search queries for a Verifier run. "
    "Queries are framed to surface independent support for the "
    "Researcher's answer, not counter-evidence. Shape-aware in the same "
    "way as the adversarial generator: for ordered-band questions, "
    "queries target a figure inside the claimed band; for categoricals, "
    "the claimed category; for binary, the claimed label."
)

_CORROBORATIVE_QUERY_GEN_SYSTEM = """You are a search query generator for a corroborative verification step.

Given an ODMI question, a country, and the Researcher's claimed answer,
produce 2-3 short web search queries that are specifically designed to
find independent evidence that SUPPORTS the Researcher's answer.

Guidance:
- Prefer 5-10 word queries.
- Corroborative direction depends on the question's answer shape:
  * binary: search for the label the Researcher gave. Where the answer is
    'no', search for an authoritative statement that the thing is absent
    or excluded, rather than for the thing itself.
  * percentage_band / ordinal_magnitude / count_band: search for a
    precise underlying figure that falls inside the Researcher's band.
  * categorical: search for evidence naming the category the Researcher
    chose.
  If the Researcher answered 'inconclusive', search for a source
  definitive enough to settle the question either way.
- Include at least one query in the country's national language.
- Do not repeat the Researcher's own queries verbatim; approach the
  question from a different angle, so any support you find is
  independent of the source the Researcher already cited.
- Target official government, legislative, and regulatory sources.

Return JSON matching the schema."""


def generate_corroborative_queries(
    inp: VerifierInput,
    *,
    subtrio_id: str | None = None,
    model: str | None = None,
) -> tuple[List[str], LLMUsage]:
    """Generate support-seeking queries for the corroborative stance."""
    prompt_id = db_helpers.ensure_prompt_version(
        _CORROBORATIVE_QUERY_GEN_NAME, _CORROBORATIVE_QUERY_GEN_VERSION,
        _CORROBORATIVE_QUERY_GEN_SYSTEM, _CORROBORATIVE_QUERY_GEN_DESCRIPTION,
    )
    parsed, usage = call_for_structured(
        system=_CORROBORATIVE_QUERY_GEN_SYSTEM,
        user_message=_build_query_gen_message(inp),
        output_schema=_Queries,
        model=model,
        max_tokens=200,
        condition_label="verifier_corroborative_query_gen",
        prompt_version_id=prompt_id,
        usage_context=(
            f"verifier_corroborative_query_gen:{inp.question_id}:{inp.country_code}"
        ),
        subtrio_id=subtrio_id,
    )
    return parsed.queries, usage


# Confirmation-probe query generation (EXP-11 P2, query-gen v3).
# For an absence claim, generate queries that hunt for the POSITIVE
# thing the answer says is missing, so the verifier can try to refute
# the absence before corroborating it. Additive: used by the EXP-11
# harness, not by production run_verifier.

_PROBE_GEN_NAME = "phase2_verifier_probe_gen"
_PROBE_GEN_VERSION = 1
_PROBE_GEN_DESCRIPTION = (
    "Generate 3-4 confirmation-probe web search queries for an absence "
    "claim. Queries hunt for the positive thing the Researcher says is "
    "absent (a portal feature, an API, a policy instrument), so the "
    "verifier can test the absence rather than accept it on silence."
)

_PROBE_GEN_SYSTEM = """You generate confirmation probes for an absence claim.

The Researcher has answered that some feature, API, dataset, or policy
instrument does NOT exist for this country. Produce 3-4 short web search
queries (5-10 words) that would FIND that thing if it existed. The point
is to give the absence its best chance to be proven wrong.

Cover different angles:
- the national open-data portal's own feature or documentation page,
- an API or developer/documentation page,
- the official policy register, legal gazette, or government strategy,
- at least one query in the country's national language.

Target official government, legislative, and regulatory sources. Do not
search for the absence ("no API Malta"); search for the presence ("Malta
open data portal API documentation"). Return JSON matching the schema."""


def generate_confirmation_probes(
    inp: VerifierInput,
    *,
    subtrio_id: str | None = None,
    model: str | None = None,
) -> tuple[List[str], LLMUsage]:
    """Generate confirmation-probe queries for an absence claim."""
    prompt_id = db_helpers.ensure_prompt_version(
        _PROBE_GEN_NAME, _PROBE_GEN_VERSION,
        _PROBE_GEN_SYSTEM, _PROBE_GEN_DESCRIPTION,
    )
    parsed, usage = call_for_structured(
        system=_PROBE_GEN_SYSTEM,
        user_message=_build_query_gen_message(inp),
        output_schema=_Probes,
        model=model,
        max_tokens=240,
        condition_label="verifier_probe_gen",
        prompt_version_id=prompt_id,
        usage_context=f"verifier_probe_gen:{inp.question_id}:{inp.country_code}",
        subtrio_id=subtrio_id,
    )
    return parsed.queries, usage


# Substring check (Python-only, no LLM)

def _run_substring_check(
    source_url: str,
    evidence_quote: str,
    researcher_snippets: Optional[List[str]] = None,
) -> tuple[str, Optional[str], Optional[FetchResult]]:
    """Check whether the Researcher's evidence_quote is present in the
    text the Researcher actually read.

    When researcher_snippets is non-empty the check is performed against
    the concatenated snippets from the Researcher's search results. This
    is the faithful anti-hallucination gate: the Researcher only ever
    reads search snippets (~300 chars each), never full pages, so the
    relevant corpus is those snippets, not the live URL.

    When researcher_snippets is empty or None the original live-fetch
    behaviour is preserved for back-compat (catalogue-computed answers
    and any path that does not supply snippets).

    Returns (result, notes, fetch_result) where result is one of
    "pass", "fail", "not_attempted". fetch_result is None for the
    snippet path.
    """
    # Snippet path (preferred when snippets are available)
    # P4 (EXP-11, shipped 2026-06-10): match per snippet with the
    # ellipsis-aware v2 matcher rather than against a joined corpus. v1
    # let a quote stitched across the junction of two snippets pass
    # (the "\n\n" join collapsed under normalisation) and wrongly failed
    # legitimate within-snippet elisions. The S0.1 replay over every
    # stored run confirmed v2 rejects nothing v1 passed on this path,
    # admits only within-snippet elisions, and catches cross-snippet
    # splices. See docs/EXPERIMENTS_VERIFIER_REDESIGN.md S0.1.
    if researcher_snippets:
        match = substring.contains_v2(researcher_snippets, evidence_quote)
        if match.matched:
            return (
                "pass",
                f"matched against snippet {match.snippet_index} the "
                f"Researcher read ({match.n_fragments} fragment(s))",
                None,
            )
        return (
            "fail",
            f"quote not present in any single snippet the Researcher "
            f"read (v2 reason: {match.reason})",
            None,
        )

    # Live-fetch path (back-compat: empty/None snippets)
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


# Verifier run result

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


# Verifier entry point

StepCallback = Callable[[str, dict], None]


def _noop(event: str, payload: dict) -> None:  # pragma: no cover
    return


def _scrub_forbidden_counter_source(
    output: "VerifierOutput",
) -> "Optional[VerifierOutput]":
    """Strip a deny-listed counter_source_url from a Verifier verdict (D24).

    search() scrubs blocked domains from results, but the strategy LLM can
    still emit a deny-listed ODMI mirror as counter_source_url from parametric
    memory (the EXP-36 post-run audit found 7 such rows, all on this
    counter-search channel; docs/EXP36_LEAKAGE_AUDIT.md). A refutation resting
    on the answer key is inadmissible under D24 in either direction, so the
    source and its quote are stripped before anything is persisted or shown.
    The verdict is left intact: the Verifier's doubt may be independently
    sound, so a fail retries for an admissible source (or abstains on
    exhaustion) rather than being flipped to a commit. Also guards the
    corroborate strategy's contradiction source.

    Returns the scrubbed copy if the URL was blocked, else None (no change).
    """
    if not output.counter_source_url:
        return None
    if not is_blocked(str(output.counter_source_url)):
        return None
    return output.model_copy(update={
        "counter_source_url": None,
        "counter_evidence_quote": (
            "Counter-evidence cited a deny-listed ODMI source and was "
            "removed under D24; find an admissible source."
        ),
        "rejection_reason": (
            "forbidden_odmi_source (verifier counter-search): "
            + (output.rejection_reason or "")
        ).strip(),
    })


def _is_catalogue_computed(researcher_output: ResearcherOutput) -> bool:
    from agents.tools.catalogue.compute import CATALOGUE_NOTE_TAG

    return bool(
        researcher_output.notes and CATALOGUE_NOTE_TAG in researcher_output.notes
    )


def _verify_catalogue(
    inp: VerifierInput, on_step: "StepCallback"
) -> VerifierRunResult:
    """Verify a catalogue-computed answer by deterministic recompute.

    No LLM call, no web search: re-run the metric from the cached snapshot
    and pass iff the recomputed band equals the Researcher's answer. A
    mismatch is a genuine signal (the cache moved, or the answer was
    hand-edited) and is reported as a fail with the recomputed band as
    counter-evidence.
    """
    from agents.tools.catalogue import compute as catalogue_compute

    ro = inp.researcher_output
    on_step("catalogue_recompute_start", {
        "question_id": inp.question_id, "country": inp.country_code,
    })
    comp = catalogue_compute.compute(
        inp.question_id, inp.country_code, write_receipt=False
    )

    if comp is None:
        # Cannot recompute (cache gone, harvest failed). Do not block: accept
        # the Researcher's deterministic answer, but record that we could not
        # re-derive it.
        out = VerifierOutput(
            verdict="pass",
            verifier_answer=ro.answer,
            verifier_confidence=0.5,
            substring_check_result="not_attempted",
            substring_check_notes="catalogue recompute unavailable; accepted as-is",
        )
        on_step("catalogue_recompute_complete", {"recomputed": None, "verdict": "pass"})
        return VerifierRunResult(
            output=out, failure_mode=None, query_gen_usage=None, main_usage=None,
            substring_result="not_attempted",
            substring_notes="catalogue recompute unavailable",
            strategy=inp.strategy,
            notes="catalogue_recompute_unavailable",
        )

    matches = comp.band == ro.answer
    on_step("catalogue_recompute_complete", {
        "recomputed": comp.band, "researcher": ro.answer, "match": matches,
    })

    if matches:
        out = VerifierOutput(
            verdict="pass",
            verifier_answer=comp.band,
            verifier_confidence=0.98,
            substring_check_result="pass",
            substring_check_notes=(
                f"Deterministic recompute reproduced the band: {comp.evidence_quote}"
            ),
            independent_evidence_snippets=[comp.evidence_quote],
        )
    else:
        out = VerifierOutput(
            verdict="fail",
            verifier_answer=comp.band,
            verifier_confidence=0.9,
            substring_check_result="fail",
            substring_check_notes="recomputed band differs from researcher answer",
            rejection_reason=(
                f"Deterministic recompute gives {comp.band!r}, not "
                f"{ro.answer!r}. {comp.evidence_quote}"
            ),
            counter_evidence_quote=comp.evidence_quote,
            counter_source_url=comp.source_url,
            independent_evidence_snippets=[comp.evidence_quote],
        )

    return VerifierRunResult(
        output=out,
        failure_mode=None,
        query_gen_usage=None,
        main_usage=None,
        substring_result=out.substring_check_result,
        substring_notes=out.substring_check_notes,
        strategy=inp.strategy,
        notes="catalogue_recompute",
    )


def run_verifier(
    inp: VerifierInput,
    *,
    model: str | None = None,
    condition_label: str = "baseline",
    max_results_per_query: int = 5,
    provider: str = "auto",
    num_queries: Optional[int] = None,
    verifier_search: VerifierSearchPolicy = "always",
    picker_model: Optional[str] = None,
    verifier_prompt_variant: str = "default",
    on_step: StepCallback = _noop,
    subtrio_id: str | None = None,
) -> VerifierRunResult:
    """Run the Verifier once on a single (question, country, researcher_output).

    Failure modes are recorded on the returned object rather than raised;
    the caller writes a row either way to preserve the audit trail.

    `model` selects the Claude model for both the adversarial query-gen
    and the main verdict call (EXP-9 model variants); `None` keeps the
    wrapper default (Sonnet).

    `verifier_search` (EXP-14) is the web counter-search policy. "always"
    is the default and is byte-identical to current production: generate
    adversarial queries, run them live, and feed the snippets to the verdict
    call. "never" skips that independent search and reasons only over the
    Researcher's own snippets. "elective" is not implemented yet and raises
    NotImplementedError. The substring gate and all verdict post-processing
    are unchanged by this knob. See the VerifierSearchPolicy note above.

    `verifier_prompt_variant` (EXP-B) selects the prompt body for the
    `verifier-disprove` strategy. "default" (the production V4 prompt)
    is byte-identical to historic behaviour; "structured" swaps in the
    structured Step 3 fit-check (entity / scope / tense / metric /
    scale). Only the `verifier-disprove` strategy honours this knob;
    every other strategy raises if a non-default variant is passed.

    `on_step(event, payload)` is the walkthrough callback.
    """
    strategy = inp.strategy
    if strategy == "verifier-disprove":
        v = verifier_prompt.disprove_variant(verifier_prompt_variant)
        spec = verifier_prompt._StrategySpec(
            name=v.name, version=v.version, system=v.system,
            description=v.description,
        )
    else:
        if verifier_prompt_variant != "default":
            raise ValueError(
                f"verifier_prompt_variant={verifier_prompt_variant!r} is only "
                f"defined for strategy='verifier-disprove'; strategy={strategy!r} "
                f"does not accept variants. Use the default variant or change "
                f"the strategy."
            )
        spec = verifier_prompt.STRATEGIES[strategy]

    on_step("start", {
        "question_id": inp.question_id,
        "country": inp.country_code,
        "strategy": strategy,
        "researcher_answer": inp.researcher_output.answer,
    })

    # D30: deterministic recompute for catalogue-computed answers
    # The Researcher's answer is a counted statistic, so adversarial web
    # search does not apply. Recompute from the cached snapshot and pass
    # iff the band matches.
    if _is_catalogue_computed(inp.researcher_output):
        return _verify_catalogue(inp, on_step)

    # Stage 1: substring check (Python, no LLM)
    on_step("substring_check_start", {"url": str(inp.researcher_output.source_url)})

    sub_result, sub_notes, fetch = _run_substring_check(
        str(inp.researcher_output.source_url),
        inp.researcher_output.evidence_quote,
        researcher_snippets=inp.researcher_snippets if inp.researcher_snippets else None,
    )

    on_step("substring_check_complete", {
        "result": sub_result,
        "notes": sub_notes,
        "fetch_status": fetch.status_code if fetch else None,
    })

    # EXP-14: web counter-search policy gate
    # "elective" is not built; fail loud rather than silently behaving like
    # "always". "never" skips the independent query-gen and search below.
    if verifier_search == "elective":
        # TODO(EXP-14): give the Verifier the choice to counter-search after
        # reading the Researcher's evidence, stating a one-line reason, then
        # branch on that choice. Until then this arm must not be dispatched.
        raise NotImplementedError(
            "verifier_search='elective' is not implemented. Use 'always' "
            "(production default) or 'never'."
        )

    skip_web_search = verifier_search == "never"

    if skip_web_search:
        # No independent web counter-search this round. The Verifier reasons
        # only over the Researcher's own snippets, which still drive the
        # substring gate and are surfaced to the verdict call below. No
        # query-gen call is made, so there is no query-gen usage to bill.
        on_step("search_skipped", {"policy": verifier_search})
        query_usage = None
        queries = []
        search_results = []
        independent_snippets = []
    else:
        # Stage 2: query generation, in the direction of the stance
        # EXP-42: the corroborative stance searches for support. Before this
        # the cooperative arm shared the adversarial generator, so it looked
        # for counter-evidence while its verdict step asked for corroboration.
        seek_support = strategy == "verifier-corroborate"
        gen = (
            generate_corroborative_queries if seek_support
            else generate_adversarial_queries
        )
        on_step("query_gen_start", {"direction": "support" if seek_support else "counter"})
        try:
            queries, query_usage = gen(
                inp, subtrio_id=subtrio_id, model=model,
            )
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

        # Stage 3: independent search
        on_step("search_start", {"queries": queries})
        search_results = search_many(
            queries, max_results_per_query=max_results_per_query, provider=provider,
            picker_model=picker_model, subtrio_id=subtrio_id,
        )
        on_step("search_complete", {
            "n_results": len(search_results),
            "top_titles": [r.title[:80] for r in search_results[:5]],
        })

        independent_snippets = [
            f"{r.title} — {r.snippet[:200]}" for r in search_results
        ]

    # Stage 4: register prompt and call the LLM
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
        answer_shape=inp.answer_shape,
        allowed_answers=list(inp.allowed_answers),
        verifier_search=verifier_search,
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
            model=model,
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

    # D28: validate verifier_answer against the question's shape
    notes_parts: List[str] = []
    shape = answer_shapes.QuestionShape(
        question_id=inp.question_id,
        shape=inp.answer_shape,
        allowed_answers=tuple(inp.allowed_answers),
    )
    normalised = answer_shapes.normalise_answer(output.verifier_answer, shape)
    if normalised != output.verifier_answer:
        notes_parts.append(
            f"verifier_answer normalised from {output.verifier_answer!r} "
            f"to {normalised!r}"
        )
        output = output.model_copy(update={"verifier_answer": normalised})
    if not answer_shapes.is_valid_answer(output.verifier_answer, shape):
        notes_parts.append(
            f"verifier_answer {output.verifier_answer!r} not in allowed set"
        )

    # Hard grounding gate: a failed substring check is fabrication
    # The substring check is deterministic, so its consequence must be too.
    # A quote absent from the snippets the Researcher actually read is
    # fabrication or misquotation; we reject it structurally rather than
    # leaving it to the strategy LLM's discretion (the LLM could rationalise
    # a pass when the answer happens to look correct). This mirrors the blind
    # and catalogue-recompute hard overrides and enforces the project's
    # no-hallucination standard in code, not in a prompt.
    if sub_result == "fail" and output.verdict == "pass":
        notes_parts.append(
            "substring check failed (quote not in the snippets the Researcher "
            "read) — verdict overridden to fail (hard grounding gate)"
        )
        output = output.model_copy(update={
            "verdict": "fail",
            "rejection_reason": (
                "Evidence quote not found in the snippets the Researcher read; "
                "treated as fabrication or misquotation. "
                + (output.rejection_reason or "")
            ).strip(),
            "counter_evidence_quote": (
                output.counter_evidence_quote
                or sub_notes
                or "grounding check failed: cited quote absent from sources read"
            ),
            "suggested_search_query": (
                output.suggested_search_query
                or (queries[0] if queries else None)
            ),
        })

    # Strategy D post-processing: compare answers
    # For blind strategy, the model returned its own answer without
    # seeing the Researcher's. If they differ, override verdict to fail.
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

    # D24 deny-list gate on the Verifier's own counter-source
    scrubbed = _scrub_forbidden_counter_source(output)
    if scrubbed is not None:
        on_step("blocked_counter_source", {
            "url": str(output.counter_source_url),
            "verdict": output.verdict,
        })
        notes_parts.append(
            f"counter_source_url {output.counter_source_url} hit the D24 "
            "deny-list; counter-evidence stripped, verdict kept for retry"
        )
        output = scrubbed

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
