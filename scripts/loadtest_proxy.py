"""Load-test the CLIProxyAPI transport at the EXP-36 dispatch concurrency.

The headline run fires tens of thousands of claude-sonnet-4-6 calls at
`--parallel 3`. A single call succeeding does not prove the shared Max auth pool
and the proxy survive sustained concurrency: history shows connection drops
(APIConnectionError), 429s, and 503 `auth_unavailable` when the auth-file pool
exhausts (D58). This fires N calls at a fixed concurrency and reports the outcome
mix and latency, so a transport fault surfaces before the one-shot run rather
than mid-dispatch.

It makes real (cheap, ~50-token) calls on the Max subscription. Each call
appends a `claude_usage_log` row to the local DB like any other call; it writes
nothing else and touches no experiment data.

  uv run python scripts/loadtest_proxy.py                 # 30 calls, concurrency 3
  uv run python scripts/loadtest_proxy.py --n 60 --concurrency 3
"""
from __future__ import annotations

import argparse
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import BaseModel


class _Ping(BaseModel):
    ok: str


def _load_env() -> None:
    import os
    for envpath in (Path(".env"), Path("/Users/benjyb/Desktop/MscProject/.env")):
        if envpath.exists():
            for line in envpath.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
            return


def _one_call(i: int) -> tuple[str, float]:
    """Return (outcome, latency_ms). outcome is 'ok' or an error class name."""
    from agents.tools import llm
    t0 = time.monotonic()
    try:
        llm.call_for_structured(
            system="Reply with JSON only.",
            user_message=f'Return {{"ok":"{i}"}}.',
            output_schema=_Ping,
            model="claude-sonnet-4-6",
            max_tokens=40,
        )
        return "ok", (time.monotonic() - t0) * 1000
    except Exception as e:  # noqa: BLE001
        return type(e).__name__, (time.monotonic() - t0) * 1000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=30, help="total calls")
    ap.add_argument("--concurrency", type=int, default=3, help="in-flight at once")
    args = ap.parse_args()

    _load_env()
    print(f"firing {args.n} claude-sonnet-4-6 calls at concurrency "
          f"{args.concurrency} ...")

    outcomes: Counter = Counter()
    latencies: list[float] = []
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(_one_call, i) for i in range(args.n)]
        for f in as_completed(futs):
            outcome, ms = f.result()
            outcomes[outcome] += 1
            latencies.append(ms)
    wall = time.monotonic() - t0

    ok = outcomes.get("ok", 0)
    print(f"\nwall: {wall:.1f}s  |  throughput: {args.n / wall:.2f} calls/s")
    print(f"outcomes: {dict(outcomes)}")
    print(f"success rate: {ok}/{args.n} = {ok / args.n:.1%}")
    if latencies:
        print(f"latency ms: p50={statistics.median(latencies):.0f} "
              f"min={min(latencies):.0f} max={max(latencies):.0f}")
    errs = {k: v for k, v in outcomes.items() if k != "ok"}
    if errs:
        print(f"\nERRORS PRESENT: {errs}")
        print("A non-trivial rate of RateLimitError / AuthUnavailableShutdown / "
              "APIConnectionError here means the proxy or auth pool will not hold "
              "the full run at this concurrency; re-auth or lower --parallel.")
        return 1
    print("\nclean: transport held at this concurrency.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
