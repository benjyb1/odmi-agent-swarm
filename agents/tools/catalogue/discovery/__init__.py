"""Portal-discovery tool: find a country's national open-data portal route.

Turns a committed seed URL (`data/catalogue/portal_seeds.json`) into a
verified `data/catalogue/portals/<CC>.json` registry, so the deterministic
catalogue-metrics tool (D30) can run without a hand-authored file per
country. Three stages:

1. `probes` fingerprints the portal software from public API signatures.
2. `verify` harvests a small sample through the matching adapter and
   auto-detects the known caveats (RDF feed missing dct:license, missing
   dcat:downloadURL, ...).
3. `emit` writes the registry JSON in the same shape as the hand-authored
   six, tagged with `discovery_method`.

Leakage (D24) is enforced at every layer: all traffic goes through
`catalogue._fetch` (which refuses deny-listed URLs and redirect chains),
and the seed loader, prober and emitter each re-check the deny-list.
"""

from agents.tools.catalogue.discovery.probes import (  # noqa: F401
    ProbeEvidence,
    probe_all,
)
