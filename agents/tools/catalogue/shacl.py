"""DCAT-AP conformance helpers (Q16/Q17/Q18), built on the vendored SEMIC
SHACL shapes (see `shapes/PROVENANCE.md`).

- Q16 (mandatory-class conformance) runs pyshacl over a dataset's bounded
  description against the official mandatory shapes: conformant when there
  are zero violations.
- Q17 (recommended-class usage) and Q18 (optional-class usage) are field
  counting: does the dataset graph exercise at least one recommended /
  optional DCAT-AP predicate. The recommended predicate set is parsed from
  the vendored recommended shapes file; the optional set is the documented
  DCAT-AP 2.1.1 optional-property list below.

pyshacl is imported lazily so the rest of the catalogue tool runs without
it. Validation uses no inference and no remote imports, so it never makes
a network call.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF

if TYPE_CHECKING:  # pragma: no cover
    pass

_SHAPES_DIR = Path(__file__).resolve().parent / "shapes"
_MANDATORY_FILE = _SHAPES_DIR / "dcat-ap_2.1.1_shacl_shapes.ttl"
_RECOMMENDED_FILE = _SHAPES_DIR / "dcat-ap_2.1.1_shacl_shapes_recommended.ttl"

SH = Namespace("http://www.w3.org/ns/shacl#")
DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
ADMS = Namespace("http://www.w3.org/ns/adms#")
DCATAP = Namespace("http://data.europa.eu/r5r/")
OWL = Namespace("http://www.w3.org/2002/07/owl#")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
PROV = Namespace("http://www.w3.org/ns/prov#")
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
SPDX = Namespace("http://spdx.org/rdf/terms#")
DCAT_DATASET = DCAT.Dataset
DCAT_DISTRIBUTION = DCAT.Distribution

# DCAT-AP 2.1.1 optional properties for Dataset and Distribution (from the
# specification's conformance tables). Used for Q18 (optional-class usage).
OPTIONAL_PREDICATES: frozenset[URIRef] = frozenset(
    {
        # Dataset optional
        DCT.accessRights,
        DCT.conformsTo,
        DCAT.landingPage,
        DCT.identifier,
        ADMS.identifier,
        DCT.provenance,
        DCT.relation,
        DCT.source,
        DCT.type,
        OWL.versionInfo,
        ADMS.versionNotes,
        PROV.wasGeneratedBy,
        DCT.accrualPeriodicity,
        DCT.hasVersion,
        DCT.isVersionOf,
        FOAF.page,
        DCAT.qualifiedRelation,
        ADMS.sample,
        DCAT.temporalResolution,
        DCAT.spatialResolutionInMeters,
        # Distribution optional
        DCT.rights,
        DCAT.byteSize,
        SPDX.checksum,
        DCAT.downloadURL,
        DCAT.mediaType,
        DCAT.packageFormat,
        DCAT.compressFormat,
        ADMS.status,
        DCAT.accessService,
        ODRL.hasPolicy,
        DCAT.temporalResolution,
    }
)


@lru_cache(maxsize=1)
def mandatory_shapes_graph() -> Graph:
    g = Graph()
    g.parse(_MANDATORY_FILE, format="turtle")
    return g


@lru_cache(maxsize=1)
def recommended_predicates() -> frozenset[URIRef]:
    """Recommended Dataset/Distribution predicates, parsed from the SEMIC
    recommended shapes file. Drives Q17."""
    g = Graph()
    g.parse(_RECOMMENDED_FILE, format="turtle")
    preds: set[URIRef] = set()
    for target in (DCAT_DATASET, DCAT_DISTRIBUTION):
        for shape in g.subjects(SH.targetClass, target):
            for pshape in g.objects(shape, SH.property):
                for path in g.objects(pshape, SH.path):
                    if isinstance(path, URIRef):
                        preds.add(path)
    return frozenset(preds)


def is_mandatory_conformant(graph: Graph) -> bool:
    """True if a dataset's bounded description has zero SHACL violations
    against the official mandatory shapes."""
    from pyshacl import validate  # lazy

    conforms, _results_graph, _text = validate(
        data_graph=graph,
        shacl_graph=mandatory_shapes_graph(),
        inference="none",
        advanced=True,
        meta_shacl=False,
        do_owl_imports=False,
        allow_warnings=True,  # only Violations count against conformance
    )
    return bool(conforms)


def graph_predicates(graph: Graph) -> set[URIRef]:
    """The set of predicates used on the dataset and its distributions."""
    return {p for p in graph.predicates() if isinstance(p, URIRef)}


def uses_recommended(graph: Graph) -> bool:
    return bool(graph_predicates(graph) & recommended_predicates())


def uses_optional(graph: Graph) -> bool:
    return bool(graph_predicates(graph) & OPTIONAL_PREDICATES)


def has_dataset_node(graph: Graph) -> bool:
    return (None, RDF.type, DCAT_DATASET) in graph
