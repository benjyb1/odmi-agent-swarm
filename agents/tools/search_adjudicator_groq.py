"""Cross-family judge for the DIY-vs-Tavily search evaluation (Groq / Llama).

The Opus judge in `search_adjudicator.py` rates which of two blind evidence
sets better supports an ODMI gold answer. Because that judge is from the same
model family as the Researcher that extracted the DIY evidence, it risks a
same-family self-preference (pre-registration section 4). This module runs the
identical task on a model hosted by Groq so inter-rater reliability against
Opus can be estimated (Krippendorff's alpha, raw agreement; section 5).

Gemini was the original cross-family choice, but its free quota is zero, so
the second judge is Meta's Llama 3.3 70B served by Groq. Llama is clearly
independent of Anthropic, and Groq's free tier is generous enough for the
reliability run. This module is the Groq twin of `search_adjudicator_gemini.py`
and mirrors it: same `adjudicate_*` signature, same return type, same shared
prompt builder, so the three judges (Opus, Gemini, Groq) see identical text.

Two things differ from `search_adjudicator.py`:

1. The model is Llama on Groq, called DIRECTLY against Groq's
   OpenAI-compatible chat-completions endpoint. The rest of the project routes
   Claude through CLIProxyAPI on localhost:8317, but Llama is not a Claude
   model, so there is no proxy in the path. The key is read from
   `GROQ_API_KEY` in `.env`.
2. There is no Anthropic SDK and no `claude_usage_log` row: Groq calls are off
   the Claude budget. A best-effort usage row is still returned (an
   `LLMUsage`) so the harness can record tokens and wall-clock uniformly, but
   `estimated_cost_usd` is left None (Llama on Groq is not in the Claude
   pricing table) and nothing is written to the Claude usage log.

The prompt is built by the SAME `agents.prompts.search_adjudicator` builder
used by the Opus and Gemini judges. Set `answer_blind=True` to withhold the
gold answer (section 4, judge answer-leakage control).

This is an evaluation tool, not part of the live swarm.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional

import httpx
from dotenv import load_dotenv

from agents.models import LLMUsage
from agents.prompts import search_adjudicator as prompt
from agents.tools.db import ensure_prompt_version
from agents.tools.search_adjudicator import AdjudicationResult, _equalise_counts

# Load env once at import, overriding the shell so a stale GROQ_API_KEY in the
# environment cannot preempt the project's .env (mirrors llm.py and the Gemini
# twin).
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=True)

# Default cross-family judge model. Llama 3.3 70B is the largest open model on
# Groq's free tier and supports the JSON-object response the parser expects.
# The model id can be swapped per call (e.g. to "llama-3.1-8b-instant" for a
# cheaper smoke test, or a future Groq-hosted model) without touching the rest
# of this module.
GROQ_JUDGE_MODEL = "llama-3.3-70b-versatile"

# Groq's OpenAI-compatible REST endpoint. The key is passed as a bearer token,
# the standard OpenAI convention Groq follows.
_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

_DEFAULT_TIMEOUT_S = 60.0


class GroqAuthError(RuntimeError):
    """Raised when the Groq API rejects the key or is unreachable."""


def _api_key() -> Optional[str]:
    """Return GROQ_API_KEY from the environment, or None if it is unset.

    Unlike the Gemini twin this does not raise on a missing key: the probe
    reports the absence as a clean dict, and adjudicate_groq raises a precise
    GroqAuthError itself, so callers always learn the exact reason.
    """
    return os.environ.get("GROQ_API_KEY") or None


def _post_chat_completion(
    *,
    model: str,
    messages: list[dict],
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    response_format: Optional[dict] = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict:
    """POST one chat-completions call to Groq with a bearer key.

    Returns the parsed JSON body on HTTP 200. Raises GroqAuthError with the
    precise upstream status and body on any non-200 or transport error, so the
    caller can record the exact reason rather than a generic failure.
    """
    key = _api_key()
    if not key:
        raise GroqAuthError(
            "GROQ_API_KEY is not set. Add it to .env (the cross-family judge "
            "calls Groq directly, not via CLIProxyAPI)."
        )
    body: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if response_format is not None:
        body["response_format"] = response_format

    headers = {"Authorization": f"Bearer {key}"}
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(_GROQ_CHAT_URL, headers=headers, json=body)
    except httpx.HTTPError as exc:  # network/DNS/timeout
        raise GroqAuthError(
            f"Groq chat-completions transport error for model={model}: {exc!r}"
        ) from exc
    if resp.status_code != 200:
        snippet = resp.text[:400]
        raise GroqAuthError(
            f"Groq chat-completions failed for model={model}: "
            f"HTTP {resp.status_code} {snippet}"
        )
    return resp.json()


def probe_auth_groq(model: str = GROQ_JUDGE_MODEL) -> dict:
    """Minimal live auth probe: one tiny chat-completions ('ping') call.

    Reads GROQ_API_KEY from the environment. If it is absent, returns
    {"ok": False, "error": "GROQ_API_KEY not set"} WITHOUT raising or touching
    the network, so a CLI or test can detect the missing key cheaply. If the
    key is present, makes one tiny call to verify it and returns
    {"ok": True, "model": <model>, "text": <reply>, "key_prefix": <3 chars>}
    on success or {"ok": False, "error": <precise upstream reason>, ...} on
    failure. Never raises: the caller inspects the dict.
    """
    key = _api_key()
    if not key:
        return {"ok": False, "error": "GROQ_API_KEY not set", "key_prefix": None}

    key_prefix = key[:3]
    try:
        data = _post_chat_completion(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=8,
        )
    except GroqAuthError as exc:
        return {
            "ok": False,
            "model": model,
            "error": str(exc),
            "key_prefix": key_prefix,
        }

    text = _extract_text(data)
    return {
        "ok": True,
        "model": model,
        "text": text,
        "key_prefix": key_prefix,
    }


def _extract_text(response: dict) -> str:
    """Pull choices[0].message.content from a chat-completions body.

    Groq follows the OpenAI shape: choices[].message.content is a string.
    Returns "" if the shape is unexpected (the caller's JSON parse then fails
    and surfaces a clear error).
    """
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = (choices[0].get("message") or {})
    return str(message.get("content") or "").strip()


def _usage_from_response(
    response: dict,
    *,
    model: str,
    wall_clock_ms: int,
    raw_text: str,
    prompt_version_id: Optional[int] = None,
    condition_label: str = "search_adjudication_groq",
) -> LLMUsage:
    """Build an LLMUsage from Groq's OpenAI-style usage block.

    Groq reports usage.prompt_tokens / usage.completion_tokens.
    estimated_cost_usd is left None: Llama on Groq is not in the Claude pricing
    table and these calls are off the Claude budget (D1). model_version records
    the Groq model so the receipt names the judge; prompt_version_id ties the
    row to the shared prompt_versions entry, exactly as the Opus and Gemini
    judges' receipts do.
    """
    meta = response.get("usage") or {}
    return LLMUsage(
        input_tokens=int(meta.get("prompt_tokens") or 0),
        output_tokens=int(meta.get("completion_tokens") or 0),
        wall_clock_ms=wall_clock_ms,
        estimated_cost_usd=None,
        model_version=model,
        prompt_version_id=prompt_version_id,
        condition_label=condition_label,
        raw_response=raw_text,
    )


def parse_groq_adjudication(response: dict) -> AdjudicationResult:
    """Map a raw Groq chat-completions body into an AdjudicationResult.

    Extracts choices[0].message.content (a JSON string), strips any markdown
    code fence, and validates it against the AdjudicationResult schema. Raises
    ValueError if the content is absent or does not match the schema, so a
    malformed judge reply fails loud. Mirrors parse_gemini_adjudication.
    """
    text = _extract_text(response)
    if not text:
        raise ValueError(
            "Groq response carried no message content to parse."
        )
    cleaned = _strip_code_fence(text)
    try:
        return AdjudicationResult.model_validate_json(cleaned)
    except Exception as exc:  # noqa: BLE001 - re-raise as a clear ValueError
        raise ValueError(
            f"Groq reply did not match AdjudicationResult: {exc}. "
            f"Raw text (first 300 chars): {text[:300]!r}"
        ) from exc


def _strip_code_fence(text: str) -> str:
    """Strip a leading ```json fence and trailing ``` if present.

    Mirrors the tolerance in agents.tools.llm._extract_json and the Gemini
    twin: an instruction-following model still sometimes wraps JSON in a fence
    despite response_format asking for a bare object.
    """
    s = text.strip()
    if s.startswith("```"):
        first_newline = s.find("\n")
        if first_newline != -1:
            s = s[first_newline + 1 :]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[: -3]
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            s = s[start : end + 1]
    return s.strip()


def adjudicate_groq(
    *,
    question_text: str,
    ground_truth: str,
    evidence_a: List[dict],
    evidence_b: List[dict],
    model: str = GROQ_JUDGE_MODEL,
    answer_blind: bool = False,
    subtrio_id: Optional[str] = None,
) -> tuple[AdjudicationResult, LLMUsage]:
    """Cross-family twin of adjudicate(): same inputs, judged by Llama on Groq.

    Takes the SAME arguments as agents.tools.search_adjudicator.adjudicate
    (plus answer_blind) and returns the SAME (AdjudicationResult, LLMUsage)
    tuple, so the reliability harness can swap judges without reshaping calls.

    With answer_blind=True the gold answer is withheld from the prompt and the
    judge is asked which evidence set better ESTABLISHES an answer; otherwise
    the gold answer is shown, matching the Opus judge's default. The prompt is
    built by the shared `search_adjudicator` builder so Opus, Gemini and Groq
    judge identical text.
    """
    # Register the prompt version for the receipt, exactly as adjudicate() and
    # adjudicate_gemini() do, so the cross-family run is traceable to the same
    # prompt row.
    prompt_version_id = ensure_prompt_version(
        prompt.NAME, prompt.VERSION, prompt.SYSTEM, prompt.DESCRIPTION,
    )
    # Equalise passage counts upstream so neither arm leaks its provider
    # through block length (mirrors adjudicate()).
    evidence_a, evidence_b = _equalise_counts(evidence_a, evidence_b)
    user_message = prompt.build_user_message(
        question_text=question_text,
        ground_truth=ground_truth,
        evidence_a=evidence_a,
        evidence_b=evidence_b,
        answer_blind=answer_blind,
    )

    # Groq's chat-completions endpoint takes a system and a user role, so the
    # judge system prompt and the user message map straight onto OpenAI roles.
    # The schema is appended to the system message so the model returns matching
    # JSON, and response_format asks for a JSON object. The system prompt must
    # match the user-message variant: when answer_blind, both omit the gold
    # answer.
    schema_text = json.dumps(AdjudicationResult.model_json_schema(), indent=2)
    system_message = (
        prompt.system_for(answer_blind)
        + f"\n\nReturn JSON matching this schema:\n{schema_text}"
    )

    started = time.monotonic()
    response = _post_chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        temperature=0.0,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    raw_text = _extract_text(response)
    result = parse_groq_adjudication(response)
    usage = _usage_from_response(
        response,
        model=model,
        wall_clock_ms=elapsed_ms,
        raw_text=raw_text,
        prompt_version_id=prompt_version_id,
        condition_label=(
            "search_adjudication_groq_blind" if answer_blind
            else "search_adjudication_groq"
        ),
    )
    return result, usage
