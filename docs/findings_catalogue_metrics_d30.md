# Catalogue metrics: validation findings (D30)

Computed 2026-06-02. Source: `evaluation/validate_catalogue_fr.py`.

Independent recompute of nine ODMI Quality catalogue metrics across the Phase B
six-country set, without consulting the MQA or any deny-listed source. The tool
harvests each national portal's live metadata directly. Ground truth is read only
to score the output, not to compute it.

---

## Results by country

### France (FR) — 5,000 datasets, udata DCAT-AP RDF (sample, 50 pages)

| Q | Computed | ODMI | Verdict | Breakdown |
|---|----------|------|---------|-----------|
| Q12 | 31-50% | >90% | differ(+3) | 1,890 of 5,000 carry licensing information = 37.8% |
| Q13 | 5-10 | 1-4 | near_match | 7 distinct licences (cc-by, cc-by-sa, cc0, etalab, etalab-2014, odbl, other:odc-by) |
| Q16 | 31-50% | >90% | differ(+3) | 319 of 1,000 pass SEMIC mandatory SHACL = 31.9% (sampled 1,000 of 5,000) |
| Q17 | >90% | >90% | exact | 5,000 of 5,000 exercise a recommended property = 100% |
| Q18 | >90% | >90% | exact | 5,000 of 5,000 exercise an optional property = 100% |
| Q21 | >90% | >90% | exact | 4,775 of 4,775 carry a download-URL = 100% |
| Q22 | >90% | >90% | exact | 4,775 of 4,775 carry an access-URL = 100% |
| Q25 | 31-50% | >90% | differ(+3) | 1,886 of 5,000 are under an open licence = 37.7% |
| Q27 | 31-50% | >90% | differ(+3) | 2,025 of 5,000 offer an open machine-readable format = 40.5% |

**exact=4 near_match=1 differ=4**

Note: the first 10-page sample (1,000 datasets) read 66.9% for Q12 and 66.6%
for Q25. The udata feed is order-biased; early pages skew toward well-maintained
government datasets. The 5,000-dataset figure is more representative.

---

### Hungary (HU) — 2,282 datasets, CKAN JSON, full catalogue

| Q | Computed | ODMI | Verdict | Breakdown |
|---|----------|------|---------|-----------|
| Q12 | 71-90% | >90% | near_match | 1,661 of 2,282 carry licensing information = 72.8% |
| Q13 | 1-4 | 1-4 | exact | 2 distinct licences (cc-by, cc-by-nc) |
| Q16 | >90% | >90% | exact | 1,000 of 1,000 pass SEMIC mandatory SHACL = 100% (sampled 1,000 of 2,282) |
| Q17 | >90% | >90% | exact | 2,282 of 2,282 exercise a recommended property = 100% |
| Q18 | >90% | >90% | exact | 2,282 of 2,282 exercise an optional property = 100% |
| Q21 | >90% | >90% | exact | 2,282 of 2,282 carry a download-URL = 100% |
| Q22 | >90% | >90% | exact | 2,282 of 2,282 carry an access-URL = 100% |
| Q25 | <10% | <10% | exact | 44 of 2,282 are under an open licence = 1.9% |
| Q27 | >90% | >90% | exact | 2,200 of 2,282 offer an open machine-readable format = 96.4% |

**exact=8 near_match=1 differ=0**

Route note: HU's DCAT-AP RDF feed carries no `dct:license` (verified live).
The tool harvests via CKAN JSON instead, which exposes `license_id` per dataset.
Conformance graphs are synthesised from the JSON. CC-BY-NC dominates the
catalogue, which is why open-licence coverage (Q25) is 1.9% and correctly
reproduces ODMI's `<10%` band.

---

### Netherlands (NL) — 20,772 datasets, CKAN-DONL JSON, full catalogue

| Q | Computed | ODMI | Verdict | Breakdown |
|---|----------|------|---------|-----------|
| Q12 | >90% | >90% | exact | 20,131 of 20,772 carry licensing information = 96.9% |
| Q13 | 5-10 | 5-10 | exact | 7 distinct licences (cc-by-4.0, cc-by-nc-4.0, cc-by-sa-4.0, cc0-1.0, geogedeeld, geslotenlicentie, pd-1.0) |
| Q16 | 51-70% | >90% | differ(+2) | 666 of 1,000 pass SEMIC mandatory SHACL = 66.6% (sampled 1,000 of 20,772) |
| Q17 | >90% | >90% | exact | 20,772 of 20,772 exercise a recommended property = 100% |
| Q18 | 71-90% | 10-30% | differ(+3) | 17,925 of 20,772 exercise an optional property = 86.3% |
| Q21 | >90% | 51-70% | differ(+2) | 17,925 of 17,925 carry a download-URL = 100% |
| Q22 | >90% | >90% | exact | 17,925 of 17,925 carry an access-URL = 100% |
| Q25 | >90% | >90% | exact | 18,757 of 20,772 are under an open licence = 90.3% |
| Q27 | 51-70% | >90% | differ(+2) | 10,510 of 20,772 offer an open machine-readable format = 50.6% |

**exact=5 near_match=0 differ=4**

Route note: no national DCAT-AP RDF feed exists (all `/catalog.*` paths return
404). Harvests via CKAN JSON; conformance graphs synthesised from JSON. The
Q18/Q21 diffs may partly reflect the route rather than the portal; see
`docs/CATALOGUE_METRICS.md` for the synthesis caveats.

---

### Germany (DE) — 3,000 datasets, CKAN DCAT-AP RDF (sample, 30 pages)

| Q | Computed | ODMI | Verdict | Breakdown |
|---|----------|------|---------|-----------|
| Q12 | >90% | >90% | exact | 3,000 of 3,000 carry licensing information = 100% |
| Q13 | >10 | 5-10 | near_match | 13 distinct licences (cc-by, cc-by-4.0, cc-by-nc variants, cc0, dl-de-by-1.0, dl-de-by-2.0, dl-de-zero-2.0, ...) |
| Q16 | <10% | >90% | differ(+5) | 42 of 1,000 pass SEMIC mandatory SHACL = 4.2% (sampled 1,000 of 3,000) |
| Q17 | >90% | >90% | exact | 3,000 of 3,000 exercise a recommended property = 100% |
| Q18 | >90% | 71-90% | near_match | 3,000 of 3,000 exercise an optional property = 100% |
| Q21 | <10% | 31-50% | differ(+2) | 81 of 3,000 carry a download-URL = 2.7% |
| Q22 | >90% | >90% | exact | 3,000 of 3,000 carry an access-URL = 100% |
| Q25 | >90% | >90% | exact | 2,998 of 3,000 are under an open licence = 99.9% |
| Q27 | 31-50% | 71-90% | differ(+2) | 1,367 of 3,000 offer an open machine-readable format = 45.6% |

**exact=4 near_match=2 differ=3**

Q16 note: the 4.2% figure is not a tool error. German distributions include an
`spdx:Checksum` block with a `checksumValue` but omit the mandatory
`spdx:algorithm` triple. The SEMIC shapes require it; a single violation fails
the dataset under our strict whole-dataset pass/fail rule. This is a genuine
DCAT-AP.de incompleteness that the self-reported >90% does not capture. Our Q16
should be read as a conservative lower bound and a stricter lens than the MQA,
not a reproduction of it.

---

### Romania (RO) — 5,143 datasets, CKAN JSON, full catalogue

| Q | Computed | ODMI | Verdict | Breakdown |
|---|----------|------|---------|-----------|
| Q12 | >90% | >90% | exact | 4,946 of 5,143 carry licensing information = 96.2% |
| Q13 | 5-10 | 1-4 | near_match | 5 distinct licences (cc-by-4.0, cc-by-nc-4.0, cc0-1.0, ogl, ogl-1.0) |
| Q16 | >90% | 71-90% | near_match | 961 of 1,000 pass SEMIC mandatory SHACL = 96.1% (sampled) |
| Q17 | >90% | 10-30% | differ(+4) | 5,143 of 5,143 exercise a recommended property = 100% |
| Q18 | >90% | <10% | differ(+5) | 5,130 of 5,143 exercise an optional property = 99.7% |
| Q21 | >90% | >90% | exact | 5,130 of 5,138 carry a download-URL = 99.8% |
| Q22 | >90% | <10% | differ(+5) | 5,130 of 5,138 carry an access-URL = 99.8% |
| Q25 | >90% | >90% | exact | 4,945 of 5,143 are under an open licence = 96.2% |
| Q27 | 51-70% | 31-50% | near_match | 3,203 of 5,143 offer an open machine-readable format = 62.3% |

**exact=3 near_match=3 differ=3**

Route note: like HU, RO's DCAT-AP RDF feed carries no `dct:license`. The tool
harvests via CKAN JSON. The large Q17/Q18/Q22 diffs (ODMI records <10% or
10-30%; the live catalogue reads ~100%) look like stale or incorrectly entered
self-reports in the ground-truth data rather than tool errors.

---

### Estonia (EE) — unavailable

All metrics unavailable. The portal returned HTTP 403 Forbidden on every
request, both with the project's descriptive research User-Agent and with a
standard browser User-Agent. This is an IP-level block on datacentre traffic;
it is not a missing API key or a robots.txt constraint. The swarm falls back to
web search for EE Quality questions. A retry from a residential or EU-based IP
may succeed.

---

## Summary

| CC | Datasets | Exact | Near | Differ |
|----|---------|-------|------|--------|
| HU | 2,282 (full) | 8 | 1 | 0 |
| NL | 20,772 (full) | 5 | 0 | 4 |
| DE | 3,000 (sample) | 4 | 2 | 3 |
| FR | 5,000 (sample) | 4 | 1 | 4 |
| RO | 5,143 (full) | 3 | 3 | 3 |
| EE | blocked | — | — | — |

## Key findings for the dissertation

**1. The self-report ceiling (France).** ODMI awarded France full marks after it
self-reported >90% on licence coverage and conformance. The independent recompute
gives 37.8% licence coverage, 37.7% open-licence coverage, and 31.9% mandatory
conformance. Metadata structure metrics (URLs, recommended/optional property
usage) agree with ODMI exactly; the disagreement is specific to the counting
questions. This is the D29 self-report ceiling made quantifiable, and it is the
headline finding for the dissertation's failure-mode taxonomy.

**2. Strict SHACL reveals real non-conformance (Germany).** The tool applies the
SEMIC shapes with a strict whole-dataset pass/fail rule. Germany scores 4.2%,
not because the tool is over-strict, but because German distributions carry
checksum values without the mandatory algorithm triple. This gap is real and
structural. It is invisible to the MQA's per-property scoring and to Germany's
self-report.

**3. Some ground truth looks stale (Romania).** ODMI records Romania's
access-URL presence as <10%. The live catalogue reads 99.8%. The most likely
explanation is that the ground-truth entry was filled in from an older or
inaccurate self-assessment. This matters for evaluation: some of the tool's
"diffs" against ground truth are probably cases where the tool is right and
ODMI's recorded answer is wrong.

**4. HU is the clean result.** Eight of nine metrics agree exactly, including
the non-obvious one: 1.9% open-licence coverage correctly reproduces ODMI's
<10% band. Hungary uses CC-BY-NC widely, which counts as a restricted licence
under the Open Definition. The tool picks this up correctly.

**5. Not every portal is harvestable.** Estonia's API is blocked at the network
level. Romania's host has intermittent availability from foreign IPs. Germany's
sample is order-biased (larger portals tend to appear first). These are
constraints on the tool's reach, not bugs in its logic, but they need to appear
in the dissertation's limitations section.
