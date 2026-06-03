"""Claude wrapper routed through CLIProxyAPI.

Every LLM call in the project flows through `call_for_structured` so
the cost receipts (D12) and prompt versioning (D5) are uniform.

The wrapper does three things:

1. Loads `.env` with `override=True` so the shell's stale
   ANTHROPIC_* values do not preempt the project's `.env`.
2. Calls Claude via the Anthropic SDK pointed at CLIProxyAPI
   (`localhost:8317` per D1).
3. Returns the parsed structured output plus an `LLMUsage` record
   containing token counts, wall-clock ms, and an estimated cost.

Estimated cost is the Anthropic published rate for the requested
model, computed for transparency in the dissertation. Under the
Claude Max subscription (per D1), the marginal cost is zero; the
estimated figure is the arithmetic equivalent had the call been
billed directly. See Q9 in SPEC.md.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from agents.errors import RateLimitedShutdown
from agents.models import LLMUsage

# Load env once at import. Override the shell so stale globals do not win.
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=True)

# Claude for Desktop (and some launch shells) inject an empty
# ANTHROPIC_AUTH_TOKEN into the environment. The Anthropic SDK reads it and
# sends an "Authorization: Bearer " header with no value, which httpx
# rejects locally as an illegal header. That surfaces as a bare
# APIConnectionError, easily mistaken for a rate-limit or a dead proxy. We
# authenticate to CLIProxyAPI via x-api-key (ANTHROPIC_API_KEY), so an empty
# bearer token is never wanted. Drop any blank value before the SDK sees it.
for _stale in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_CUSTOM_HEADERS"):
    if os.environ.get(_stale, "").strip() == "":
        os.environ.pop(_stale, None)


# Anthropic published pricing in USD per million tokens for cost
# arithmetic (Q9). Numbers are intentionally hard-coded here so the
# computed estimated_cost_usd column is reproducible regardless of
# upstream pricing changes; refresh deliberately if/when pricing moves.
PRICING_USD_PER_M = {
    "claude-sonnet-4-6":          {"input": 3.0,  "output": 15.0},
    "claude-sonnet-4-5-20250929": {"input": 3.0,  "output": 15.0},
    "claude-opus-4-6":            {"input": 15.0, "output": 75.0},
    "claude-opus-4-5-20251101":   {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5-20251001":  {"input": 1.0,  "output": 5.0},
    "claude-3-5-haiku-20241022":  {"input": 0.8,  "output": 4.0},
}

DEFAULT_MODEL = "claude-sonnet-4-6"


def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.environ["ANTHROPIC_BASE_URL"],
    )


_DB_PATH = _REPO_ROOT / "data" / "odmi.db"


def _log_claude_usage(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float | None,
    rate_limited: bool,
    context: str | None,
    subtrio_id: str | None,
) -> None:
    """Write one row to claude_usage_log.

    Best-effort. A failure to write the usage row must not break the
    caller's main flow, so all exceptions are swallowed with a stderr
    note. The dashboard tolerates a missing or sparse log; the budget
    widget shows "unknown" if the table is empty.
    """
    try:
        with sqlite3.connect(_DB_PATH, timeout=5.0) as conn:
            conn.execute(
                """INSERT INTO claude_usage_log
                   (timestamp, model, input_tokens, output_tokens,
                    estimated_cost_usd, rate_limited, context, subtrio_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    model,
                    input_tokens,
                    output_tokens,
                    estimated_cost_usd,
                    1 if rate_limited else 0,
                    context,
                    subtrio_id,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - best-effort log
        # Don't raise; main flow proceeds.
        import sys as _sys
        print(f"[llm.py] claude_usage_log write failed: {exc}", file=_sys.stderr)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Compute the arithmetic-equivalent USD cost.

    Returns None if the model is not in the pricing table; the caller
    stores None and the dissertation footnotes the gap.
    """
    rates = PRICING_USD_PER_M.get(model)
    if rates is None:
        return None
    return (
        rates["input"] * input_tokens / 1_000_000
        + rates["output"] * output_tokens / 1_000_000
    )


def _extract_json(text: str) -> str:
    """Strip code fences and leading/trailing whitespace.

    The model occasionally wraps JSON in markdown fences despite
    instructions. We tolerate that without a second call by stripping
    here. If the result still does not parse, the caller retries with
    a stricter prompt.
    """
    s = text.strip()
    if s.startswith("```"):
        # Drop the opening fence (optionally with a language tag).
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        # Drop the closing fence.
        s = re.sub(r"\n?```\s*$", "", s)
    s = s.strip()
    # Defensive fallback: if the model added prose before/after the JSON (or
    # a trailing fence the anchored strip missed), slice to the outermost
    # braces. A clean object already starts "{" and ends "}", so this is a
    # no-op for well-formed output.
    if not (s.startswith("{") and s.endswith("}")):
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            s = s[start : end + 1]
    return s.strip()


M = TypeVar("M", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """Raised when the model fails to produce a valid response after retries."""


def call_for_structured(
    *,
    system: str,
    user_message: str,
    output_schema: type[M],
    model: str | None = None,
    max_tokens: int = 2000,
    temperature: float = 0.0,
    timeout_s: float = 60.0,
    condition_label: str = "baseline",
    prompt_version_id: int | None = None,
    usage_context: str | None = None,
    subtrio_id: str | None = None,
) -> tuple[M, LLMUsage]:
    """Call Claude and parse the response into `output_schema`.

    One retry with a stricter "JSON ONLY" prompt on validation failure.

    Returns
    -------
    (parsed_object, usage)
        `parsed_object` is an instance of `output_schema`.
        `usage` records tokens, wall-clock ms, and estimated cost.

    `model=None` resolves to DEFAULT_MODEL, so a caller threading an
    optional per-agent override (EXP-9) can pass it straight through
    without re-implementing the default. The model the API actually
    served is logged from `response.model`, so the resolved version ID
    lands in claude_usage_log regardless of the alias requested.
    """
    if model is None:
        model = DEFAULT_MODEL
    client = _make_client()
    schema = output_schema.model_json_schema()
    schema_text = json.dumps(schema, indent=2)

    attempt = 0
    last_error: Exception | None = None
    raw_text: str = ""
    response: anthropic.types.Message | None = None
    cumulative_input_tokens = 0
    cumulative_output_tokens = 0
    cumulative_wall_clock_ms = 0

    while attempt < 2:
        stricter = (
            "\n\nIMPORTANT: Respond with valid JSON only. "
            "No markdown code fences, no prefix, no suffix. "
            "Match the schema exactly. Previous attempt failed validation."
        )
        user_text = user_message + (stricter if attempt > 0 else "")
        sys_text = system + (
            f"\n\nReturn JSON matching this schema:\n{schema_text}"
        )

        started = time.monotonic()
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=sys_text,
                messages=[{"role": "user", "content": user_text}],
                timeout=timeout_s,
            )
        except anthropic.RateLimitError as exc:
            # Anthropic 429. Log a placeholder usage row, then raise the
            # typed shutdown signal so the Coordinator can exit cleanly.
            _log_claude_usage(
                model=model,
                input_tokens=0,
                output_tokens=0,
                estimated_cost_usd=None,
                rate_limited=True,
                context=usage_context,
                subtrio_id=subtrio_id,
            )
            raise RateLimitedShutdown(
                f"Anthropic rate limit hit for model={model}: {exc}"
            ) from exc

        elapsed_ms = int((time.monotonic() - started) * 1000)

        cumulative_input_tokens += response.usage.input_tokens
        cumulative_output_tokens += response.usage.output_tokens
        cumulative_wall_clock_ms += elapsed_ms

        # Per-call usage log (one row per actual Anthropic call, not per retry).
        _log_claude_usage(
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            estimated_cost_usd=estimate_cost_usd(
                response.model,
                response.usage.input_tokens,
                response.usage.output_tokens,
            ),
            rate_limited=False,
            context=usage_context,
            subtrio_id=subtrio_id,
        )

        raw_text = response.content[0].text if response.content else ""
        json_text = _extract_json(raw_text)

        try:
            parsed = output_schema.model_validate_json(json_text)
            usage = LLMUsage(
                input_tokens=cumulative_input_tokens,
                output_tokens=cumulative_output_tokens,
                wall_clock_ms=cumulative_wall_clock_ms,
                estimated_cost_usd=estimate_cost_usd(
                    model, cumulative_input_tokens, cumulative_output_tokens
                ),
                model_version=response.model,
                prompt_version_id=prompt_version_id,
                condition_label=condition_label,
                raw_response=raw_text,
            )
            return parsed, usage
        except Exception as exc:  # noqa: BLE001 - intentional broad catch with retry
            last_error = exc
            attempt += 1

    # Both attempts failed; surface a useful exception with the last raw
    # response so a debugger can read what the model actually said.
    raise StructuredOutputError(
        f"Failed to parse structured output after {attempt} attempts. "
        f"Last error: {last_error}. Last raw response (first 500 chars): "
        f"{raw_text[:500]!r}"
    )
