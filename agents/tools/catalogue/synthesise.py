"""Synthesise a DCAT-AP graph from a normalised dataset (NL, EE).

NL (data.overheid.nl) and EE (andmed.eesti.ee) expose no national DCAT-AP
RDF feed, only JSON. The conformance metrics (Q16/Q17/Q18) need an RDF
graph, so we build one from the harvested JSON fields. This can only carry
what the JSON exposes, so a low NL/EE conformance figure may reflect this
mapping rather than the portal. That caveat is recorded with every NL/EE
conformance result (see docs/CATALOGUE_METRICS.md).
"""

from __future__ import annotations

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF

from agents.tools.catalogue.model import HarvestedDataset

_DCAT = "http://www.w3.org/ns/dcat#"
_DCT = "http://purl.org/dc/terms/"

DCAT_DATASET = URIRef(_DCAT + "Dataset")
DCAT_DISTRIBUTION_CLASS = URIRef(_DCAT + "Distribution")
DCAT_DISTRIBUTION = URIRef(_DCAT + "distribution")
DCAT_ACCESS_URL = URIRef(_DCAT + "accessURL")
DCAT_DOWNLOAD_URL = URIRef(_DCAT + "downloadURL")
DCAT_MEDIATYPE = URIRef(_DCAT + "mediaType")
DCAT_KEYWORD = URIRef(_DCAT + "keyword")
DCAT_THEME = URIRef(_DCAT + "theme")
DCT_TITLE = URIRef(_DCT + "title")
DCT_DESCRIPTION = URIRef(_DCT + "description")
DCT_LICENSE = URIRef(_DCT + "license")
DCT_FORMAT = URIRef(_DCT + "format")
DCT_PUBLISHER = URIRef(_DCT + "publisher")
DCT_IDENTIFIER = URIRef(_DCT + "identifier")
DCT_ISSUED = URIRef(_DCT + "issued")
DCT_MODIFIED = URIRef(_DCT + "modified")


def _node(value: str):
    """A URIRef if the value looks like a URL, else a Literal."""
    return URIRef(value) if value.startswith("http") else Literal(value)


def build_graph(dataset: HarvestedDataset) -> Graph:
    """Map a normalised dataset onto a DCAT-AP graph for conformance."""
    g = Graph()
    ds = URIRef(dataset.identifier) if dataset.identifier.startswith("http") else BNode()
    g.add((ds, RDF.type, DCAT_DATASET))

    ex = dataset.extras or {}
    if ex.get("title"):
        g.add((ds, DCT_TITLE, Literal(ex["title"])))
    if ex.get("description"):
        g.add((ds, DCT_DESCRIPTION, Literal(ex["description"])))
    if dataset.identifier_uri:
        g.add((ds, DCT_IDENTIFIER, Literal(dataset.identifier_uri)))
    if ex.get("publisher"):
        g.add((ds, DCT_PUBLISHER, _node(str(ex["publisher"]))))
    if ex.get("issued"):
        g.add((ds, DCT_ISSUED, Literal(ex["issued"])))
    if ex.get("modified"):
        g.add((ds, DCT_MODIFIED, Literal(ex["modified"])))
    for kw in ex.get("keywords") or []:
        g.add((ds, DCAT_KEYWORD, Literal(kw)))
    for theme in ex.get("themes") or []:
        g.add((ds, DCAT_THEME, _node(str(theme))))

    for lic in dataset.dataset_licences:
        g.add((ds, DCT_LICENSE, _node(lic)))

    for dist in dataset.distributions:
        dn = BNode()
        g.add((ds, DCAT_DISTRIBUTION, dn))
        g.add((dn, RDF.type, DCAT_DISTRIBUTION_CLASS))
        if dist.access_url:
            g.add((dn, DCAT_ACCESS_URL, _node(dist.access_url)))
        if dist.download_url:
            g.add((dn, DCAT_DOWNLOAD_URL, _node(dist.download_url)))
        if dist.fmt:
            g.add((dn, DCT_FORMAT, _node(dist.fmt)))
        if dist.media_type:
            g.add((dn, DCAT_MEDIATYPE, _node(dist.media_type)))
        if dist.licence:
            g.add((dn, DCT_LICENSE, _node(dist.licence)))

    return g


def attach_graphs(datasets: list[HarvestedDataset]) -> list[HarvestedDataset]:
    """Populate `.graph` on datasets that lack one, in place."""
    for d in datasets:
        if d.graph is None:
            d.graph = build_graph(d)
    return datasets
