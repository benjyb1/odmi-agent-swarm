"""Cross-family judge for the DIY-vs-Tavily search evaluation (Mistral Large).

The Opus judge in `search_adjudicator.py` rates which of two blind evidence
sets better supports an ODMI gold answer. Because that judge is from the same
model family as the Researcher that extracted the DIY evidence, it risks a
same-family self-preference (pre-registration section 4). This module runs the
identical task on a model hosted by Mistral so inter-rater reliability against
Opus can be estimated (Krippendorff's alpha, raw agreement; section 5).

Cross-family judge history (pre-registration section 4): Gemini was the original
choice, but its free quota is zero. Groq's Llama 3.3 70B replaced it
(`search_adjudicator_groq.py`), but Groq enforces its free-tier token cap **per
organisation, not per key**, so once that one daily pool is spent every key in
the organisation is blocked. Mistral Large, served by Mistral AI, is a third
clearly-independent family (a French lab, no Anthropic lineage) on a separate
quota, so it can produce the reliability number when Groq's daily pool is gone.
This module is the Mistral twin of `search_adjudicator_groq.py` and mirrors it:
same `adjudicate_*` signature, same return type, same shared prompt builder, so
all judges (Opus, Gemini, Groq, Mistral) see identical text.

Two things differ from `search_adjudicator.py`:

1. The model is Mistral Large, called DIRECTLY against Mistral's
   OpenAI-compatible chat-completions endpoint. The rest of the project routes
   Claude through CLIProxyAPI on localhost:8317, but Mistral is not a Claude
   model, so there is no proxy in the path. The key is read from
   `MISTRAL_API_KEY` in `.env`.
2. There is no Anthropic SDK and no `claude_usage_log` row: Mistral calls are
   off the Claude budget. A best-effort usage row is still returned (an
   `LLMUsage`) so the harness can record tokens and wall-clock uniformly, but
   `estimated_cost_usd` is left None (Mistral is not in the Claude pricing
   table) and nothing is written to the Claude usage log.

The prompt is built by the SAME `agents.prompts.search_adjudicator` builder used
by the Opus, Gemini and Groq judges. Set `answer_blind=True` to withhold the
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

# Load env once at import, overriding the shell so a stale MISTRAL_API_KEY in the
# environment cannot preempt the project's .env (mirrors llm.py and the Groq
# twin).
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=True)

# Default cross-family judge model. Mistral Large is Mistral's strongest model
# and supports the JSON-object response the parser expects. The model id can be
# swapped per call (e.g. to "mistral-small-latest" for a cheaper smoke test, or
# a future Mistral model) without touching the rest of this module.
MISTRAL_JUDGE_MODEL = "mistral-large-latest"

# Mistral's OpenAI-compatible REST endpoint. The key is passed as a bearer
# token, the standard OpenAI convention Mistral follows.
_MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"

_DEFAULT_TIMEOUT_S = 60.0

# Mistral's free tier throttles to roughly one request per second and returns
# HTTP 429 (code 1300, "rate_limited") on a burst. The backfill fires two calls
# per pair, so without throttling it trips the limit immediately. These knobs
# pace the calls (a fixed gap before every request) and retry a 429 with
# exponential backoff, so a transient rate limit recovers instead of dropping
# the pair. They do NOT help a hard quota (a spent monthly cap still raises after
# the retries), which is then reported honestly as an errored pair.
_MIN_INTERVAL_S = 1.2
_MAX_RETRIES = 5
_BACKOFF_BASE_S = 2.0
_last_call_at: list[float] = []  # single-slot mutable clock, module-global


class MistralAuthError(RuntimeError):
    """Raised when the Mistral API rejects the key or is unreachable."""


def _api_key() -> Optional[str]:
    """Return MISTRAL_API_KEY from the environment, or None if it is unset.

    Like the Groq twin this does not raise on a missing key: the probe reports
    the absence as a clean dict, and adjudicate_mistral raises a precise
    MistralAuthError itself, so callers always learn the exact reason.
    """
    return os.environ.get("MISTRAL_API_KEY") or None


def _post_chat_completion(
    *,
    model: str,
    messages: list[dict],
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    response_format: Optional[dict] = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict:
    """POST one chat-completions call to Mistral with a bearer key.

    Returns the parsed JSON body on HTTP 200. Raises MistralAuthError with the
    precise upstream status and body on any non-200 or transport error, so the
    caller can record the exact reason rather than a generic failure.
    """
    key = _api_key()
    if not key:
        raise MistralAuthError(
            "MISTRAL_API_KEY is not set. Add it to .env (the cross-family judge "
            "calls Mistral directly, not via CLIProxyAPI)."
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
    last_err = ""
    for attempt in range(_MAX_RETRIES + 1):
        # Pace requests to stay under the free-tier ~1 req/s limit: wait until at
        # least _MIN_INTERVAL_S has passed since the previous call.
        if _last_call_at:
            gap = time.monotonic() - _last_call_at[0]
            if gap < _MIN_INTERVAL_S:
                time.sleep(_MIN_INTERVAL_S - gap)
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(_MISTRAL_CHAT_URL, headers=headers, json=body)
        except httpx.HTTPError as exc:  # network/DNS/timeout
            raise MistralAuthError(
                f"Mistral chat-completions transport error for model={model}: {exc!r}"
            ) from exc
        finally:
            _last_call_at[:] = [time.monotonic()]

        if resp.status_code == 200:
            return resp.json()
        snippet = resp.text[:400]
        last_err = f"HTTP {resp.status_code} {snippet}"
        # Retry only a 429 (transient rate limit); back off exponentially. Any
        # other status is a hard failure and is raised at once.
        if resp.status_code == 429:
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE_S * (2 ** attempt))
                continue
            raise MistralAuthError(
                f"Mistral chat-completions failed for model={model} after "
                f"{_MAX_RETRIES} retries: {last_err}"
            )
        raise MistralAuthError(
            f"Mistral chat-completions failed for model={model}: {last_err}"
        )


def probe_auth_mistral(model: str = MISTRAL_JUDGE_MODEL) -> dict:
    """Minimal live auth probe: one tiny chat-completions ('ping') call.

    Reads MISTRAL_API_KEY from the environment. If it is absent, returns
    {"ok": False, "error": "MISTRAL_API_KEY not set"} WITHOUT raising or
    touching the network, so a CLI or test can detect the missing key cheaply.
    If the key is present, makes one tiny call to verify it and returns
    {"ok": True, "model": <model>, "text": <reply>, "key_prefix": <3 chars>}
    on success or {"ok": False, "error": <precise upstream reason>, ...} on
    failure. Never raises: the caller inspects the dict.
    """
    key = _api_key()
    if not key:
        return {"ok": False, "error": "MISTRAL_API_KEY not set", "key_prefix": None}

    key_prefix = key[:3]
    try:
        data = _post_chat_completion(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=8,
        )
    except MistralAuthError as exc:
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

    Mistral follows the OpenAI shape: choices[].message.content is a string.
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
    condition_label: str = "search_adjudication_mistral",
) -> LLMUsage:
    """Build an LLMUsage from Mistral's OpenAI-style usage block.

    Mistral reports usage.prompt_tokens / usage.completion_tokens.
    estimated_cost_usd is left None: Mistral is not in the Claude pricing table
    and these calls are off the Claude budget (D1). model_version records the
    Mistral model so the receipt names the judge; prompt_version_id ties the
    row to the shared prompt_versions entry, exactly as the Opus, Gemini and
    Groq judges' receipts do.
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


def parse_mistral_adjudication(response: dict) -> AdjudicationResult:
    """Map a raw Mistral chat-completions body into an AdjudicationResult.

    Extracts choices[0].message.content (a JSON string), strips any markdown
    code fence, and validates it against the AdjudicationResult schema. Raises
    ValueError if the content is absent or does not match the schema, so a
    malformed judge reply fails loud. Mirrors parse_groq_adjudication.
    """
    text = _extract_text(response)
    if not text:
        raise ValueError(
            "Mistral response carried no message content to parse."
        )
    cleaned = _strip_code_fence(text)
    try:
        return AdjudicationResult.model_validate_json(cleaned)
    except Exception as exc:  # noqa: BLE001 - re-raise as a clear ValueError
        raise ValueError(
            f"Mistral reply did not match AdjudicationResult: {exc}. "
            f"Raw text (first 300 chars): {text[:300]!r}"
        ) from exc


def _strip_code_fence(text: str) -> str:
    """Strip a leading ```json fence and trailing ``` if present.

    Mirrors the tolerance in agents.tools.llm._extract_json and the Groq twin:
    an instruction-following model still sometimes wraps JSON in a fence despite
    response_format asking for a bare object.
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


def adjudicate_mistral(
    *,
    question_text: str,
    ground_truth: str,
    evidence_a: List[dict],
    evidence_b: List[dict],
    model: str = MISTRAL_JUDGE_MODEL,
    answer_blind: bool = False,
    subtrio_id: Optional[str] = None,
) -> tuple[AdjudicationResult, LLMUsage]:
    """Cross-family twin of adjudicate(): same inputs, judged by Mistral Large.

    Takes the SAME arguments as agents.tools.search_adjudicator.adjudicate
    (plus answer_blind) and returns the SAME (AdjudicationResult, LLMUsage)
    tuple, so the reliability harness can swap judges without reshaping calls.

    With answer_blind=True the gold answer is withheld from the prompt and the
    judge is asked which evidence set better ESTABLISHES an answer; otherwise
    the gold answer is shown, matching the Opus judge's default. The prompt is
    built by the shared `search_adjudicator` builder so Opus, Gemini, Groq and
    Mistral judge identical text.
    """
    # Register the prompt version for the receipt, exactly as adjudicate() and
    # adjudicate_groq() do, so the cross-family run is traceable to the same
    # prompt row.
    prompt_version_id = ensure_prompt_version(
        prompt.NAME, prompt.VERSION, prompt.SYSTEM, prompt.DESCRIPTION,
    )
    # Equalise passage counts upstream so neither arm leaks its provider through
    # block length (mirrors adjudicate()).
    evidence_a, evidence_b = _equalise_counts(evidence_a, evidence_b)
    user_message = prompt.build_user_message(
        question_text=question_text,
        ground_truth=ground_truth,
        evidence_a=evidence_a,
        evidence_b=evidence_b,
        answer_blind=answer_blind,
    )

    # Mistral's chat-completions endpoint takes a system and a user role, so the
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
    result = parse_mistral_adjudication(response)
    usage = _usage_from_response(
        response,
        model=model,
        wall_clock_ms=elapsed_ms,
        raw_text=raw_text,
        prompt_version_id=prompt_version_id,
        condition_label=(
            "search_adjudication_mistral_blind" if answer_blind
            else "search_adjudication_mistral"
        ),
    )
    return result, usage
