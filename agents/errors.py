"""Shared exception types and exit codes for the swarm.

Centralised so the dispatcher, Coordinator, and LLM wrapper all agree on
the contract for graceful shutdown when Anthropic returns a 429.

The protocol:
- `agents/tools/llm.py` catches `anthropic.RateLimitError` from the
  Anthropic SDK, writes a final `claude_usage_log` row with
  `rate_limited=1`, and re-raises as `RateLimitedShutdown`.
- The Coordinator's outer handler catches `RateLimitedShutdown`, marks
  its `subtrio_status` row `interrupted_rate_limit`, and exits with
  `EXIT_CODE_RATE_LIMITED` (= 42).
- `scripts/dispatch_subtrios.py` treats exit code 42 as a global stop
  signal: it kills all in-flight children with SIGTERM, marks their
  subtrio_status rows the same way, and exits cleanly.

Both ends import the constant from this file so the contract is one
source of truth.
"""

from __future__ import annotations


EXIT_CODE_RATE_LIMITED = 42


class RateLimitedShutdown(RuntimeError):
    """The Anthropic API returned a 429.

    Re-raised from the LLM wrapper. The caller is expected to flush any
    partial state to the DB and exit with EXIT_CODE_RATE_LIMITED.
    """


class CoordinatorError(RuntimeError):
    """Unrecoverable error inside the Coordinator's state machine.

    Used for situations the named-fallbacks table in AGENT_DESIGN does
    not cover (e.g. database write failures). The Coordinator catches
    its own raises, records `final_failure_reason` on the
    subtrio_status row, and exits with code 1.
    """
