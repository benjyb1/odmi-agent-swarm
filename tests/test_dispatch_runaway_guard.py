"""Tests for the D41 runaway guards on dispatch_subtrios.

Two circuit breakers, both set far above any real run:
- a pre-flight refusal when a single dispatch exceeds MAX_PAIRS_PER_DISPATCH
  pairs (the cross-product footgun), overridable with allow_large;
- an optional mid-flight stop once the batch's logged calls reach max_calls.

Offline: subprocess.Popen, _read_default, publish_to_main, estimate_pair_cost,
and the call-count helper are monkeypatched so nothing real is spawned.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.dispatch_subtrios as ds


class _FakeProc:
    def wait(self):
        return 0

    def poll(self):
        return 0


def _neutralise(monkeypatch, captured):
    def fake_popen(cmd, **kw):
        captured.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr(ds.subprocess, "Popen", fake_popen)
    # The dispatch loop staggers spawns by 0.05s; skip the wait in tests.
    monkeypatch.setattr(ds.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(ds, "_read_default", lambda role: "claude-sonnet-4-6")
    monkeypatch.setattr(
        ds, "estimate_pair_cost",
        lambda **kw: ds.CostEstimate(
            per_subtrio_usd=0.01, projected_total_usd=0.01,
            rolling_window_cost_usd=0.0, fallback_level="cold_start",
            sample_size=0,
        ),
    )
    monkeypatch.setattr(ds, "publish_to_main", lambda result, log=None: None)
    # The catalogue warm step (D30/D46) would otherwise do a live national
    # harvest for any catalogue-computable pair in the batch (these tests
    # range over Q-ids that include the real catalogue questions for FR).
    # Stub it: "nothing real is spawned" includes no network harvest.
    monkeypatch.setattr(ds, "warm_catalogue_snapshots", lambda *a, **k: [])


# ---------------------------------------------------------------------------
# Pre-flight size guard
# ---------------------------------------------------------------------------

def test_oversize_dispatch_refused(monkeypatch):
    captured: list = []
    _neutralise(monkeypatch, captured)
    pairs = [(f"Q{i}", "FR") for i in range(ds.MAX_PAIRS_PER_DISPATCH + 1)]

    result = ds.dispatch(pairs=pairs)

    assert result.aborted_oversize is True
    assert result.jobs == []
    assert captured == []  # nothing spawned
    assert "REFUSED" in result.messages[0]


def test_oversize_dispatch_allowed_with_override(monkeypatch):
    captured: list = []
    _neutralise(monkeypatch, captured)
    pairs = [(f"Q{i}", "FR") for i in range(ds.MAX_PAIRS_PER_DISPATCH + 1)]

    result = ds.dispatch(pairs=pairs, allow_large=True)

    assert result.aborted_oversize is False
    assert len(result.jobs) == len(pairs)
    assert len(captured) == len(pairs)  # every pair spawned


def test_normal_size_dispatch_unaffected(monkeypatch):
    captured: list = []
    _neutralise(monkeypatch, captured)
    pairs = [("P1", "FR"), ("P2", "DE")]

    result = ds.dispatch(pairs=pairs)

    assert result.aborted_oversize is False
    assert len(captured) == 2


def test_at_threshold_is_allowed(monkeypatch):
    # Exactly MAX_PAIRS_PER_DISPATCH is fine; only strictly above is refused.
    captured: list = []
    _neutralise(monkeypatch, captured)
    pairs = [(f"Q{i}", "FR") for i in range(ds.MAX_PAIRS_PER_DISPATCH)]

    result = ds.dispatch(pairs=pairs)

    assert result.aborted_oversize is False


# ---------------------------------------------------------------------------
# Mid-flight call breaker
# ---------------------------------------------------------------------------

def test_max_calls_off_by_default(monkeypatch):
    captured: list = []
    _neutralise(monkeypatch, captured)
    # Even with a high reported call count, nothing trips when max_calls is None.
    monkeypatch.setattr(ds, "_batch_call_count", lambda ids: 10_000)
    pairs = [("P1", "FR"), ("P2", "DE"), ("P3", "NL")]

    result = ds.dispatch(pairs=pairs)

    assert result.calls_capped is False
    assert len(captured) == 3


def test_max_calls_stops_spawning(monkeypatch):
    captured: list = []
    _neutralise(monkeypatch, captured)
    # Report the cap already exceeded, so the first spawn check trips it.
    monkeypatch.setattr(ds, "_batch_call_count", lambda ids: 999)
    pairs = [("P1", "FR"), ("P2", "DE"), ("P3", "NL")]

    result = ds.dispatch(pairs=pairs, max_calls=100)

    assert result.calls_capped is True
    assert len(captured) == 0  # breaker tripped before any spawn


def test_max_calls_high_does_not_trip(monkeypatch):
    captured: list = []
    _neutralise(monkeypatch, captured)
    monkeypatch.setattr(ds, "_batch_call_count", lambda ids: 5)
    pairs = [("P1", "FR"), ("P2", "DE")]

    result = ds.dispatch(pairs=pairs, max_calls=10_000)

    assert result.calls_capped is False
    assert len(captured) == 2


# ---------------------------------------------------------------------------
# CLI defaults
# ---------------------------------------------------------------------------

def test_dispatch_guard_params_default_safe():
    import inspect
    sig = inspect.signature(ds.dispatch)
    assert sig.parameters["allow_large"].default is False
    assert sig.parameters["max_calls"].default is None
