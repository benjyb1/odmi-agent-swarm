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

See `data/catalogue/portals/<CC>.json` for verified endpoints. Summary:

| CC | Route | Conformance (Q16-18) source |
|---|---|---|
| FR | DCAT-AP RDF (udata `catalog.ttl`) | native RDF |
| DE | DCAT-AP RDF (CKAN `catalog.ttl`) | native RDF |
| RO | DCAT-AP RDF (CKAN `catalog.xml`) | native RDF (host availability permitting) |
| HU | DCAT-AP RDF (CKAN `catalog.xml`) | native RDF |
| NL | CKAN JSON (no national RDF) | DCAT-AP RDF synthesised from JSON |
| EE | custom JSON (no national RDF) | DCAT-AP RDF synthesised from JSON |

For NL and EE the conformance check runs the same SEMIC shapes over triples we
build from the JSON. This can only test fields the JSON exposes, so a low NL/EE
conformance figure may reflect our mapping rather than the portal. This caveat is
recorded with every NL/EE conformance result.
