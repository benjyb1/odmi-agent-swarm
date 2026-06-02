"""Offline tests for the dcat_rdf adapter, Estonia adapter, and JSON->RDF
graph synthesis (catalogue tool, D30)."""

from __future__ import annotations

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
