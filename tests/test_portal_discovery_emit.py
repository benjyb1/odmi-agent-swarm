"""Registry emission: the auto-generated <CC>.json and its leakage gates.

The emitted file must round-trip through `registry.load_portal` (the same
loader the harvest uses), must never overwrite a hand-authored registry
without force, and must refuse any deny-listed endpoint outright.
"""

from __future__ import annotations

import json

import pytest

from agents.tools.catalogue import registry
from agents.tools.catalogue._fetch import BlockedEndpointError
from agents.tools.catalogue.discovery.emit import emit_registry
from agents.tools.catalogue.discovery.probes import ProbeEvidence
from agents.tools.catalogue.discovery.verify import (
    DiscoveryOutcome,
    SampleStats,
    VerifiedRoute,
)


def _outcome(endpoint_base="https://p.example", caveats=None):
    ev = ProbeEvidence(
        stack="ckan",
        route="ckan_json",
        endpoint=f"{endpoint_base}/api/3/action/package_search?rows=1",
        detail="package_search success=true, count=100",
        total_datasets=100,
        config_fields={
            "native_api_url": (
                f"{endpoint_base}/api/3/action/package_search"
                "?rows={page_size}&start={start}"
            ),
            "pagination": "ckan_offset",
            "page_size": 500,
        },
    )
    stats = SampleStats(
        n_datasets=100, licence_share=0.8, with_distributions=90,
        download_url_share=0.9, access_url_share=1.0, format_share=0.95,
        dataset_licence_share=0.8, distribution_licence_share=0.1,
    )
    return DiscoveryOutcome(
        country_code="XX",
        country_name="Testland",
        portal_base=endpoint_base,
        status="verified",
        chosen=VerifiedRoute(
            "ckan_json", ev, stats,
            caveats=list(caveats or ["conformance_synthesised_from_json"]),
        ),
    )


def test_emit_round_trips_through_load_portal(tmp_path, monkeypatch):
    path = emit_registry(_outcome(), portals_dir=tmp_path)
    assert path.name == "XX.json"

    monkeypatch.setattr(registry, "_DIR", tmp_path)
    registry.load_portal.cache_clear()
    cfg = registry.load_portal("XX")
    assert cfg.harvest_route == "ckan_json"
    assert cfg.portal_base == "https://p.example"
    assert cfg.pagination == "ckan_offset"
    assert cfg.page_size == 500
    assert cfg.total_datasets_hint == 100
    registry.load_portal.cache_clear()


def test_emit_records_discovery_provenance(tmp_path):
    path = emit_registry(_outcome(), portals_dir=tmp_path)
    data = json.loads(path.read_text())
    assert data["discovery_method"] == "auto"
    assert data["caveats"] == ["conformance_synthesised_from_json"]
    assert data["verified_at"]  # stamped
    # The probe receipt survives into the registry.
    assert "package_search" in data["discovery_evidence"]
    # Caveats are also readable in prose.
    assert "conformance_synthesised_from_json" in data["notes"]


def test_emit_sets_licence_field_from_sample(tmp_path):
    out = _outcome()
    out.chosen.stats.dataset_licence_share = 0.0
    out.chosen.stats.distribution_licence_share = 0.7
    data = json.loads(emit_registry(out, portals_dir=tmp_path).read_text())
    assert data["licence_field"] == "distribution"


def test_emit_records_robots_note(tmp_path):
    def fake_robots(url: str, **kw) -> bytes:
        assert url == "https://p.example/robots.txt"
        return b"User-agent: *\nDisallow: /api/\nCrawl-delay: 10\n"

    path = emit_registry(
        _outcome(), portals_dir=tmp_path, robots_fetcher=fake_robots
    )
    note = json.loads(path.read_text())["robots_note"]
    assert "Disallow: /api/" in note
    assert "Crawl-delay: 10" in note


def test_emit_robots_note_absent_robots_is_recorded(tmp_path):
    def no_robots(url: str, **kw) -> bytes:
        raise RuntimeError("404")

    path = emit_registry(
        _outcome(), portals_dir=tmp_path, robots_fetcher=no_robots
    )
    note = json.loads(path.read_text())["robots_note"]
    assert "no robots.txt" in note.lower()


def test_emit_refuses_unverified_outcome(tmp_path):
    out = _outcome()
    out.status = "failed"
    out.chosen = None
    with pytest.raises(ValueError):
        emit_registry(out, portals_dir=tmp_path)


def test_emit_refuses_overwrite_without_force(tmp_path):
    (tmp_path / "XX.json").write_text("{}")
    with pytest.raises(FileExistsError):
        emit_registry(_outcome(), portals_dir=tmp_path)


def test_emit_overwrites_with_force(tmp_path):
    (tmp_path / "XX.json").write_text("{}")
    path = emit_registry(_outcome(), portals_dir=tmp_path, force=True)
    assert json.loads(path.read_text())["country_code"] == "XX"


def test_emit_refuses_denylisted_endpoint(tmp_path):
    out = _outcome(endpoint_base="https://data.europa.eu")
    with pytest.raises(BlockedEndpointError):
        emit_registry(out, portals_dir=tmp_path)
    assert not (tmp_path / "XX.json").exists()


def test_emit_refuses_denylisted_url_hidden_in_config_fields(tmp_path):
    out = _outcome()
    out.chosen.evidence.config_fields["dcat_catalog_url"] = (
        "https://web.archive.org/web/2024/https://p.example/catalog.ttl?page={page}"
    )
    with pytest.raises(BlockedEndpointError):
        emit_registry(out, portals_dir=tmp_path)
