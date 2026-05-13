"""Display cost figures in pounds sterling.

The DB stores `estimated_cost_usd` because Anthropic publishes its
pricing in USD. Per D1 these figures are the arithmetic equivalent of
direct API billing rather than money that actually moved (Claude Max
is a flat-rate sub), so the headline currency is a presentational
choice. The dissertation is targeted at a UK examiner, so the
dashboard, the slide deck, and every CLI message render costs in
pounds.

Update `USD_TO_GBP` below by hand when the exchange rate drifts more
than ~5%. Not load-bearing — every cost figure is notional.
"""

from __future__ import annotations

# Last reviewed: 2026-05-13.
USD_TO_GBP = 0.79


def to_gbp(usd_amount: float | None) -> float | None:
    if usd_amount is None:
        return None
    try:
        return float(usd_amount) * USD_TO_GBP
    except (TypeError, ValueError):
        return None


def format_gbp(
    usd_amount: float | None,
    *,
    places: int = 2,
    empty: str = "—",
) -> str:
    """Render a USD figure as a £ string."""
    gbp = to_gbp(usd_amount)
    if gbp is None:
        return empty
    return f"£{gbp:.{places}f}"
