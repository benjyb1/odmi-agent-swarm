"""Mistral provider for the swarm's structured-output calls.

The project routes Claude through CLIProxyAPI in `agents/tools/llm.py`. This
module is the parallel path for Mistral models: when an agent's model id names a
Mistral model (e.g. `mistral-large-latest`), `call_for_structured` delegates
here instead of to the Anthropic SDK. The point is a like-for-like cost and
accuracy comparison (EXP-9, cross-family): the same Researcher / Verifier /
Adjudicator prompts, the same schemas, the same one-retry parse, but a different
model family on a separate quota.

Why a separate module rather than a branch inside `llm.py`:

- Mistral is called DIRECTLY against its OpenAI-compatible chat-completions
  endpoint, not through CLIProxyAPI. There is no Anthropic SDK in the path.
- Mistral calls are off the Claude Max budget, so nothing is written to
  `claude_usage_log`. The returned `LLMUsage` still carries tokens, wall-clock
  and a real Mistral cost, so per-agent receipts stay uniform.
- `estimated_cost_usd` here is the ACTUAL Mistral list price (the comparison is
  the whole reason this exists), not the arithmetic-equivalent Claude figure the
  llm.py path records. The model_version column on every receipt names the
  provider, so the two cost bases are never silently mixed.

The HTTP layer mirrors the proven one in `search_adjudicator_mistral.py`: a
fixed gap before each call to stay under the free-tier ~1 req/s limit, and an
exponential backoff retry on HTTP 429. A hard quota still raises after the
retries and is reported honestly rather than masked.

Key is read from `MISTRAL_API_KEY` in `.env`. If it is unset, the swarm fails
loud with a `MistralProviderError` naming the missing key.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional, TypeVar

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

from agents.models import LLMUsage

# Load env once at import, overriding the shell so a stale MISTRAL_API_KEY in the
# environment cannot preempt the project's .env (mirrors llm.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=True)

# Mistral's OpenAI-compatible REST endpoint. The key is a bearer token.
_MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"

_DEFAULT_TIMEOUT_S = 60.0

# Free-tier pacing and 429 backoff, mirroring search_adjudicator_mistral.py. A
# fixed gap before each request keeps a burst under the ~1 req/s limit; a 429 is
# retried with exponential backoff. A spent hard quota still raises after the
# retries and surfaces as a failed call rather than a silent stall.
_MIN_INTERVAL_S = 1.2
_MAX_RETRIES = 5
_BACKOFF_BASE_S = 2.0
_last_call_at: list[float] = []  # single-slot mutable clock, module-global

# Mistral list pricing in USD per million tokens. Hard-coded so the recorded
# estimated_cost_usd is reproducible regardless of upstream pricing changes;
# refresh deliberately if Mistral's prices move. Unknown models fall through to
# None (the receipt then footnotes the gap, exactly as llm.py does for models
# outside its Claude table).
PRICING_USD_PER_M = {
    "mistral-large-latest":  {"input": 2.0, "output": 6.0},
    "mistral-medium-latest": {"input": 0.4, "output": 2.0},
    "mistral-small-latest":  {"input": 0.2, "output": 0.6},
}


class MistralProviderError(RuntimeError):
    """Raised when the Mistral API rejects the key, is unreachable, or a hard
    quota is spent after the backoff retries."""


def is_mistral_model(model: str | None) -> bool:
    """True if `model` names a Mistral model and should route through here.

    The match is a case-insensitive `mistral` prefix, so `mistral-large-latest`,
    `mistral-small-latest` and any future Mistral id all route here without a
    table edit. None (the default-model sentinel) is not Mistral.
    """
    return bool(model) and model.lower().startswith("mistral")


def _api_key() -> Optional[str]:
    """Return MISTRAL_API_KEY from the environment, or None if it is unset."""
    return os.environ.get("MISTRAL_API_KEY") or None


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Real Mistral list cost for the call, or None for an unpriced model."""
    rates = PRICING_USD_PER_M.get(model)
    if rates is None:
        return None
    return (
        rates["input"] * input_tokens / 1_000_000
        + rates["output"] * output_tokens / 1_000_000
    )


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

    Returns the parsed JSON body on HTTP 200. Raises MistralProviderError with
    the precise upstream status and body on any non-200 or transport error.
    """
    key = _api_key()
    if not key:
        raise MistralProviderError(
            "MISTRAL_API_KEY is not set. Add it to .env (Mistral is called "
            "directly, not via CLIProxyAPI). See docs/EXP_MISTRAL_RUNBOOK.md."
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
        # Pace requests to stay under the free-tier ~1 req/s limit.
        if _last_call_at:
            gap = time.monotonic() - _last_call_at[0]
            if gap < _MIN_INTERVAL_S:
                time.sleep(_MIN_INTERVAL_S - gap)
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(_MISTRAL_CHAT_URL, headers=headers, json=body)
        except httpx.HTTPError as exc:  # network/DNS/timeout
            raise MistralProviderError(
                f"Mistral transport error for model={model}: {exc!r}"
            ) from exc
        finally:
            _last_call_at[:] = [time.monotonic()]

        if resp.status_code == 200:
            return resp.json()
        snippet = resp.text[:400]
        last_err = f"HTTP {resp.status_code} {snippet}"
        # Retry only a 429 (transient rate limit); back off exponentially. Any
        # other status is a hard failure raised at once.
        if resp.status_code == 429:
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE_S * (2 ** attempt))
                continue
            raise MistralProviderError(
                f"Mistral rate limit for model={model} after "
                f"{_MAX_RETRIES} retries: {last_err}"
            )
        raise MistralProviderError(
            f"Mistral call failed for model={model}: {last_err}"
        )


def _extract_text(response: dict) -> str:
    """Pull choices[0].message.content from a chat-completions body."""
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = (choices[0].get("message") or {})
    return str(message.get("content") or "").strip()


def _extract_json(text: str) -> str:
    """Strip code fences and slice to the outermost braces.

    Mirrors agents.tools.llm._extract_json: an instruction-following model still
    sometimes wraps JSON in a markdown fence or adds prose despite the
    response_format request, so we tolerate that without a second call.
    """
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            s = s[start : end + 1]
    return s.strip()


M = TypeVar("M", bound=BaseModel)


def call_mistral_structured(
    *,
    system: str,
    user_message: str,
    output_schema: type[M],
    model: str,
    max_tokens: int = 2000,
    temperature: float = 0.0,
    timeout_s: float = 60.0,
    condition_label: str = "baseline",
    prompt_version_id: int | None = None,
) -> tuple[M, LLMUsage]:
    """Mistral twin of `call_for_structured`: same contract, Mistral family.

    The schema is appended to the system message and `response_format` asks for a
    JSON object, matching the cross-family judge. One retry with a stricter
    "JSON ONLY" suffix on a validation failure, then a StructuredOutputError so
    the Coordinator handles a Mistral schema failure exactly as a Claude one.

    Returns (parsed_object, usage). `usage.estimated_cost_usd` is the real
    Mistral list cost (the comparison's reason for existing); `model_version`
    names the served Mistral model so the receipt is unambiguous.
    """
    # Imported lazily to avoid an import cycle: llm.py imports this module at the
    # top, so this module must not import llm.py at load time.
    from agents.tools.llm import StructuredOutputError

    schema_text = json.dumps(output_schema.model_json_schema(), indent=2)

    attempt = 0
    last_error: Exception | None = None
    raw_text = ""
    cumulative_input_tokens = 0
    cumulative_output_tokens = 0
    cumulative_wall_clock_ms = 0
    served_model = model

    while attempt < 2:
        stricter = (
            "\n\nIMPORTANT: Respond with valid JSON only. "
            "No markdown code fences, no prefix, no suffix. "
            "Match the schema exactly. Previous attempt failed validation."
        )
        user_text = user_message + (stricter if attempt > 0 else "")
        sys_text = system + f"\n\nReturn JSON matching this schema:\n{schema_text}"

        started = time.monotonic()
        response = _post_chat_completion(
            model=model,
            messages=[
                {"role": "system", "content": sys_text},
                {"role": "user", "content": user_text},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            timeout_s=timeout_s,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)

        meta = response.get("usage") or {}
        cumulative_input_tokens += int(meta.get("prompt_tokens") or 0)
        cumulative_output_tokens += int(meta.get("completion_tokens") or 0)
        cumulative_wall_clock_ms += elapsed_ms
        served_model = str(response.get("model") or model)

        raw_text = _extract_text(response)
        json_text = _extract_json(raw_text)

        try:
            parsed = output_schema.model_validate_json(json_text)
            usage = LLMUsage(
                input_tokens=cumulative_input_tokens,
                output_tokens=cumulative_output_tokens,
                wall_clock_ms=cumulative_wall_clock_ms,
                estimated_cost_usd=estimate_cost_usd(
                    served_model, cumulative_input_tokens, cumulative_output_tokens
                ),
                model_version=served_model,
                prompt_version_id=prompt_version_id,
                condition_label=condition_label,
                raw_response=raw_text,
            )
            return parsed, usage
        except Exception as exc:  # noqa: BLE001 - broad catch with retry, mirrors llm.py
            last_error = exc
            attempt += 1

    raise StructuredOutputError(
        f"Mistral failed to parse structured output after {attempt} attempts. "
        f"Last error: {last_error}. Last raw response (first 500 chars): "
        f"{raw_text[:500]!r}"
    )


def probe_mistral_key(model: str = "mistral-large-latest") -> dict:
    """Cheap live auth probe: one tiny 'ping' call. Never raises.

    Returns {"ok": False, "error": "MISTRAL_API_KEY not set"} without touching
    the network if the key is absent, else {"ok": True/False, ...} after one
    small call. The caller inspects the dict (mirrors probe_auth_mistral).
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
    except MistralProviderError as exc:
        return {"ok": False, "model": model, "error": str(exc), "key_prefix": key_prefix}
    return {"ok": True, "model": model, "text": _extract_text(data), "key_prefix": key_prefix}
