"""Offline tests for the dcat_rdf adapter, Estonia adapter, and JSON->RDF
graph synthesis (catalogue tool, D30)."""

from __future__ import annotations

import hashlib

import pytest
from rdflib import Graph

from agents.tools.answer_shapes import QuestionShape
from agents.tools.catalogue import metrics, shacl, synthesise
from agents.tools.catalogue.adapters import dcat_rdf, estonia_json
from agents.tools.catalogue.model import Distribution, HarvestedDataset

PCT_BANDS = (">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%")

_TURTLE_PAGE = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .

<https://data.gouv.fr/dataset/a> a dcat:Dataset ;
    dct:title "Dataset A" ;
    dct:description "First dataset" ;
    dct:license <https://www.etalab.gouv.fr/licence-ouverte-open-licence> ;
    dcat:keyword "transport" ;
    dcat:distribution <https://data.gouv.fr/dataset/a/dist/1> .

<https://data.gouv.fr/dataset/a/dist/1> a dcat:Distribution ;
    dct:format <http://publications.europa.eu/resource/authority/file-type/CSV> ;
    dcat:accessURL <https://data.gouv.fr/files/a.csv> ;
    dcat:downloadURL <https://data.gouv.fr/files/a.csv> .

<https://data.gouv.fr/dataset/b> a dcat:Dataset ;
    dct:title "Dataset B" ;
    dcat:distribution <https://data.gouv.fr/dataset/b/dist/1> .

<https://data.gouv.fr/dataset/b/dist/1> a dcat:Distribution ;
    dct:format "PDF" .
"""


def test_dcat_rdf_split_into_datasets():
    datasets = dcat_rdf.normalise_page(_TURTLE_PAGE.encode("utf-8"))
    by_id = {d.identifier: d for d in datasets}
    assert set(by_id) == {
        "https://data.gouv.fr/dataset/a",
        "https://data.gouv.fr/dataset/b",
    }

    a = by_id["https://data.gouv.fr/dataset/a"]
    assert a.dataset_licences == ["https://www.etalab.gouv.fr/licence-ouverte-open-licence"]
    assert len(a.distributions) == 1
    dist = a.distributions[0]
    assert dist.fmt == "http://publications.europa.eu/resource/authority/file-type/CSV"
    assert dist.access_url == "https://data.gouv.fr/files/a.csv"
    assert dist.download_url == "https://data.gouv.fr/files/a.csv"
    assert a.graph is not None and shacl.has_dataset_node(a.graph)

    # Bounded description must not bleed dataset B into A's graph.
    assert "dataset/b" not in a.graph.serialize(format="turtle")


def test_dcat_rdf_presence_metrics_over_split():
    datasets = dcat_rdf.normalise_page(_TURTLE_PAGE.encode("utf-8"))
    shape = QuestionShape(question_id="Q12", shape="percentage_band", allowed_answers=PCT_BANDS)
    q12 = metrics.metric_q12_licence_presence(datasets, shape)
    assert q12.numerator == 1 and q12.denominator == 2   # only A has a licence

    q27 = metrics.metric_q27_open_format(
        datasets, QuestionShape("Q27", "percentage_band", PCT_BANDS)
    )
    assert q27.numerator == 1 and q27.denominator == 2   # A has CSV; B only PDF


def test_dcat_rdf_conformance_runs_on_real_graph():
    datasets = dcat_rdf.normalise_page(_TURTLE_PAGE.encode("utf-8"))
    shape = QuestionShape("Q16", "percentage_band", PCT_BANDS)
    # A has a distribution with accessURL (conformant); B's distribution
    # lacks accessURL (violates mandatory minCount).
    r = metrics.metric_q16_mandatory_conformance(datasets, shape)
    assert r.denominator == 2
    assert r.numerator == 1


# Turtle page with a blank node, the classic source of non-deterministic
# serialisation. Harvesting it twice must yield the same content hash.
_TURTLE_WITH_BNODE = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .

<https://data.gouv.fr/dataset/x> a dcat:Dataset ;
    dct:title "X" ;
    dct:publisher [ dct:title "Some Agency" ] ;
    dcat:distribution [ a dcat:Distribution ;
        dct:format <http://publications.europa.eu/resource/authority/file-type/CSV> ;
        dcat:accessURL <https://data.gouv.fr/files/x.csv> ] .
"""


def _portal_config_for_ttl():
    from agents.tools.catalogue.registry import PortalConfig

    return PortalConfig(
        country_code="ZZ",
        country_name="Testland",
        portal_base="https://example.test",
        stack="dcat",
        harvest_route="dcat_rdf",
        pagination="hydra",
        page_size=100,
        request_delay_s=0.0,
        licence_field="dct:license",
        dcat_catalog_url="https://example.test/catalog.ttl?page={page}&size={page_size}",
    )


def _harvest_content_hash(raw_page: bytes) -> str:
    """Run the dcat_rdf harvest over a fixed page and hash the sink payloads
    exactly as harvest.harvest_country does (sha256 over the raw page bytes)."""
    config = _portal_config_for_ttl()
    hasher = hashlib.sha256()
    calls = {"n": 0}

    def _fetcher(url: str, **_kw) -> bytes:
        # Absorbs the adapter's timeout_s kwarg (see BytesFetcher).
        # First page returns the fixture; subsequent pages are empty so the
        # Hydra loop terminates.
        calls["n"] += 1
        return raw_page if calls["n"] == 1 else b""

    def _sink(idx: int, payload: bytes) -> None:
        hasher.update(payload)

    list(dcat_rdf.harvest(config, fetcher=_fetcher, on_raw_page=_sink))
    return hasher.hexdigest()


# Same triples as _TURTLE_WITH_BNODE but with explicitly-labelled blank
# nodes under different names. rdflib's Turtle writer renumbers blank nodes
# per run, so hashing its raw output is not reproducible across harvests
# that see logically-identical graphs with different bnode labels. The
# canonical serialisation must hash these two inputs identically.
_TURTLE_WITH_BNODE_RELABELLED = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .

<https://data.gouv.fr/dataset/x> a dcat:Dataset ;
    dct:title "X" ;
    dct:publisher _:pub99 ;
    dcat:distribution _:dist42 .

_:pub99 dct:title "Some Agency" .

_:dist42 a dcat:Distribution ;
    dct:format <http://publications.europa.eu/resource/authority/file-type/CSV> ;
    dcat:accessURL <https://data.gouv.fr/files/x.csv> .
"""


def test_dcat_rdf_content_hash_is_reproducible():
    raw = _TURTLE_WITH_BNODE.encode("utf-8")
    h1 = _harvest_content_hash(raw)
    h2 = _harvest_content_hash(raw)
    assert h1 == h2
    assert h1  # non-empty


def test_dcat_rdf_content_hash_invariant_to_blank_node_labels():
    """Two byte-different inputs that carry the same triples (only blank-node
    labels differ) must produce the same content hash. The plain Turtle
    serialisation does not guarantee this; the canonical one does."""
    h1 = _harvest_content_hash(_TURTLE_WITH_BNODE.encode("utf-8"))
    h2 = _harvest_content_hash(_TURTLE_WITH_BNODE_RELABELLED.encode("utf-8"))
    assert h1 == h2


def test_dcat_rdf_cached_payload_is_canonical_not_turtle():
    """The page cached for hashing must be the canonical, sorted N-Triples
    form, not rdflib's Turtle writer output. rdflib Turtle is not a stable
    contract across versions/runs (blank-node ids, triple order), so the
    snapshot hash would not reproduce. Pin the canonical bytes here."""
    from rdflib import Graph
    from rdflib.compare import to_canonical_graph

    config = _portal_config_for_ttl()
    raw = _TURTLE_WITH_BNODE.encode("utf-8")
    calls = {"n": 0}
    captured: list[bytes] = []

    def _fetcher(url: str, **_kw) -> bytes:
        # Absorbs the adapter's timeout_s kwarg (see BytesFetcher).
        calls["n"] += 1
        return raw if calls["n"] == 1 else b""

    def _sink(idx: int, payload: bytes) -> None:
        captured.append(payload)

    list(dcat_rdf.harvest(config, fetcher=_fetcher, on_raw_page=_sink))
    assert len(captured) == 1

    # Expected canonical form: sorted N-Triples of the canonicalised graph.
    page = Graph()
    page.parse(data=raw, format="turtle")
    canon = to_canonical_graph(page)
    expected_lines = sorted(
        line for line in canon.serialize(format="nt").splitlines() if line.strip()
    )
    expected = ("\n".join(expected_lines) + "\n").encode("utf-8")
    assert captured[0] == expected

    # And it must still replay as Turtle (N-Triples is valid Turtle).
    replayed = dcat_rdf.normalise_page(captured[0])
    assert any(d.identifier == "https://data.gouv.fr/dataset/x" for d in replayed)


# One malformed IRI (a space in the path) on an otherwise sound page. rdflib
# parses it but refuses to serialise it, so before the drop guard the whole
# page raised and every dataset on it was lost. That is what truncated the
# Croatian harvest at 1,400 of 3,867 datasets.
_TURTLE_WITH_MALFORMED_IRI = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .

<https://portal.hr/ds/1> a dcat:Dataset ;
    dct:title "Sound" ;
    dcat:distribution <https://portal.hr/files/ok.csv> .

<https://portal.hr/ds/2> a dcat:Dataset ;
    dct:title "Carries a malformed distribution IRI" ;
    dcat:distribution <https://portal.hr/files/bad file.csv> .
"""


def test_dcat_rdf_malformed_iri_drops_the_triple_not_the_page():
    page = Graph()
    page.parse(data=_TURTLE_WITH_MALFORMED_IRI, format="turtle")
    # Precondition: plain serialisation of this page raises. Without the
    # guard the harvest loses the page.
    with pytest.raises(Exception):
        page.serialize(format="nt")

    payload = dcat_rdf._canonical_turtle_bytes(page)
    replayed = dcat_rdf.normalise_page(payload)
    ids = {d.identifier for d in replayed}
    assert ids == {"https://portal.hr/ds/1", "https://portal.hr/ds/2"}
    assert b"bad file.csv" not in payload


def test_dcat_rdf_harvest_survives_a_page_with_a_malformed_iri():
    config = _portal_config_for_ttl()
    calls = {"n": 0}
    captured: list[bytes] = []

    def _fetcher(url: str, **_kw) -> bytes:
        calls["n"] += 1
        return _TURTLE_WITH_MALFORMED_IRI.encode("utf-8") if calls["n"] == 1 else b""

    datasets = list(
        dcat_rdf.harvest(
            config, fetcher=_fetcher, on_raw_page=lambda i, p: captured.append(p)
        )
    )
    assert len(datasets) == 2
    assert len(captured) == 1


def test_dcat_rdf_fetcher_is_called_with_the_page_timeout():
    """The retry path passes `timeout_s`; an injected fetcher must receive it.
    Pins the contract that `BytesFetcher` documents."""
    config = _portal_config_for_ttl()
    seen: list[float] = []

    def _fetcher(url: str, *, timeout_s: float = 0.0, **_kw) -> bytes:
        seen.append(timeout_s)
        return _TURTLE_PAGE.encode("utf-8") if len(seen) == 1 else b""

    list(dcat_rdf.harvest(config, fetcher=_fetcher))
    assert seen and all(t == dcat_rdf._PAGE_FETCH_TIMEOUT_S for t in seen)


def test_estonia_normalise_detail():
    detail = {
        "id": "abc",
        "title": "Liiklus",
        "titleEn": "Traffic",
        "distributions": [
            {"license": "CC_BY_4.0", "format": "CSV", "accessUrls": ["https://x/ee.csv"]},
            {"license": "", "format": "JSON", "accessUrls": ["https://x/ee.json"]},
        ],
    }
    ds = estonia_json.normalise_estonia_detail(detail)
    assert ds.identifier == "abc"
    assert ds.extras["title"] == "Traffic"
    assert len(ds.distributions) == 2
    assert ds.distributions[0].licence == "CC_BY_4.0"
    assert ds.distributions[0].access_url == "https://x/ee.csv"
    # Distinct licence + open: CC_BY_4.0 is open; empty is unlicensed.
    assert "cc-by-4.0" in {
        __import__("agents.tools.catalogue.licences", fromlist=["canonical_licence"]).canonical_licence(l)
        for l in ds.all_licences()
    }


def test_synthesise_graph_enables_conformance_for_json_route():
    ds = HarvestedDataset(
        identifier="https://data.overheid.nl/dataset/x",
        dataset_licences=["http://creativecommons.org/licenses/by/4.0/deed.nl"],
        distributions=[Distribution(fmt="CSV", access_url="https://x/a.csv")],
        extras={"title": "T", "description": "D", "keywords": ["k"]},
    )
    synthesise.attach_graphs([ds])
    assert ds.graph is not None
    assert shacl.has_dataset_node(ds.graph)
    # accessURL present -> mandatory conformant; keyword -> recommended.
    assert shacl.is_mandatory_conformant(ds.graph) is True
    assert shacl.uses_recommended(ds.graph) is True
