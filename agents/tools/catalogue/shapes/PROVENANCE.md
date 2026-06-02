# Vendored DCAT-AP SHACL shapes

Source: the official SEMIC (SEMICeu) DCAT-AP repository, release 2.1.1.

- `dcat-ap_2.1.1_shacl_shapes.ttl` — the mandatory constraints (all
  `sh:severity sh:Violation`). Used for Q16 (mandatory-class conformance):
  a dataset is mandatory-conformant when pyshacl reports zero violations
  over its bounded description.
- `dcat-ap_2.1.1_shacl_shapes_recommended.ttl` — the recommended
  constraints. We do not validate against these; we parse them to derive
  the recommended Dataset/Distribution predicate set for Q17 (recommended-
  class usage), which the plan computes by field counting rather than
  pass/fail validation.

Fetched 2026-06-02 from:
- https://raw.githubusercontent.com/SEMICeu/DCAT-AP/master/releases/2.1.1/dcat-ap_2.1.1_shacl_shapes.ttl
- https://raw.githubusercontent.com/SEMICeu/DCAT-AP/master/releases/2.1.1/dcat-ap_2.1.1_shacl_shapes_recommended.ttl

These are specification artefacts published by SEMIC on GitHub. They are
not data.europa.eu and carry no ODMI answer content; the `data.europa.eu`
URIs inside them are the r5r vocabulary namespace, never fetched.

Caveat on per-dataset validation. The MQA validates a whole catalogue
graph where referenced nodes (LicenseDocument, Location, ConceptScheme)
are present. We validate each dataset's bounded description (the dataset
plus its distributions and immediate referenced nodes). Class shapes for
referenced external nodes only fire when those nodes are present in the
harvested metadata, which matches how the portal actually publishes them.
This is an independent recompute, not a reproduction of the MQA pipeline.
