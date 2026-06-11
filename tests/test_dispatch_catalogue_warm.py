"""Pre-dispatch catalogue warm step.

A batch can mix web questions with the nine D30 catalogue questions. The
catalogue questions need a harvested snapshot; harvesting inside the
Researcher means a cold cache triggers one full harvest per question and
can occupy every parallel slot, starving the web questions. The warm step
harvests each distinct catalogue country once, up front, so the dispatch
itself only ever replays from cache.

These tests pin the pure selector and the warm driver offline: no network,
no real harvest, no subprocess.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.dispatch_subtrios as ds


# A catalogue question is computable only for a country with a registry.
# The real predicate is agents.tools.catalogue.compute.is_computable; here
# we inject a fake so the selector is tested without the registry/DB.
def _fake_is_computable(catalogue_pairs):
    allowed = set(catalogue_pairs)

    def predicate(qid, cc):
        return (qid, cc.upper()) in allowed

    return predicate


def test_selector_keeps_only_catalogue_pairs_distinct_country():
    pairs = [("Q12", "AT"), ("I1", "AT"), ("Q16", "AT"), ("P1", "FR")]
    is_comp = _fake_is_computable({("Q12", "AT"), ("Q16", "AT")})
    assert ds._catalogue_countries_to_warm(pairs, is_computable=is_comp) == ["AT"]


def test_selector_collects_multiple_countries_sorted():
    pairs = [("Q12", "SI"), ("Q16", "AT"), ("Q12", "AT")]
    is_comp = _fake_is_computable(
        {("Q12", "SI"), ("Q16", "AT"), ("Q12", "AT")}
    )
    assert ds._catalogue_countries_to_warm(pairs, is_computable=is_comp) == ["AT", "SI"]


def test_selector_empty_when_no_catalogue_pairs():
    pairs = [("I1", "FR"), ("P1", "DE")]
    is_comp = _fake_is_computable(set())
    assert ds._catalogue_countries_to_warm(pairs, is_computable=is_comp) == []


def test_selector_uppercases_country_codes():
    pairs = [("Q12", "at")]
    is_comp = _fake_is_computable({("Q12", "AT")})
    assert ds._catalogue_countries_to_warm(pairs, is_computable=is_comp) == ["AT"]


@dataclass
class _FakeSnap:
    dataset_count: int
    partial: bool = False

    @property
    def datasets(self):  # truthy iff non-empty, mirrors the real Snapshot
        return list(range(self.dataset_count))


def test_warm_harvests_each_country_once():
    harvested = []

    def harvest_fn(cc):
        harvested.append(cc)
        return _FakeSnap(100)

    warmed = ds.warm_catalogue_snapshots(
        ["AT", "SI"], harvest_fn=harvest_fn,
        cache_loader=lambda cc: None,  # cold cache
    )
    assert harvested == ["AT", "SI"]
    assert warmed == ["AT", "SI"]


def test_warm_skips_country_with_usable_cache():
    harvested = []

    def harvest_fn(cc):
        harvested.append(cc)
        return _FakeSnap(100)

    def cache_loader(cc):
        return _FakeSnap(2282) if cc == "AT" else None

    warmed = ds.warm_catalogue_snapshots(
        ["AT", "SI"], harvest_fn=harvest_fn, cache_loader=cache_loader,
    )
    assert harvested == ["SI"]   # AT served from cache
    assert warmed == ["SI"]


def test_warm_refresh_reharvests_even_with_cache():
    harvested = []

    def harvest_fn(cc):
        harvested.append(cc)
        return _FakeSnap(100)

    warmed = ds.warm_catalogue_snapshots(
        ["AT"], harvest_fn=harvest_fn,
        cache_loader=lambda cc: _FakeSnap(2282), refresh=True,
    )
    assert harvested == ["AT"]


def test_warm_reharvests_when_cache_is_partial():
    harvested = []

    def harvest_fn(cc):
        harvested.append(cc)
        return _FakeSnap(100)

    warmed = ds.warm_catalogue_snapshots(
        ["RO"], harvest_fn=harvest_fn,
        cache_loader=lambda cc: _FakeSnap(10, partial=True),
    )
    assert harvested == ["RO"]   # a partial cache is not trusted for skip


def test_warm_harvest_failure_does_not_abort_other_countries():
    harvested = []
    msgs = []

    def harvest_fn(cc):
        harvested.append(cc)
        if cc == "RO":
            raise RuntimeError("host unreachable")
        return _FakeSnap(100)

    warmed = ds.warm_catalogue_snapshots(
        ["RO", "SI"], harvest_fn=harvest_fn,
        cache_loader=lambda cc: None, log=msgs.append,
    )
    assert harvested == ["RO", "SI"]   # SI still harvested after RO failed
    assert warmed == ["SI"]
    assert any("RO" in m and "fail" in m.lower() for m in msgs)


class _AfterWarm(Exception):
    """Sentinel raised by a stubbed estimate_pair_cost, the call right
    after the warm block, to halt dispatch() before its threading,
    subprocess and git-publish machinery (covered by other tests)."""


def _stop_after_warm(monkeypatch):
    def boom(**k):
        raise _AfterWarm

    monkeypatch.setattr(ds, "estimate_pair_cost", boom)
    monkeypatch.setattr(ds, "_read_default", lambda role: "claude-sonnet-4-6")


def test_dispatch_warms_when_flag_on(monkeypatch):
    seen = {}

    def fake_warm(countries, **kw):
        seen["countries"] = list(countries)
        return list(countries)

    monkeypatch.setattr(ds, "warm_catalogue_snapshots", fake_warm)
    monkeypatch.setattr(
        ds, "_catalogue_countries_to_warm", lambda pairs, **kw: ["AT"]
    )
    _stop_after_warm(monkeypatch)

    import pytest
    with pytest.raises(_AfterWarm):  # halts right after the warm block
        ds.dispatch(
            pairs=[("Q12", "AT"), ("I1", "AT")],
            parallel_limit=1, warm_catalogue=True,
        )
    assert seen["countries"] == ["AT"]


def test_dispatch_skips_warm_when_flag_off(monkeypatch):
    called = []
    monkeypatch.setattr(
        ds, "warm_catalogue_snapshots",
        lambda *a, **k: called.append(True) or [],
    )
    monkeypatch.setattr(
        ds, "_catalogue_countries_to_warm", lambda pairs, **kw: ["AT"]
    )
    _stop_after_warm(monkeypatch)

    import pytest
    with pytest.raises(_AfterWarm):
        ds.dispatch(pairs=[("Q12", "AT")], parallel_limit=1, warm_catalogue=False)
    assert called == []
