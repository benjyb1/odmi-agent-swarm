"""The model seam for the WHO speech-writer swarm.

Every agent call goes through ``structured()``, which dispatches to the
backend named by ``WHO_LLM_BACKEND``. This is the single point that decouples
the swarm from any one provider:

- ``claude`` (default): the development backend, routed through the project's
  CLIProxyAPI wrapper (``agents.tools.llm.call_for_structured``), which also
  writes the cost/receipt rows the dissertation relies on.
- ``azure_openai``: a deployment in WHO's tenant, the likely production target
  behind Copilot Studio. Structured output is prompt-plus-JSON-mode, the same
  shape the Claude path uses.

Both backends return ``(parsed_object, meta)``. Heavy provider SDKs are
imported lazily inside the backend functions, so importing this module (and
unit-testing the dispatch) needs neither the Anthropic client nor the OpenAI
SDK.
"""
from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel

from who_speech import config

M = TypeVar("M", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """Raised when a backend fails to return output matching the schema."""


def structured(
    *,
    system: str,
    user_message: str,
    output_schema: type[M],
    usage_context: str,
    max_tokens: int = 2000,
    temperature: float = 0.0,
) -> tuple[M, dict]:
    """Call the configured model backend and parse the reply into the schema."""
    backend = config.llm_backend()
    if backend == "claude":
        return _claude_structured(
            system=system, user_message=user_message, output_schema=output_schema,
            usage_context=usage_context, max_tokens=max_tokens, temperature=temperature,
        )
    if backend == "azure_openai":
        return _azure_structured(
            system=system, user_message=user_message, output_schema=output_schema,
            usage_context=usage_context, max_tokens=max_tokens, temperature=temperature,
        )
    raise ValueError(
        f"unknown WHO_LLM_BACKEND {backend!r}; expected 'claude' or 'azure_openai'"
    )


def _claude_structured(
    *, system, user_message, output_schema, usage_context, max_tokens, temperature
):
    """Delegate to the project's CLIProxyAPI wrapper (development backend)."""
    from agents.tools.llm import StructuredOutputError as _ClaudeErr
    from agents.tools.llm import call_for_structured

    try:
        obj, usage = call_for_structured(
            system=system,
            user_message=user_message,
            output_schema=output_schema,
            usage_context=usage_context,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except _ClaudeErr as exc:
        raise StructuredOutputError(str(exc)) from exc
    return obj, {"backend": "claude", "usage": usage}


def _azure_structured(
    *, system, user_message, output_schema, usage_context, max_tokens, temperature
):
    """Call an Azure OpenAI deployment with JSON-mode structured output.

    Written for the production target, but exercised live only once WHO's
    endpoint and key are present; the unit tests cover the parse path with a
    stubbed client. Validate against a real deployment before relying on it.
    """
    client, deployment = _azure_client()
    schema = json.dumps(output_schema.model_json_schema(), indent=2)
    sys_text = f"{system}\n\nReturn JSON matching this schema:\n{schema}"
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": sys_text},
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or ""
    try:
        parsed = output_schema.model_validate_json(_strip_fences(raw))
    except Exception as exc:  # noqa: BLE001 - surface the raw reply for debugging
        raise StructuredOutputError(
            f"azure_openai returned unparseable output ({usage_context}): {raw[:300]!r}"
        ) from exc
    return parsed, {"backend": "azure_openai", "raw": raw}


def _azure_client():
    """Construct an AzureOpenAI client from the environment. Lazy-imported so
    the OpenAI SDK is needed only when this backend is actually selected."""
    from openai import AzureOpenAI

    s = config.azure_openai_settings()
    missing = [k for k in ("endpoint", "api_key", "deployment") if not s[k]]
    if missing:
        raise StructuredOutputError(
            f"azure_openai backend selected but missing settings: {missing}"
        )
    client = AzureOpenAI(
        azure_endpoint=s["endpoint"], api_key=s["api_key"], api_version=s["api_version"]
    )
    return client, s["deployment"]


def _strip_fences(text: str) -> str:
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
