"""Smoke-test a Mistral API key before dispatching a swarm batch on it.

Run this once after adding MISTRAL_API_KEY to .env. It does two things:

1. A cheap auth probe (one tiny 'ping' call) to confirm the key is accepted.
2. A real structured-output call through the same code path the swarm uses
   (`call_for_structured` -> Mistral provider), so a key that authenticates but
   cannot produce schema-valid JSON is caught here, not mid-dispatch.

Usage:
    uv run python scripts/check_mistral.py
    uv run python scripts/check_mistral.py --model mistral-small-latest

Exit code 0 if both checks pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel

from agents.tools.llm import call_for_structured
from agents.tools.mistral_provider import probe_mistral_key


class _Smoke(BaseModel):
    answer: str
    confidence: float


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="mistral-large-latest")
    args = parser.parse_args()

    print(f"1/2 Auth probe ({args.model}) ...", flush=True)
    probe = probe_mistral_key(args.model)
    if not probe.get("ok"):
        print(f"    FAIL: {probe.get('error')}", flush=True)
        if probe.get("error") == "MISTRAL_API_KEY not set":
            print("    Add MISTRAL_API_KEY=... to .env (see "
                  "docs/EXP_MISTRAL_RUNBOOK.md).", flush=True)
        return 1
    print(f"    ok  key={probe.get('key_prefix')}*** reply={probe.get('text')!r}",
          flush=True)

    print("2/2 Structured-output call through the swarm path ...", flush=True)
    try:
        parsed, usage = call_for_structured(
            system="You are a test harness. Answer the question.",
            user_message="Is the sky blue on a clear day? Give answer yes/no and a "
                          "confidence between 0 and 1.",
            output_schema=_Smoke,
            model=args.model,
            condition_label="mistral_smoke_test",
        )
    except Exception as exc:  # noqa: BLE001 - report any failure plainly
        print(f"    FAIL: {type(exc).__name__}: {exc}", flush=True)
        return 1

    print(f"    ok  parsed={parsed.model_dump()}", flush=True)
    print(f"        tokens in/out={usage.input_tokens}/{usage.output_tokens} "
          f"cost_usd={usage.estimated_cost_usd} model={usage.model_version}",
          flush=True)
    print("\nMistral path is live. Dispatch with e.g.:\n"
          "  uv run python scripts/dispatch_subtrios.py --questions P1 --countries MT \\\n"
          f"      --researcher-model {args.model} --verifier-model {args.model} \\\n"
          f"      --adjudicator-model {args.model} --experiment-id exp9_mistral",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
