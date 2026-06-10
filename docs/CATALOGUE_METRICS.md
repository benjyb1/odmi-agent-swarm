# Catalogue metrics mapping

How the deterministic catalogue-metrics tool (`agents/tools/catalogue/`, SPEC D30)
turns each ODMI band/count question into a computed statistic over a national
portal's harvested metadata. One named metric function per question_id, documented
here against its definition and band rule.

This document is the audit surface for the metric definitions. The tool never reads
`ground_truth`, and ODMI's own answer never feeds a computation. Bands are assigned
from the question's `response_scoring` / `allowed_answers` (already loaded in the
`questions` table), not from any external answer.

## Scope

The shape filter `answer_shape IN ('percentage_band','count_band')` returns 14
questions. Of these:

- 9 are computed by v1 (table below).
- 4 are flagged ambiguous: a definition is proposed but not built until signed off.
- 1 is excluded: P29 asks about annual events, not catalogue metadata.
- Q2 is excluded: it asks what share of metadata is harvested automatically rather
  than edited by hand. That is a workflow self-report, not a property of the
  catalogue records, so it is not catalogue-derivable.

## In scope (v1)

All percentages are computed from the harvested metadata of the national portal
only. The denominator is stated per metric because some questions are about
datasets and some about distributions.

| Q | Dimension | Shape | Metric | Numerator | Denominator |
|---|---|---|---|---|---|
| Q12 | Quality | percentage_band | Datasets carrying licensing information | datasets with at least one licence present (dataset-level or any distribution licence), excluding the "no licence" sentinels | all datasets |
| Q13 | Quality | count_band | Distinct licences used on the portal | count of distinct normalised licence identifiers across the catalogue | n/a (count, not a ratio) |
| Q16 | Quality | percentage_band | Metadata DCAT-AP compliant, mandatory classes | datasets whose graph passes the SEMIC DCAT-AP mandatory-class SHACL shapes | all datasets |
| Q17 | Quality | percentage_band | Metadata using DCAT-AP recommended classes | datasets exercising at least the recommended-class/property set | all datasets |
| Q18 | Quality | percentage_band | Metadata using DCAT-AP optional classes | datasets exercising at least one optional-class/property | all datasets |
| Q21 | Quality | percentage_band | Datasets whose metadata gives a download-URL | datasets with at least one distribution carrying `dcat:downloadURL` | datasets with at least one distribution |
| Q22 | Quality | percentage_band | Datasets whose metadata gives an access-URL | datasets with at least one distribution carrying `dcat:accessURL` | datasets with at least one distribution |
| Q25 | Quality | percentage_band | Datasets under an open licence | datasets whose licence is in the open-licence set | all datasets |
| Q27 | Quality | percentage_band | Datasets in an open and machine-readable format | datasets with at least one distribution whose format/media type is in the open and machine-readable list | all datasets |

### Band assignment

1. Compute the raw value (a percentage in [0,100], or an integer count for Q13).
2. Read the question's `allowed_answers` and `response_scoring` from the DB.
3. Map the raw value to the band whose range contains it. The percentage bands are
   half-open ranges read straight off the labels, for example `>90%` is
   `(90, 100]`, `71-90%` is `(70, 90]`, `<10%` is `[0, 10)`. Q13's count bands are
   `1-4`, `5-10`, `>10` (and `i don't know`, never emitted by the tool).
4. Validate the chosen label against the allowed set with
   `agents/tools/answer_shapes.py:is_valid_answer`.

The two percentage band families in use:

- Q12 uses `>90% / 71-90% / 51-70% / 31-50% / 10-30% / <10%`.
- Q16-Q29 use the same six labels (different scores, same ranges).

### The "no licence" sentinels

A dataset counts as unlicensed (and is excluded from the Q12 numerator) when its
only licence value is one of the per-portal sentinels:

- udata (FR): `notspecified`, `other-at`, `other-open`, `other-pd`, or null.
- CKAN (DE/RO/HU): empty `license_id`/`license`, or `notspecified`.
- DONL (NL): `http://standaarden.overheid.nl/owms/terms/licentieonbekend`, or empty.
- Estonia: empty-string `license`.

DE carries the real licence at the distribution level; its dataset-level
`license_id` is almost always empty and is ignored.

### Reference lists

The open-licence set (Q25) and the open and machine-readable format list (Q27) are
committed as small JSON lookups under `data/catalogue/` with a provenance note.
Sources are public and not data.europa.eu:

- Open licences: SPDX identifiers plus the Open Definition conformant-licence list
  (CC-BY, CC-BY-SA, CC0/PDDL, ODbL, ODC-BY, Etalab Licence Ouverte, OGL families).
- Open and machine-readable formats: the common open structured families (CSV, JSON,
  XML, RDF/Turtle/N-Triples, GeoJSON, XLSX/ODS, GeoPackage, Parquet, and similar),
  matched against both plain format tokens and the EU file-type authority URIs that
  several portals emit.

## Flagged ambiguous (documented, not built in v1)

These are not computed until a definition is signed off, per the "do not guess"
instruction. Proposed interpretations:

| Q | Question | Proposed interpretation |
|---|---|---|
| Q26 | What percentage of licences are provided in a structured data format? | Of datasets that carry a licence, the share whose licence is expressed as a URI or a controlled code rather than free text. |
| Q28 | What percentage of datasets consistently use Uniform Resource Identifiers? | Share of datasets whose `dct:identifier` (and key references) are http(s) URIs rather than opaque local strings. |
| Q29 | What percentage of datasets link to other renowned sources (linked-data fashion)? | Share of datasets carrying at least one outward link via `dct:relation`, `rdfs:seeAlso`, `owl:sameAs`, or `dcat:qualifiedRelation`. |

## Excluded

| Q | Reason |
|---|---|
| P29 | Annual national/regional/local events to promote open data. Not a property of catalogue metadata. Stays on the web-search path. |
| Q2 | Share of metadata harvested automatically vs edited by hand. A workflow self-report, not derivable from the catalogue records. |

## Per-country harvest routes

See `data/catalogue/portals/<CC>.json` for verified endpoints. The six
rows above the line are hand-authored (D30); the rest were emitted by the
portal-discovery tool (D46, `docs/PORTAL_DISCOVERY.md`), with the caveats
auto-detected from a verification sample. Summary:

| CC | Route | Conformance (Q16-18) source |
|---|---|---|
| FR | DCAT-AP RDF (udata `catalog.ttl`) | native RDF |
| DE | DCAT-AP RDF (CKAN `catalog.ttl`) | native RDF |
| RO | DCAT-AP RDF (CKAN `catalog.xml`) | native RDF (host availability permitting) |
| HU | CKAN JSON (RDF feed omits dct:license) | DCAT-AP RDF synthesised from JSON |
| NL | CKAN JSON (no national RDF) | DCAT-AP RDF synthesised from JSON |
| EE | custom JSON (no national RDF) | DCAT-AP RDF synthesised from JSON |
| AT | piveau hub-search JSON | DCAT-AP RDF synthesised from JSON |
| CH | DCAT-AP RDF (`catalog.ttl`) | native RDF |
| CZ | SPARQL (paged CONSTRUCT) | native RDF (dataset + distribution levels) |
| EL | DCAT-AP RDF (`catalog.ttl`) | native RDF |
| FI | CKAN JSON | DCAT-AP RDF synthesised from JSON |
| HR | SPARQL (paged CONSTRUCT; no licence metadata) | native RDF (dataset + distribution levels) |
| IE | CKAN JSON (RDF feed omits dct:license, the HU pattern) | DCAT-AP RDF synthesised from JSON |
| LU | DCAT-AP RDF (udata site catalogue, the FR pattern) | native RDF |
| LV | CKAN JSON | DCAT-AP RDF synthesised from JSON |
| ME | CKAN JSON (RDF feed omits dct:license) | DCAT-AP RDF synthesised from JSON |
| PT | DCAT-AP RDF (udata site catalogue) | native RDF |
| RS | uData JSON (RDF feed omits dct:license) | DCAT-AP RDF synthesised from JSON |
| SE | SPARQL on admin.dataportal.se (no downloadURL in graph) | native RDF (dataset + distribution levels) |
| SI | CKAN JSON (no licence metadata on any route) | DCAT-AP RDF synthesised from JSON |
| UA | CKAN JSON (RDF feed omits dct:license) | DCAT-AP RDF synthesised from JSON |

The SPARQL route pulls dataset and distribution triples only (the paged
CONSTRUCT does not follow publisher or contact sub-nodes), so Q16/Q17/Q18
on CZ/HR/SE read those two levels of the portal's own graph; treat
recommended-class usage that depends on deeper nodes as a lower bound.

## Per-route reliability and caveats

Not every metric is equally reliable on every route. The route is chosen per
country to maximise fidelity, and the following caveats are recorded with the
results.

- **RDF routes (FR, DE, RO)** are authoritative for all nine metrics: the feed
  carries typed licences, the access/download-URL distinction, and EU file-type
  IRIs, so the SHACL conformance runs against the portal's own triples.
- **HU** publishes a DCAT-AP RDF feed that carries no `dct:license` at all
  (verified 2026-06-02), so licence metrics (Q12/Q13/Q25) would read ~0% via
  RDF. HU therefore harvests via CKAN JSON, which exposes `license_id`.
- **Synthesised routes (HU, NL, EE)** build the conformance graph from JSON.
  Two mapping rules matter: dates are emitted as `xsd:date`/`xsd:dateTime`
  (an untyped literal is a mandatory violation), and a CKAN resource URL is
  mapped to both `dcat:accessURL` and `dcat:downloadURL`, mirroring
  ckanext-dcat. Because the synthesised graph contains only the fields we map,
  Q16 conformance on these routes tends to read high (the shapes' only hard
  mandatory constraints, a typed date and a distribution access URL, are
  satisfied by construction). Treat synthesised-route Q16 as an upper bound,
  not a like-for-like with the RDF routes.
- **Q21 (download-URL)** is authoritative only on the RDF routes, where the
  portal distinguishes download from access. On CKAN JSON it follows the
  ckanext-dcat convention (resource URL = both), so it tracks Q22.
