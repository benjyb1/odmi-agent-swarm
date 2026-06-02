"""Tests for the DCAT-AP conformance helpers (Q16/Q17/Q18, D30).

Hand-built tiny graphs through pyshacl and the predicate-usage checks. No
network: validation uses the vendored shapes with imports disabled.
"""

from __future__ import annotations

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from agents.tools.answer_shapes import QuestionShape
from agents.tools.catalogue import metrics, shacl
from agents.tools.catalogue.model import HarvestedDataset

DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")

PCT_BANDS = (">90%", "71-90%", "51-70%", "31-50%", "10-30%", "<10%")


def _conformant_graph() -> Graph:
    """A Dataset with a Distribution that carries a mandatory accessURL."""
    g = Graph()
    ds = URIRef("https://example.org/dataset/1")
    dist = URIRef("https://example.org/dataset/1/dist/1")
    g.add((ds, RDF.type, DCAT.Dataset))
    g.add((ds, DCT.title, Literal("Title")))
    g.add((ds, DCT.description, Literal("Description")))
    g.add((ds, DCAT.distribution, dist))
    g.add((dist, RDF.type, DCAT.Distribution))
    g.add((dist, DCAT.accessURL, URIRef("https://example.org/file.csv")))
    return g


def _non_conformant_graph() -> Graph:
    """A Distribution missing the mandatory dcat:accessURL (minCount 1)."""
    g = Graph()
    ds = URIRef("https://example.org/dataset/2")
    dist = URIRef("https://example.org/dataset/2/dist/1")
    g.add((ds, RDF.type, DCAT.Dataset))
    g.add((ds, DCT.title, Literal("Title")))
    g.add((ds, DCAT.distribution, dist))
    g.add((dist, RDF.type, DCAT.Distribution))
    # No dcat:accessURL -> violates the mandatory shape.
    return g


def test_mandatory_conformance_pass_and_fail():
    assert shacl.is_mandatory_conformant(_conformant_graph()) is True
    assert shacl.is_mandatory_conformant(_non_conformant_graph()) is False


def test_recommended_predicate_set_parsed():
    preds = shacl.recommended_predicates()
    # Parsed from the SEMIC recommended file; Dataset recommendeds include
    # these.
    assert DCAT.distribution in preds
    assert DCAT.keyword in preds
    assert DCT.publisher in preds


def test_uses_recommended_and_optional():
    g = _conformant_graph()
    # dcat:distribution is a recommended Dataset predicate.
    assert shacl.uses_recommended(g) is True

    opt = Graph()
    ds = URIRef("https://example.org/dataset/3")
    opt.add((ds, RDF.type, DCAT.Dataset))
    opt.add((ds, DCT.title, Literal("t")))
    opt.add((ds, DCT.identifier, Literal("ABC-123")))  # optional predicate
    assert shacl.uses_optional(opt) is True

    bare = Graph()
    ds2 = URIRef("https://example.org/dataset/4")
    bare.add((ds2, RDF.type, DCAT.Dataset))
    bare.add((ds2, DCT.title, Literal("t")))
    assert shacl.uses_optional(bare) is False


def _ds_with_graph(identifier: str, graph: Graph) -> HarvestedDataset:
    return HarvestedDataset(identifier=identifier, graph=graph)


def test_q16_metric_over_mixed_datasets():
    datasets = [
        _ds_with_graph("a", _conformant_graph()),
        _ds_with_graph("b", _conformant_graph()),
        _ds_with_graph("c", _non_conformant_graph()),
        _ds_with_graph("d", _non_conformant_graph()),
    ]
    shape = QuestionShape(question_id="Q16", shape="percentage_band", allowed_answers=PCT_BANDS)
    r = metrics.metric_q16_mandatory_conformance(datasets, shape)
    assert r.numerator == 2 and r.denominator == 4
    assert r.band_label == "31-50%"


def test_q16_raises_without_graphs():
    datasets = [HarvestedDataset(identifier="x")]  # no graph
    shape = QuestionShape(question_id="Q16", shape="percentage_band", allowed_answers=PCT_BANDS)
    try:
        metrics.metric_q16_mandatory_conformance(datasets, shape)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_q16_sampling_is_disclosed():
    datasets = [_ds_with_graph(str(i), _conformant_graph()) for i in range(10)]
    shape = QuestionShape(question_id="Q16", shape="percentage_band", allowed_answers=PCT_BANDS)
    r = metrics.metric_q16_mandatory_conformance(datasets, shape, sample_size=4)
    assert r.denominator == 4
    assert "sampled 4 of 10" in r.breakdown
