#!/usr/bin/env python3
"""Recompute claude_usage_log.estimated_cost_usd from the current rate table.

Why this exists
---------------
The Opus rate in ``agents.tools.llm.PRICING_USD_PER_M`` was corrected on
2026-06-25 from the legacy $15/$75 per M (the Opus 3/4/4.1 figure) to the
current $5/$25 per M (every Opus from 4.5 onward). ``estimated_cost_usd``
is a notional API-equivalent figure, not a real billing record (D1/Q9: the
swarm runs on a flat CLIProxyAPI Max subscription), so correcting the
historical rows to the right notional value is the honest choice and keeps
the column reproducible from (tokens x rate), which is the project
reproducibility standard.

What it does
------------
For every model in ``PRICING_USD_PER_M`` it rewrites ``estimated_cost_usd``
to ``input_tokens*rate_in/1e6 + output_tokens*rate_out/1e6``, but only for
rows that already carry a non-NULL cost which differs from the recompute
(tolerance 1e-6, above last-ULP float noise). Two kinds of row are left
untouched on purpose: rows whose model is not in the table (Mistral /
Gemini / Groq adjudicator rows logged with NULL), and NULL-cost rows of a
priced model (failed or zero-token calls, where NULL is a meaningful "no
cost recorded" signal, not a zero). The arithmetic comes straight from the
rate table, so it can never drift from ``estimate_cost_usd``. Idempotent: a
second run reports zero wrong rows and changes nothing.

Safety
------
- Dry run by default; pass ``--apply`` to write.
- Defaults to the repo's ``data/odmi.db``. The binary DB diverges per git
  worktree, so run this from the canonical checkout to hit the live DB,
  not a stale worktree copy.
- One transaction; prints a per-model before/after summary.

Usage
-----
    uv run python scripts/backfill_opus_pricing.py            # dry run
    uv run python scripts/backfill_opus_pricing.py --apply    # write
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from agents.tools.llm import PRICING_USD_PER_M

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "odmi.db"


def _summary(
    conn: sqlite3.Connection, model: str, rin: float, rout: float
) -> tuple[int, int, float, float]:
    """Return (rows_total, rows_wrong, old_sum, new_sum) for one model."""
    n, wrong, old_sum, new_sum = conn.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(CASE
                WHEN estimated_cost_usd IS NOT NULL
                     AND ABS(estimated_cost_usd
                             - (input_tokens * ? / 1e6 + output_tokens * ? / 1e6)) > 1e-6
                THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(estimated_cost_usd), 0.0),
            COALESCE(SUM(input_tokens * ? / 1e6 + output_tokens * ? / 1e6), 0.0)
        FROM claude_usage_log
        WHERE model = ?
        """,
        (rin, rout, rin, rout, model),
    ).fetchone()
    return n, wrong, old_sum, new_sum


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Recompute claude_usage_log.estimated_cost_usd from the rate table."
    )
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB, help="SQLite path")
    ap.add_argument(
        "--apply", action="store_true", help="write changes (default: dry run)"
    )
    args = ap.parse_args()

    print(f"DB:   {args.db}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}\n")
    header = f"{'model':30} {'rows':>6} {'wrong':>6} {'old_sum':>11} {'new_sum':>11} {'delta':>11}"
    print(header)
    print("-" * len(header))

    conn = sqlite3.connect(args.db)
    try:
        total_changed = 0
        for model, rates in PRICING_USD_PER_M.items():
            rin, rout = rates["input"], rates["output"]
            n, wrong, old_sum, new_sum = _summary(conn, model, rin, rout)
            if n == 0:
                continue
            print(
                f"{model:30} {n:>6} {wrong:>6} "
                f"{old_sum:>11.4f} {new_sum:>11.4f} {new_sum - old_sum:>11.4f}"
            )
            if args.apply and wrong:
                conn.execute(
                    """
                    UPDATE claude_usage_log
                    SET estimated_cost_usd =
                        input_tokens * ? / 1e6 + output_tokens * ? / 1e6
                    WHERE model = ?
                      AND estimated_cost_usd IS NOT NULL
                      AND ABS(estimated_cost_usd
                              - (input_tokens * ? / 1e6 + output_tokens * ? / 1e6)) > 1e-6
                    """,
                    (rin, rout, model, rin, rout),
                )
                total_changed += wrong
        if args.apply:
            conn.commit()
            print(f"\nApplied. Rows changed: {total_changed}")
        else:
            print("\nDry run. Re-run with --apply to write.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
