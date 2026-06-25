"""Lock the per-model cost arithmetic in agents.tools.llm.

``estimate_cost_usd`` is the single source of truth behind the
``claude_usage_log.estimated_cost_usd`` column and every GBP figure the
dashboard derives from it. The Opus rate was corrected on 2026-06-25 from
the legacy Opus 3/4/4.1 figure ($15/$75 per M) to the current Opus 4.5+
figure ($5/$25 per M). These cases pin the corrected rates against the
claude-api skill current-models table so a regression is caught before it
reaches the cost reporting.
"""
from __future__ import annotations

import pytest

from agents.tools.llm import PRICING_USD_PER_M, estimate_cost_usd

_OPUS_IDS = (
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5-20251101",
)


@pytest.mark.parametrize("model", _OPUS_IDS)
def test_opus_rate_is_five_twentyfive_per_million(model: str) -> None:
    # Current Opus pricing: $5 input / $25 output per M (every Opus 4.5+).
    assert PRICING_USD_PER_M[model] == {"input": 5.0, "output": 25.0}
    # 1M input + 1M output => $5 + $25 = $30 exactly.
    assert estimate_cost_usd(model, 1_000_000, 1_000_000) == pytest.approx(30.0)


def test_sonnet_rate_unchanged() -> None:
    # Sonnet 4.6: $3 input / $15 output per M. Verified correct, not changed.
    assert estimate_cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_haiku_rate_unchanged() -> None:
    # Haiku 4.5: $1 input / $5 output per M. Verified correct, not changed.
    assert (
        estimate_cost_usd("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        == pytest.approx(6.0)
    )


def test_opus_batch_matches_corrected_arithmetic() -> None:
    # The 27-call Opus batch that exposed the bug: 49,959 in + 6,710 out.
    # Corrected $5/$25 -> $0.417545; the old (wrong) $15/$75 gave $1.252635.
    cost = estimate_cost_usd("claude-opus-4-6", 49_959, 6_710)
    assert cost == pytest.approx(0.417545, abs=1e-6)


def test_unknown_model_returns_none() -> None:
    # Off-table models (e.g. a Gemini arm) cost None so the gap is explicit.
    assert estimate_cost_usd("gemini-2.5-pro", 100, 100) is None
