"""Cold-cache mode for EXP-2 (cost-per-pair comparison across DIY knobs).

EXP-2 runs DIY search-knob conditions one after another through
scripts/dispatch_subtrios.py and compares them by measured cost per pair.
The DIY pipeline caches at the SERP, fetch, and snippet layers, so a later
condition that reads cache entries a previous condition wrote would record
an understated search cost and invalidate the comparison.

The `--no-cache` flag (default OFF) makes a run COLD: the three cache read
functions short-circuit to a miss, so every SERP, fetch, and snippet-pick
is computed live and no condition benefits from another's hits. Writes
still happen, so the cache stays populated as an audit record; only reads
are bypassed.

These tests pin two things:
1. The cache read-disable toggle: with reads disabled, a pre-populated
   cache entry is NOT read and the underlying live function is still called.
2. The CLI wiring: dispatch_subtrios exposes a `--no-cache` flag, threads
   `no_cache` into the dispatch() call, and forwards `--no-cache` to each
   spawned run_coordinator subprocess. Default OFF leaves the command line
   unchanged.

No network, Serper, Playwright, or Claude calls are made.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import agents.tools.search_cache as sc


# ---------------------------------------------------------------------------
# Helpers / fixtures (mirror tests/test_search_diy.py style)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_layers(monkeypatch, tmp_path):
    """Isolate the cache DB and stub every DIY layer so no network is hit.

    Returns a dict of call-tracking lists so a test can assert which live
    layers actually ran.
    """
    from agents.tools.fetch import FetchResult
    from agents.models import LLMUsage
    from agents.tools.search import SearchResult
    from agents.tools.snippet_picker import PickedChunk

    # Throwaway cache DB; reset the ensure-tables guard and the read toggle.
    monkeypatch.setattr(sc, "_DB_PATH", tmp_path / "test_no_cache.db")
    monkeypatch.setattr(sc, "_TABLES_ENSURED", False)
    monkeypatch.setattr(sc, "_READ_DISABLED", False)

    serper_calls: list[str] = []

    def fake_serper(query, **kw):
        serper_calls.append(query)
        return [
            SearchResult(title="A", url="https://a.example", snippet="raw A",
                         score=1.0, provider="serper"),
        ]

    monkeypatch.setattr("agents.tools.search_diy.serper_search", fake_serper)

    fetch_calls: list[str] = []

    def fake_fetch_html(url, **kw):
        fetch_calls.append(url)
        return FetchResult(
            url=url, backend="httpx", status_code=200,
            content=f"FETCHED:{url}", truncated=False, failure_mode=None,
        )

    monkeypatch.setattr("agents.tools.search_diy.fetch_html", fake_fetch_html)
    monkeypatch.setattr(
        "agents.tools.search_diy.extract_text",
        lambda content, url, is_html=True: content,
    )

    fake_usage = LLMUsage(
        input_tokens=1, output_tokens=1, wall_clock_ms=1,
        estimated_cost_usd=0.0, model_version="test",
        prompt_version_id=None, condition_label="t", raw_response="{}",
    )
    picker_calls: list[str] = []

    def fake_picker(*, query, url, page_text, subtrio_id=None):
        picker_calls.append(url)
        return ([PickedChunk(text=f"good chunk for {url}", score=0.9)], fake_usage)

    monkeypatch.setattr("agents.tools.search_diy.pick_snippet", fake_picker)

    return {
        "serper_calls": serper_calls,
        "fetch_calls": fetch_calls,
        "picker_calls": picker_calls,
    }


# ---------------------------------------------------------------------------
# 1. Cache read-disable toggle on the cache object
# ---------------------------------------------------------------------------

class TestCacheReadDisable:
    def test_serp_get_returns_none_when_reads_disabled(self) -> None:
        """A populated SERP entry must read as a miss once reads are disabled."""
        from agents.tools.search import SearchResult
        results = [SearchResult(title="T", url="https://x.example", snippet="S",
                                score=0.5, provider="tavily")]
        sc.serp_put("odmi policy", 5, None, results)
        assert sc.serp_get("odmi policy", 5, None) is not None  # warm baseline

        sc.set_read_disabled(True)
        try:
            assert sc.serp_get("odmi policy", 5, None) is None
        finally:
            sc.set_read_disabled(False)

    def test_fetch_get_returns_none_when_reads_disabled(self) -> None:
        sc.fetch_put("https://x.example/p", "text", status_code=200, backend="httpx")
        assert sc.fetch_get("https://x.example/p") == "text"  # warm baseline

        sc.set_read_disabled(True)
        try:
            assert sc.fetch_get("https://x.example/p") is None
        finally:
            sc.set_read_disabled(False)

    def test_snippet_get_returns_none_when_reads_disabled(self) -> None:
        from agents.tools.snippet_picker import PickedChunk
        sc.snippet_put("q", "page", [PickedChunk(text="c", score=0.8)])
        assert sc.snippet_get("q", "page") is not None  # warm baseline

        sc.set_read_disabled(True)
        try:
            assert sc.snippet_get("q", "page") is None
        finally:
            sc.set_read_disabled(False)

    def test_writes_still_persist_when_reads_disabled(self) -> None:
        """Reads are bypassed but writes continue, so re-enabling reads sees
        the entry the cold run wrote (audit-trail semantics)."""
        from agents.tools.search import SearchResult
        sc.set_read_disabled(True)
        try:
            sc.serp_put("q", 5, None,
                        [SearchResult(title="T", url="https://x.example",
                                      snippet="S", score=0.5, provider="tavily")])
            assert sc.serp_get("q", 5, None) is None  # still a cold miss
        finally:
            sc.set_read_disabled(False)
        assert sc.serp_get("q", 5, None) is not None  # write did land

    def test_isolated_default_is_reads_enabled(self) -> None:
        """The toggle defaults OFF so existing behaviour is unchanged."""
        from agents.tools.search import SearchResult
        sc.serp_put("q", 5, None,
                    [SearchResult(title="T", url="https://x.example",
                                  snippet="S", score=0.5, provider="tavily")])
        assert sc.serp_get("q", 5, None) is not None


# ---------------------------------------------------------------------------
# 2. End-to-end through the DIY search path
# ---------------------------------------------------------------------------

class TestDiySearchPathCold:
    def test_diy_serp_cache_hit_skips_serper_when_reads_enabled(self, mock_layers):
        """Sanity check: with reads ON, the second call is served from cache."""
        from agents.tools.search_diy import diy_search
        diy_search("test query")
        diy_search("test query")
        assert len(mock_layers["serper_calls"]) == 1  # cache hit on second call

    def test_diy_recomputes_live_when_reads_disabled(self, mock_layers):
        """The crux. Pre-populate every cache layer, disable reads, run DIY.

        The cache entries must NOT be read: serper, fetch, and the snippet
        picker all fire again on the second call. This is what makes a later
        EXP-2 condition pay its own cold search cost.
        """
        from agents.tools.search_diy import diy_search

        # First call warms all three layers (reads still enabled here).
        diy_search("test query")
        assert mock_layers["serper_calls"] == ["test query"]
        assert mock_layers["fetch_calls"] == ["https://a.example"]
        assert mock_layers["picker_calls"] == ["https://a.example"]

        # Disable reads: the warm entries must be ignored.
        sc.set_read_disabled(True)
        try:
            diy_search("test query")
        finally:
            sc.set_read_disabled(False)

        # Live functions were called a SECOND time (cache NOT read).
        assert len(mock_layers["serper_calls"]) == 2
        assert len(mock_layers["fetch_calls"]) == 2
        assert len(mock_layers["picker_calls"]) == 2


# ---------------------------------------------------------------------------
# 3. CLI / dispatch wiring
# ---------------------------------------------------------------------------

class TestDispatchWiring:
    def test_dispatch_accepts_no_cache_and_forwards_to_subprocess(
        self, monkeypatch, tmp_path
    ):
        """dispatch(no_cache=True) must add --no-cache to the spawned command."""
        import scripts.dispatch_subtrios as ds

        captured_cmds: list[list[str]] = []

        class _FakeProc:
            def wait(self):
                return 0

        def fake_popen(cmd, **kw):
            captured_cmds.append(list(cmd))
            return _FakeProc()

        # Neutralise everything dispatch() touches except the spawn command.
        monkeypatch.setattr(ds.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(ds, "_read_default", lambda role: "claude-sonnet-4-6")
        monkeypatch.setattr(
            ds, "estimate_pair_cost",
            lambda **kw: ds.CostEstimate(
                per_subtrio_usd=0.01, projected_total_usd=0.01,
                rolling_window_cost_usd=0.0, fallback_level="cold_start",
                sample_size=0,
            ),
        )
        monkeypatch.setattr(ds, "rolling_window_cost_usd", lambda *a, **k: 0.0)
        monkeypatch.setattr(ds, "publish_to_main", lambda result, log=None: None)

        ds.dispatch(pairs=[("P1", "FR")], provider="diy", no_cache=True)

        assert len(captured_cmds) == 1
        assert "--no-cache" in captured_cmds[0]

    def test_dispatch_default_omits_no_cache_flag(self, monkeypatch):
        """Default (no_cache unset) must NOT add --no-cache; behaviour unchanged."""
        import scripts.dispatch_subtrios as ds

        captured_cmds: list[list[str]] = []

        class _FakeProc:
            def wait(self):
                return 0

        def fake_popen(cmd, **kw):
            captured_cmds.append(list(cmd))
            return _FakeProc()

        monkeypatch.setattr(ds.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(ds, "_read_default", lambda role: "claude-sonnet-4-6")
        monkeypatch.setattr(
            ds, "estimate_pair_cost",
            lambda **kw: ds.CostEstimate(
                per_subtrio_usd=0.01, projected_total_usd=0.01,
                rolling_window_cost_usd=0.0, fallback_level="cold_start",
                sample_size=0,
            ),
        )
        monkeypatch.setattr(ds, "rolling_window_cost_usd", lambda *a, **k: 0.0)
        monkeypatch.setattr(ds, "publish_to_main", lambda result, log=None: None)

        ds.dispatch(pairs=[("P1", "FR")], provider="diy")

        assert len(captured_cmds) == 1
        assert "--no-cache" not in captured_cmds[0]


# ---------------------------------------------------------------------------
# 4. run_coordinator honours --no-cache by disabling cache reads
# ---------------------------------------------------------------------------

class TestCoordinatorWiring:
    def test_coordinate_sets_read_disabled_when_no_cache(self, monkeypatch):
        """coordinate(no_cache=True) must flip the cache read toggle on."""
        import scripts.run_coordinator as rc

        observed: dict[str, bool] = {}

        # Stop the state machine immediately after the no-cache hook by making
        # the first DB write raise; we only care that the toggle was set.
        def fake_set_read_disabled(value):
            observed["disabled"] = value
            raise _StopHere()

        class _StopHere(Exception):
            pass

        monkeypatch.setattr(
            "agents.tools.search_cache.set_read_disabled", fake_set_read_disabled
        )

        with pytest.raises(_StopHere):
            rc.coordinate(
                question_id="P1", country_code="FR",
                provider="diy", no_cache=True, dry_run=True,
            )
        assert observed["disabled"] is True
