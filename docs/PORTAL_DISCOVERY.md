# Portal discovery

How the discovery tool (`agents/tools/catalogue/discovery/`, SPEC D46) turns a
committed seed URL into a verified `data/catalogue/portals/<CC>.json` registry,
so the deterministic catalogue-metrics tool (D30) can run for any assessed
country without a hand-authored file. Norway is the motivating case: it scored
poorly on Quality purely because `NO.json` did not exist, while data.norge.no
published DCAT-AP-NO the whole time.

## Why

D30 fires only for countries with a portal registry. Six existed (DE, EE, FR,
HU, NL, RO), all hand-authored. The per-country answerable-share analysis
(`evaluation/answerable_share.py`) prices the gap: countries with a registry
sit at an ~89.4% open-web accuracy ceiling, countries without sit at ~83%.
Hand-authoring 36 registries, and re-verifying each one per assessment cycle,
does not scale and rots silently. Discovery replaces the hand-authoring with a
probed, verified, receipted pipeline; the hand-authored six remain untouched
and act as a validation set for the prober.

## Pipeline

1. **Seeds** (`seeds.py`, `data/catalogue/portal_seeds.json`). One entry per
   ODMI-assessed country: `portal_base`, optional `alternates` (fallback
   hypotheses), optional `hints` (endpoints that cannot be guessed from the
   base URL, e.g. Norway's FDK search service or Sweden's SPARQL host), and a
   mandatory `source` annotation saying how the URL was found. The list was
   compiled without consulting the EU aggregator (D24); the loader refuses any
   deny-listed entry. A seed is a hypothesis, not a fact: only probing turns it
   into a verified endpoint.

2. **Fingerprinting** (`probes.py`). Cheap, public-signature probes, one or two
   requests each:

   | Probe | Signature | Route |
   |---|---|---|
   | CKAN | `/api/3/action/package_search?rows=1` returns `success: true` plus `result.count`; also tried under the `/data` prefix (the data.overheid.nl pattern) | `ckan_json` |
   | uData | `/api/1/datasets/?page_size=1` returns `data` plus `total` | `udata_json` |
   | DCAT-AP feed | `catalog.{ttl,xml,rdf}?page=1` or the uData first-party `api/1/site/catalog.ttl` parses as RDF with at least one `dcat:Dataset` (an HTML shell is a miss) | `dcat_rdf` |
   | FDK | hint-driven: the search service answers a POST with `hits` plus `page.totalElements` | `fdk_rdf` once that adapter merges; until then flagged |
   | OpenDataSoft | `/api/explore/v2.1/catalog/datasets?limit=1` returns `total_count` | none yet |
   | piveau | `/api/hub/search/search?filters=dataset` returns `result.index == "dataset"` plus `result.count` (the data.europa.eu software family, nationally hosted, e.g. the relaunched data.gv.at) | none yet |
   | data.json | `/data.json` with a non-empty `dataset` array | none yet |
   | SPARQL | `ASK { ?s a dcat:Dataset }` returns true; `sparql_endpoint` hint overrides `{base}/sparql` for sibling hosts (Sweden's EntryScape) | none yet |

   A probe miss is any HTTP or parse failure. A D24 deny-list refusal is never
   a miss: it propagates and aborts the country, because a portal redirecting
   to data.europa.eu must surface as a leakage event, not as "stack unknown".

3. **Verification** (`verify.py`). For each routable fingerprint, in preference
   order `dcat_rdf` > `ckan_json` > `udata_json` > `fdk_rdf`, harvest one page
   through the real adapter and compute field-presence stats over the sample
   (licence at dataset and distribution level, access-URL, download-URL,
   format). Auto-detected caveats:

   | Caveat | Trigger | Known precedent |
   |---|---|---|
   | `rdf_feed_omits_dct_license` | RDF sample has zero licence values while a JSON route carries them; the JSON route wins | HU, RO (hand-authored), IE (discovered) |
   | `feed_omits_download_url` | no `dcat:downloadURL` anywhere in the sample; Q21 reads near 0% faithfully to the feed | FDK/Norway |
   | `conformance_synthesised_from_json` | any JSON route: Q16/Q17/Q18 run over graphs synthesised from JSON | NL, EE, HU |
   | `no_licence_metadata_on_any_route` | no route's sample carries any licence value | SI (discovered) |

   A sample with no datasets or no distributions rejects the route. A stack
   recognised without an adapter makes the country `needs_new_adapter`; no
   fingerprint at all makes it `failed`. Both are explicit outcomes, never a
   silent low score.

4. **Emission** (`emit.py`). A verified outcome is written as
   `data/catalogue/portals/<CC>.json` in the same shape as the hand-authored
   six, plus `discovery_method: "auto"`, `discovery_evidence` (the matched
   endpoint and signature) and the machine-readable `caveats` list.
   `licence_field` is set from the sample (dataset vs distribution level).
   Every URL in the outgoing payload is re-checked against the deny-list, and
   an existing registry is never overwritten without `force`.

5. **Fallback.** A country with no verified route keeps the web-search path
   unchanged. The discovery report records why (`needs_new_adapter` with the
   detected stack, or `failed` with the error), so the gap is visible and
   priced rather than silent.

## Leakage controls (D24)

- The seed list is sourced without the EU aggregator and every entry carries
  its provenance; `load_seeds` refuses deny-listed URLs
  (`tests/test_portal_discovery_seeds.py`).
- All discovery traffic goes through `catalogue/_fetch.py`, which refuses
  deny-listed URLs before the request and, since this work, re-checks the
  redirect chain and final URL after it (`tests/test_catalogue_fetch_guard.py`).
- `probe_all` refuses a deny-listed base and never swallows a
  `BlockedEndpointError` (`tests/test_portal_discovery_probes.py`).
- `emit_registry` walks every URL in the outgoing registry against the
  deny-list before writing a byte (`tests/test_portal_discovery_emit.py`).
- ODMI's answers never feed any step: discovery reads portal APIs only, and the
  metrics pipeline it feeds (D30) never reads `ground_truth`.

## Running it

```bash
# One country, no side effects
uv run python -m agents.tools.catalogue.discovery.run IE

# Probe everything, write the experiment report
uv run python -m agents.tools.catalogue.discovery.run --all \
    --report evaluation/results/discovery_report.json

# Emit registries for verified countries (never overwrites without --force)
uv run python -m agents.tools.catalogue.discovery.run IE LU SI --emit

# Ceiling lift from a report
uv run python -m evaluation.discovery_ceiling \
    --report evaluation/results/discovery_report.json
```

A discovery run samples one page per candidate route; it never performs a full
harvest. Politeness: 1s between probes, 2s between countries.

## Results (2026-06-10 run)

PENDING: filled from `evaluation/results/discovery_report.json` when the
36-country run completes.

## Limitations

- A one-page sample can misread an order-biased feed (the FR validation showed
  first pages skew licensed); sample stats are verification signals, not
  metric values. The metrics themselves run on much larger harvests with
  disclosed sample sizes.
- WAF/IP blocks (EE in the hand-authored set, MT here) are environment
  dependent: the route may work from a residential or EU IP. The outcome
  records the HTTP evidence either way.
- piveau portals can federate EU-scope datasets; a future piveau adapter must
  filter to the national scope before computing metrics.
- Seed URLs and hints still rest on human knowledge of which portal is "the
  national one"; ODMI's own country sheets name the portal, but reading them
  is forbidden (D24), so the seed list is the honest substitute and is itself
  receipted.
