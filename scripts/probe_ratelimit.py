"""Probe whether CLIProxyAPI forwards Anthropic rate-limit headers.

The Anthropic API returns `anthropic-ratelimit-*` headers on every
successful response. The desktop / Claude Max UI reads those to show
"21% used". If CLIProxyAPI forwards them through to our SDK client we
can do the same on the dashboard. If it strips them we have to fall
back to a guessed message-count cap.

This script fires one cheap call through the proxy and dumps every
header. Cost: a few hundred tokens (<£0.001).

    uv run python scripts/probe_ratelimit.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env", override=True)
sys.path.insert(0, str(REPO_ROOT))

import anthropic  # noqa: E402


def main() -> int:
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.environ["ANTHROPIC_BASE_URL"],
    )

    print(f"Probing {os.environ['ANTHROPIC_BASE_URL']} ...")
    raw = client.messages.with_raw_response.create(
        model="claude-sonnet-4-6",
        max_tokens=8,
        messages=[{"role": "user", "content": "ping"}],
    )

    headers = raw.headers
    print(f"\nStatus: {raw.http_response.status_code}")
    print(f"Header count: {len(headers)}")
    print()

    interesting = []
    everything = []
    for k, v in headers.items():
        line = f"  {k}: {v}"
        everything.append(line)
        if "ratelimit" in k.lower() or "anthropic" in k.lower():
            interesting.append(line)

    if interesting:
        print("=== Anthropic / rate-limit headers ===")
        for line in interesting:
            print(line)
    else:
        print("=== No anthropic-ratelimit-* headers present ===")
        print("CLIProxyAPI is stripping or not generating them; we cannot "
              "read Claude Max remaining capacity this way.")

    print()
    print("=== Full header list ===")
    for line in everything:
        print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
