"""Orchestration: probing a seed, falling back to alternates, ranking outcomes."""

from __future__ import annotations

from agents.tools.catalogue.discovery.probes import ProbeEvidence
from agents.tools.catalogue.discovery.run import discover_country
from agents.tools.catalogue.discovery.seeds import Seed
from agents.tools.catalogue.discovery.verify import (
    DiscoveryOutcome,
    SampleStats,
    VerifiedRoute,
)

_STATS = SampleStats(10, 1.0, 10, 1.0, 1.0, 1.0, 1.0, 0.0)


def _ev(base):
    return ProbeEvidence(
        stack="ckan", route="ckan_json",
        endpoint=f"{base}/api/3/action/package_search?rows=1", detail="ckan",
    )


def _verified(base):
    return DiscoveryOutcome(
        "XX", "Testland", base, "verified",
        chosen=VerifiedRoute("ckan_json", _ev(base), _STATS),
    )


def test_primary_base_wins_when_it_verifies():
    seed = Seed("XX", "Testland", "https://a.example", "src",
                alternates=("https://b.example",))
    probed: list[str] = []

    def prober(base, hints):
        probed.append(base)
        return [_ev(base)]

    def verifier(cc, name, base, evidence):
        return _verified(base)

    out = discover_country(seed, prober=prober, verifier=verifier)
    assert out.status == "verified"
    assert out.portal_base == "https://a.example"
    assert probed == ["https://a.example"]  # alternate never touched


def test_falls_back_to_alternate_when_primary_fails():
    seed = Seed("XX", "Testland", "https://a.example", "src",
                alternates=("https://b.example",))

    def prober(base, hints):
        return [_ev(base)] if base == "https://b.example" else []

    def verifier(cc, name, base, evidence):
        if not evidence:
            return DiscoveryOutcome(cc, name, base, "failed")
        return _verified(base)

    out = discover_country(seed, prober=prober, verifier=verifier)
    assert out.status == "verified"
    assert out.portal_base == "https://b.example"


def test_needs_new_adapter_beats_failed_across_bases():
    seed = Seed("XX", "Testland", "https://a.example", "src",
                alternates=("https://b.example",))

    def prober(base, hints):
        return []

    def verifier(cc, name, base, evidence):
        if base == "https://a.example":
            return DiscoveryOutcome(cc, name, base, "failed")
        return DiscoveryOutcome(
            cc, name, base, "needs_new_adapter", new_stacks=["opendatasoft"]
        )

    out = discover_country(seed, prober=prober, verifier=verifier)
    assert out.status == "needs_new_adapter"
    assert out.portal_base == "https://b.example"


def test_probe_errors_become_a_failed_outcome_not_a_crash():
    seed = Seed("XX", "Testland", "https://a.example", "src")

    def prober(base, hints):
        raise TimeoutError("portal down")

    def verifier(cc, name, base, evidence):  # pragma: no cover
        raise AssertionError("must not be called")

    out = discover_country(seed, prober=prober, verifier=verifier)
    assert out.status == "failed"
    assert "TimeoutError" in (out.error or "")
