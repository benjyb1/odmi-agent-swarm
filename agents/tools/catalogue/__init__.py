"""Deterministic catalogue-metrics tool (SPEC D30).

A subset of ODMI Quality questions ask for a proportion of the national
catalogue (e.g. "what share of datasets carry a licence"). These are
computed statistics, not facts on any page, and the one public source that
publishes them (the MQA on data.europa.eu) is deny-listed under D24. This
package harvests each national portal's metadata and computes the metric
ourselves, deterministically, with near-zero token cost.

Public entry point: `agents.tools.catalogue.compute.compute_metric`.

The harvest never touches data.europa.eu or any deny-listed domain; every
endpoint is asserted against `agents.tools.blocked_domains.is_blocked`
before a fetch. See `docs/CATALOGUE_METRICS.md` for the question -> metric
mapping and `data/catalogue/portals/<CC>.json` for the verified endpoints.
"""
