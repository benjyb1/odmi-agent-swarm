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
EXIT_CODE_BLOCKER = 43


class RateLimitedShutdown(RuntimeError):
    """The Anthropic API returned a 429.

    Re-raised from the LLM wrapper. The caller is expected to flush any
    partial state to the DB and exit with EXIT_CODE_RATE_LIMITED.
    """


class AuthUnavailableShutdown(RateLimitedShutdown):
    """CLIProxyAPI returned a 503 `auth_unavailable` (observed 2026-07-02).

    The shared Claude Max auth-file pool has no session available for the
    requested model, typically because several concurrent windows are
    drawing on the same subscription. This is the same shape of problem as
    a 429 (transient shared-capacity exhaustion, not a bug in the caller),
    so it subclasses `RateLimitedShutdown` and reuses its whole contract:
    caught by the same `except RateLimitedShutdown` handlers, same
    `EXIT_CODE_RATE_LIMITED`, same dispatcher global-stop-and-resume
    behaviour. It exists as a distinct subclass only so the Coordinator can
    record an honest `final_failure_reason` (`auth_unavailable`, not
    `anthropic_rate_limit`) — the DB row should say what actually happened.

    Before this was added, the 503 propagated as an uncaught
    `anthropic.InternalServerError`, crashing the coordinator subprocess
    with no DB update at all: the subtrio_status row was orphaned mid-stage
    and no phase2_final row was ever written, so the pair silently vanished
    from both the health check and the resume set until someone happened to
    query subtrio_status for stuck rows.
    """


class BlockerShutdown(BaseException):
    """The DIY fetch stage exceeded its wall-clock ceiling (D43).

    Raised when the DIY pipeline's network fetch/extract stage runs longer
    than `DIY_FETCH_DEADLINE_S`. On the 20x plan DIY is the sole provider
    and should be fast; a slow fetch stage means a real blocker (Cloudflare
    / WAF challenge, a hanging portal, a network fault) that a human must
    clear, so the whole run stops loudly rather than limping on or silently
    substituting another provider.

    It subclasses `BaseException`, not `Exception`, on purpose: the DIY
    pipeline and the agents are littered with `except Exception` handlers
    that record a failure mode and carry on. A blocker must not be absorbed
    by any of them. It propagates untouched to the Coordinator's `main()`,
    which flushes partial state and exits with EXIT_CODE_BLOCKER; the
    dispatcher treats that exit code as a global stop, exactly like a 429.
    """


class CoordinatorError(RuntimeError):
    """Unrecoverable error inside the Coordinator's state machine.

    Used for situations the named-fallbacks table in AGENT_DESIGN does
    not cover (e.g. database write failures). The Coordinator catches
    its own raises, records `final_failure_reason` on the
    subtrio_status row, and exits with code 1.
    """
