"""Route selection, sample verification and caveat auto-detection.

Offline: the sampler is injected, so the choice logic is tested against
hand-built HarvestedDataset samples that reproduce the known per-portal
quirks (the HU/RO RDF-without-licence pattern, the FDK missing
downloadURL pattern).
"""

from __future__ import annotations

import pytest

from agents.tools.catalogue.discovery.probes import ProbeEvidence
from agents.tools.catalogue.discovery.verify import (
    DiscoveryOutcome,
    choose_and_verify,
    sample_stats,
)
from agents.tools.catalogue.model import Distribution, HarvestedDataset


def _ds(licences=(), dists=()):
    return HarvestedDataset(
        identifier="d",
        dataset_licences=list(licences),
        distributions=list(dists),
    )


def _licensed_sample(n=10):
    return [
        _ds(
            licences=["cc-by"],
            dists=[Distribution(
                fmt="CSV",
                access_url="https://x/f.csv",
                download_url="https://x/f.csv",
            )],
        )
        for _ in range(n)
    ]


def _unlicensed_sample(n=10):
    return [
        _ds(dists=[Distribution(
            fmt="CSV",
            access_url="https://x/f.csv",
            download_url="https://x/f.csv",
        )])
        for _ in range(n)
    ]


def _no_download_sample(n=10):
    return [
        _ds(
            licences=["cc-by"],
            dists=[Distribution(fmt="CSV", access_url="https://x/f")],
        )
        for _ in range(n)
    ]


_RDF_EV = ProbeEvidence(
    stack="dcat_feed", route="dcat_rdf",
    endpoint="https://p.example/catalog.ttl?page=1",
    detail="feed",
    config_fields={
        "dcat_catalog_url": "https://p.example/catalog.ttl?page={page}",
        "pagination": "hydra", "page_size": 100,
    },
)

_CKAN_EV = ProbeEvidence(
    stack="ckan", route="ckan_json",
    endpoint="https://p.example/api/3/action/package_search?rows=1",
    detail="ckan", total_datasets=100,
    config_fields={
        "native_api_url": "https://p.example/api/3/action/package_search?rows={page_size}&start={start}",
        "pagination": "ckan_offset", "page_size": 500,
    },
)

_ODS_EV = ProbeEvidence(
    stack="opendatasoft", route=None,
    endpoint="https://p.example/api/explore/v2.1/catalog/datasets?limit=1",
    detail="ods", total_datasets=50,
)


def test_sample_stats_counts_field_presence():
    stats = sample_stats(_licensed_sample(4) + _unlicensed_sample(6))
    assert stats.n_datasets == 10
    assert stats.licence_share == pytest.approx(0.4)
    assert stats.with_distributions == 10
    assert stats.download_url_share == pytest.approx(1.0)
    assert stats.access_url_share == pytest.approx(1.0)


def test_rdf_route_with_licences_is_chosen_directly():
    def sampler(route, config):
        assert route == "dcat_rdf"
        return _licensed_sample()

    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [_RDF_EV, _CKAN_EV],
        sampler=sampler,
    )
    assert isinstance(out, DiscoveryOutcome)
    assert out.status == "verified"
    assert out.chosen.route == "dcat_rdf"
    assert "rdf_feed_omits_dct_license" not in out.chosen.caveats


def test_hu_pattern_falls_back_to_ckan_when_rdf_has_no_licences():
    def sampler(route, config):
        if route == "dcat_rdf":
            return _unlicensed_sample()
        return _licensed_sample()

    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [_RDF_EV, _CKAN_EV],
        sampler=sampler,
    )
    assert out.status == "verified"
    assert out.chosen.route == "ckan_json"
    assert "rdf_feed_omits_dct_license" in out.chosen.caveats
    assert "conformance_synthesised_from_json" in out.chosen.caveats


def test_rdf_without_licences_and_no_json_alternative_keeps_rdf_with_caveat():
    def sampler(route, config):
        return _unlicensed_sample()

    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [_RDF_EV], sampler=sampler
    )
    assert out.status == "verified"
    assert out.chosen.route == "dcat_rdf"
    assert "no_licence_metadata_on_any_route" in out.chosen.caveats


def test_fdk_pattern_missing_download_url_is_a_caveat():
    def sampler(route, config):
        return _no_download_sample()

    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [_RDF_EV], sampler=sampler
    )
    assert out.status == "verified"
    assert "feed_omits_download_url" in out.chosen.caveats


def test_json_route_gets_synthesis_caveat():
    def sampler(route, config):
        return _licensed_sample()

    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [_CKAN_EV], sampler=sampler
    )
    assert out.status == "verified"
    assert out.chosen.route == "ckan_json"
    assert "conformance_synthesised_from_json" in out.chosen.caveats


def test_known_stack_without_adapter_is_flagged_not_failed():
    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [_ODS_EV], sampler=None
    )
    assert out.status == "needs_new_adapter"
    assert out.new_stacks == ["opendatasoft"]
    assert out.chosen is None


def test_no_evidence_at_all_is_failed():
    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [], sampler=None
    )
    assert out.status == "failed"
    assert out.chosen is None


def test_empty_sample_fails_verification_and_falls_through():
    def sampler(route, config):
        if route == "dcat_rdf":
            return []  # feed answers the probe but yields nothing
        return _licensed_sample()

    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [_RDF_EV, _CKAN_EV],
        sampler=sampler,
    )
    assert out.status == "verified"
    assert out.chosen.route == "ckan_json"
    assert any(r.route == "dcat_rdf" for r in out.rejected)


def test_class_as_predicate_feed_is_diagnosed():
    # The data.gov.cy producer bug: datasets point at distributions with
    # the CLASS name (dcat:Distribution) as the predicate, so the
    # normaliser sees none. The rejection must name the malformation.
    from rdflib import Graph

    ttl = """
    @prefix dcat: <http://www.w3.org/ns/dcat#> .
    <https://p.example/ds/1> a dcat:Dataset ;
        dcat:Distribution <https://p.example/res/1> .
    """

    def sampler(route, config):
        g = Graph()
        g.parse(data=ttl, format="turtle")
        return [_ds() for _ in range(3)] and [
            HarvestedDataset(identifier="d", graph=g) for _ in range(3)
        ]

    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [_RDF_EV], sampler=sampler
    )
    assert out.status == "failed"
    reason = " ".join(r.reason for r in out.rejected)
    assert "dcat:Distribution used as a predicate" in reason


def test_sample_without_distributions_is_rejected():
    def sampler(route, config):
        return [_ds(licences=["cc-by"]) for _ in range(5)]

    out = choose_and_verify(
        "XX", "Testland", "https://p.example", [_RDF_EV], sampler=sampler
    )
    assert out.status == "failed"
    assert any("no distributions" in r.reason for r in out.rejected)
