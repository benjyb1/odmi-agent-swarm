"""Layer 5: data-leakage deny-list tests for diy and serper_raw providers.

Confirms that _scrub_blocked runs on both new dispatch paths, regardless of
what the underlying search function returns.
"""

import pytest
from agents.tools.search import search, SearchResult
from agents.tools.blocked_domains import BLOCKED_DOMAINS

# Pick a known-blocked domain.
_BLOCKED = "data.europa.eu"
assert _BLOCKED in BLOCKED_DOMAINS or any(_BLOCKED in d for d in BLOCKED_DOMAINS), \
    "Fixture assumes data.europa.eu is blocked; update if list changed"


def _blocked_and_clean_results():
    return [
        SearchResult(title="blocked", url="https://data.europa.eu/example",
                     snippet="s", score=0.9, provider="diy"),
        SearchResult(title="clean", url="https://example.gov.fr/data",
                     snippet="s", score=0.8, provider="diy"),
    ]


def test_diy_provider_scrubs_blocked_domains(monkeypatch):
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: _blocked_and_clean_results(),
    )
    out = search("test", provider="diy")
    urls = [r.url for r in out]
    assert "https://data.europa.eu/example" not in urls
    assert any("example.gov.fr" in u for u in urls)


def test_serper_raw_provider_scrubs_blocked_domains(monkeypatch):
    monkeypatch.setattr(
        "agents.tools.search_serper.serper_search",
        lambda q, **k: [
            SearchResult(title="blocked", url="https://data.europa.eu/x",
                         snippet="s", score=1.0, provider="serper"),
            SearchResult(title="clean", url="https://example.fr/data",
                         snippet="s", score=0.5, provider="serper"),
        ],
    )
    out = search("test", provider="serper_raw")
    urls = [r.url for r in out]
    assert "https://data.europa.eu/x" not in urls


def test_diy_provider_emits_telemetry_with_diy_label(monkeypatch):
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: _blocked_and_clean_results(),
    )
    calls = []
    search("test", provider="diy", on_call=calls.append)
    assert len(calls) == 1
    assert calls[0]["provider"] == "diy"
    assert calls[0]["ok"] is True


def test_diy_provider_telemetry_on_error(monkeypatch):
    def boom(q, **k):
        raise RuntimeError("simulated diy failure")
    monkeypatch.setattr("agents.tools.search_diy.diy_search", boom)
    calls = []
    with pytest.raises(RuntimeError, match="simulated"):
        search("test", provider="diy", on_call=calls.append)
    assert len(calls) == 1
    assert calls[0]["provider"] == "diy"
    assert calls[0]["ok"] is False
    assert "simulated" in calls[0]["error"]
