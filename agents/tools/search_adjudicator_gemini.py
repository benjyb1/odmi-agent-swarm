"""Cross-family judge for the DIY-vs-Tavily search evaluation (Gemini).

The Opus judge in `search_adjudicator.py` rates which of two blind evidence
sets better supports an ODMI gold answer. Because that judge is from the same
model family as the Researcher that extracted the DIY evidence, it risks a
same-family self-preference (pre-registration section 4). This module runs the
identical task on Google Gemini so inter-rater reliability against Opus can be
estimated (Krippendorff's alpha, raw agreement; section 5).

Two things differ from `search_adjudicator.py`:

1. The model is Gemini, called DIRECTLY against the Google Generative Language
   API. The rest of the project routes Claude through CLIProxyAPI on
   localhost:8317, but Gemini is not a Claude model, so there is no proxy in
   the path. The key is read from `GEMINI_API_KEY` in `.env`.
2. There is no Anthropic SDK and no `claude_usage_log` row: Gemini calls are
   off the Claude budget. A best-effort usage row is still returned (an
   `LLMUsage`) so the harness can record tokens and wall-clock uniformly, but
   `estimated_cost_usd` is left None (Gemini is not in the Claude pricing
   table) and nothing is written to the Claude usage log.

The prompt is built by the SAME `agents.prompts.search_adjudicator` builder
used by the Opus judge, so the two judges see identical text and any
difference is the model, not the prompt. Set `answer_blind=True` to withhold
the gold answer (section 4, judge answer-leakage control).

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

# Load env once at import, overriding the shell so a stale GEMINI_API_KEY in
# the environment cannot preempt the project's .env (mirrors llm.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=True)

# Default cross-family judge model. gemini-2.0-flash is fast, cheap, and
# supports the JSON-only response the parser expects. Override per call if a
# stronger model (e.g. gemini-1.5-pro) is wanted for the reliability run.
GEMINI_JUDGE_MODEL = "gemini-2.0-flash"

# Google Generative Language REST base. The key is passed as the `key` query
# parameter (AI Studio convention) and, as a fallback, an OAuth-style bearer
# header, because this project's key does not use the usual "AIza" AI Studio
# format (it starts "AQ."), so it may be an OAuth access token.
_GENLANG_BASE = "https://generativelanguage.googleapis.com/v1beta"

_DEFAULT_TIMEOUT_S = 60.0


class GeminiAuthError(RuntimeError):
    """Raised when the Gemini API rejects the key or is unreachable."""


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise GeminiAuthError(
            "GEMINI_API_KEY is not set. Add it to .env (the cross-family "
            "judge calls Google directly, not via CLIProxyAPI)."
        )
    return key


def _looks_like_oauth(key: str) -> bool:
    """AI Studio keys start 'AIza'; anything else may be an OAuth token.

    Used only to choose which auth conventions to try first in the probe, not
    to gate the call.
    """
    return not key.startswith("AIza")


def _post_generate_content(
    *,
    model: str,
    contents: list[dict],
    generation_config: Optional[dict] = None,
    system_instruction: Optional[str] = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict:
    """POST one generateContent call, trying key-as-query then bearer header.

    Returns the parsed JSON body on the first HTTP 200. Raises GeminiAuthError
    with the precise upstream status and body if every auth convention fails,
    so the caller can record the exact reason rather than a generic failure.
    """
    key = _api_key()
    url = f"{_GENLANG_BASE}/models/{model}:generateContent"
    body: dict = {"contents": contents}
    if generation_config is not None:
        body["generationConfig"] = generation_config
    if system_instruction is not None:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    # Try the key as the `key` query parameter first, then a bearer header as
    # a fallback. The live auth probe established that THIS project's key (which
    # starts "AQ.", not the usual AI Studio "AIza") authenticates via the query
    # parameter and is rejected 401 as a bearer token, so query-first both works
    # and keeps any failure message anchored on the real reason rather than on a
    # spurious bearer 401. The bearer fallback is retained for robustness if a
    # future key is a true OAuth access token.
    attempts: list[tuple[str, dict, dict]] = [
        ("key-query", {"key": key}, {}),
        ("bearer-header", {}, {"Authorization": f"Bearer {key}"}),
    ]

    errors: list[str] = []
    with httpx.Client(timeout=timeout_s) as client:
        for label, params, headers in attempts:
            try:
                resp = client.post(url, params=params, headers=headers, json=body)
            except httpx.HTTPError as exc:  # network/DNS/timeout
                errors.append(f"{label}: transport error {exc!r}")
                continue
            if resp.status_code == 200:
                return resp.json()
            # Record the precise upstream reason and keep trying the next auth
            # convention.
            snippet = resp.text[:400]
            errors.append(f"{label}: HTTP {resp.status_code} {snippet}")

    raise GeminiAuthError(
        f"Gemini generateContent failed for model={model}. "
        f"Attempts: {' | '.join(errors)}"
    )


def probe_auth(model: str = GEMINI_JUDGE_MODEL) -> dict:
    """Minimal live auth probe: one tiny generateContent ('ping') call.

    Returns a dict describing the outcome:
      {"ok": True, "model": <model>, "text": <reply>, "key_prefix": "AQ."}
    on success, or {"ok": False, "error": <precise upstream reason>, ...}
    on failure. Never raises: the caller (a CLI or a test) inspects the dict.

    This is the CRITICAL first step in the build plan. It exists so the exact
    auth outcome (authenticates / precise error) is recorded once, rather than
    hammering variations.
    """
    try:
        key = _api_key()
    except GeminiAuthError as exc:
        return {"ok": False, "error": str(exc), "key_prefix": None}

    key_prefix = key[:3]
    try:
        data = _post_generate_content(
            model=model,
            contents=[{"role": "user", "parts": [{"text": "ping"}]}],
            generation_config={"maxOutputTokens": 8, "temperature": 0.0},
        )
    except GeminiAuthError as exc:
        return {
            "ok": False,
            "model": model,
            "error": str(exc),
            "key_prefix": key_prefix,
            "key_looks_oauth": _looks_like_oauth(key),
        }

    text = _extract_text(data)
    return {
        "ok": True,
        "model": model,
        "text": text,
        "key_prefix": key_prefix,
        "key_looks_oauth": _looks_like_oauth(key),
    }


def _extract_text(response: dict) -> str:
    """Pull the first candidate's concatenated text parts from a Gemini body.

    Gemini returns candidates[].content.parts[].text. We join the text parts
    of the first candidate. Returns "" if the shape is unexpected (the caller's
    JSON parse then fails and surfaces a clear error).
    """
    candidates = response.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(str(p.get("text") or "") for p in parts).strip()


def _usage_from_response(
    response: dict,
    *,
    model: str,
    wall_clock_ms: int,
    raw_text: str,
    prompt_version_id: Optional[int] = None,
    condition_label: str = "search_adjudication_gemini",
) -> LLMUsage:
    """Build an LLMUsage from Gemini's usageMetadata.

    Gemini reports promptTokenCount / candidatesTokenCount. estimated_cost_usd
    is left None: Gemini is not in the Claude pricing table and these calls are
    off the Claude budget (D1). model_version records the Gemini model so the
    receipt names the judge; prompt_version_id ties the row to the shared
    prompt_versions entry, exactly as the Opus judge's receipt does.
    """
    meta = response.get("usageMetadata") or {}
    return LLMUsage(
        input_tokens=int(meta.get("promptTokenCount") or 0),
        output_tokens=int(meta.get("candidatesTokenCount") or 0),
        wall_clock_ms=wall_clock_ms,
        estimated_cost_usd=None,
        model_version=model,
        prompt_version_id=prompt_version_id,
        condition_label=condition_label,
        raw_response=raw_text,
    )


def parse_gemini_adjudication(response: dict) -> AdjudicationResult:
    """Map a raw Gemini generateContent body into an AdjudicationResult.

    Extracts the model's text, strips any markdown code fence, and validates it
    against the AdjudicationResult schema. Raises ValueError if the text is
    absent or does not match the schema, so a malformed judge reply fails loud.
    """
    text = _extract_text(response)
    if not text:
        raise ValueError(
            "Gemini response carried no candidate text to parse."
        )
    cleaned = _strip_code_fence(text)
    try:
        return AdjudicationResult.model_validate_json(cleaned)
    except Exception as exc:  # noqa: BLE001 - re-raise as a clear ValueError
        raise ValueError(
            f"Gemini reply did not match AdjudicationResult: {exc}. "
            f"Raw text (first 300 chars): {text[:300]!r}"
        ) from exc


def _strip_code_fence(text: str) -> str:
    """Strip a leading ```json fence and trailing ``` if present.

    Mirrors the tolerance in agents.tools.llm._extract_json: Gemini, like
    Claude, sometimes wraps JSON in a fence despite the instruction.
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


def adjudicate_gemini(
    *,
    question_text: str,
    ground_truth: str,
    evidence_a: List[dict],
    evidence_b: List[dict],
    model: str = GEMINI_JUDGE_MODEL,
    answer_blind: bool = False,
    subtrio_id: Optional[str] = None,
) -> tuple[AdjudicationResult, LLMUsage]:
    """Cross-family twin of adjudicate(): same inputs, judged by Gemini.

    Takes the SAME arguments as agents.tools.search_adjudicator.adjudicate
    (plus answer_blind) and returns the SAME (AdjudicationResult, LLMUsage)
    tuple, so the reliability harness can swap judges without reshaping calls.

    With answer_blind=True the gold answer is withheld from the prompt and the
    judge is asked which evidence set better ESTABLISHES an answer; otherwise
    the gold answer is shown, matching the Opus judge's default. The prompt is
    built by the shared `search_adjudicator` builder so Opus and Gemini judge
    identical text.
    """
    # Register the prompt version for the receipt, exactly as adjudicate()
    # does, so the cross-family run is traceable to the same prompt row.
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

    # Gemini has no separate system role in the same shape as Anthropic; pass
    # the judge system prompt via systemInstruction, append the schema so the
    # model returns matching JSON, and request a JSON mime type. The system
    # prompt must match the user-message variant: when answer_blind, both omit
    # the gold answer.
    schema_text = json.dumps(AdjudicationResult.model_json_schema(), indent=2)
    system_instruction = (
        prompt.system_for(answer_blind)
        + f"\n\nReturn JSON matching this schema:\n{schema_text}"
    )

    started = time.monotonic()
    response = _post_generate_content(
        model=model,
        contents=[{"role": "user", "parts": [{"text": user_message}]}],
        generation_config={
            "temperature": 0.0,
            "maxOutputTokens": 1200,
            "responseMimeType": "application/json",
        },
        system_instruction=system_instruction,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    raw_text = _extract_text(response)
    result = parse_gemini_adjudication(response)
    usage = _usage_from_response(
        response,
        model=model,
        wall_clock_ms=elapsed_ms,
        raw_text=raw_text,
        prompt_version_id=prompt_version_id,
        condition_label=(
            "search_adjudication_gemini_blind" if answer_blind
            else "search_adjudication_gemini"
        ),
    )
    return result, usage
