# Agent task: build the catalogue / API route for Malta (and harden it generally)

You are working in the ODMI Agent Swarm repo. Goal: answer the portal/Quality
questions for Malta from the national portal's **structured metadata** (the
catalogue tool, D30) instead of scraping HTML, so the swarm bypasses the
Cloudflare WAF on data.gov.mt and can independently recompute catalogue metrics.
Work from the DB and live probes, not guesses. Commit a registry entry and
validation receipts.

## Read first
- `docs/SPEC.md` -> D30 (the deterministic catalogue tool: what it computes and
  how the per-country registry works), D24 (the data-leakage deny-list, a hard
  constraint), and the two 2026-06-03 Malta entries (the dispatch + the WAF
  finding).
- `docs/CATALOGUE_METRICS.md` -> the nine catalogue-derivable questions and the
  per-country route findings.
- `agents/tools/catalogue/` -> the tool. `compute.COMPUTABLE_QUESTIONS` is the
  authoritative set {Q12, Q13, Q16, Q17, Q18, Q21, Q22, Q25, Q27}. Registry in
  `data/catalogue/portals/<CC>.json`; read `NL.json` and `HU.json` as the
  schema templates (fields: `portal_base`, `stack`, `harvest_route`,
  `native_api_url`, `dcat_catalog_url`, `licence_field`, `pagination`,
  `page_size`, `robots_note`, `verified_at`, `notes`).
- `agents/tools/fetch.py` -> the hardened Playwright fallback (anti-automation
  launch args, `_settle_through_challenge`). This is what clears the WAF on HTML.

## What is already known (do NOT re-discover)
- The other five D30 countries work: HU, NL, DE, FR, RO have registry entries
  and validate against ODMI GT. EE was 403-blocked. **Malta has no registry
  entry yet** (`data/catalogue/portals/MT.json` does not exist).
- `portal.data.gov.mt` is a **uData** instance (its API lives under `/api/1/`,
  e.g. `/api/1/site/`, `/api/1/datasets/?page_size=N`, `/api/1/organizations/`).
- The portal is behind **Cloudflare**, and the WAF covers the **API paths too**,
  not just HTML. Confirmed blocked (HTTP 403, `text/html` "Attention Required"
  challenge) by THREE methods:
  1. plain httpx GET with a browser User-Agent;
  2. a Playwright `context.request.get(...)` after clearing the homepage
     (the cf_clearance cookie did not authorise the API path);
  3. an in-page `fetch(url, {headers:{Accept:'application/json'}})` evaluated
     inside the cleared page.
- The apex `data.gov.mt` (not `portal.`) returns clean **JSON 404s** to httpx
  (so it is reachable, just not the right host/paths for the catalogue).
- **HTML pages on portal.data.gov.mt DO clear** via the hardened Playwright
  render (head_ok, the DIY pipeline, and the Verifier all fall back to it).
- Hard constraints: the D24 deny-list (no `data.europa.eu` /
  `publications.europa.eu` / ODMI mirrors) is enforced and must stay enforced.
  Do **not** use a paid CAPTCHA solver or a residential proxy: cost, fragility,
  and reproducibility/ethics for the dissertation. The examiner-defensible route
  is structured data over a normal browser session.

## Tasks
1. **Find a reachable structured MT source.** In priority order, probe and
   record what returns JSON/RDF without a 403:
   - A **persistent** Playwright context: solve the homepage challenge once,
     save `storage_state` (cf_clearance), then in the SAME context navigate the
     browser directly to an `/api/1/...` URL (a navigation, not a fetch) and read
     the `<pre>`/body JSON. Try a longer settle and `networkidle`. The earlier
     attempts used a fresh context per request; a persistent, warmed context with
     a real cf_clearance may behave differently.
   - The uData **DCAT-AP RDF** export, if any (`/catalog.rdf`, `/data.json`,
     `dcat` content-negotiation), via the same cleared context.
   - An **alternative MT catalogue host**: a CKAN mirror, the national geoportal
     / INSPIRE endpoint, or an alt open-data domain that is not Cloudflare-
     fronted. Search for it; record the URL and what it serves.
2. **If a structured route is found**, add `data/catalogue/portals/MT.json`
   following the NL/HU schema (`stack: "udata"`, the working `native_api_url` or
   `dcat_catalog_url`, `licence_field`, `robots_note` describing the WAF and how
   you got past it, `verified_at`). Then make the catalogue fetch layer
   (`agents/tools/catalogue/_fetch.py` / `harvest.py`) fall back to the hardened
   Playwright render when httpx is WAF-blocked, so the route is robust for any
   Cloudflare-fronted portal, not just MT.
3. **Validate.** Run the catalogue tool on MT, compute the nine questions, and
   compare against ODMI `ground_truth` (leakage-guarded), producing the same
   per-question match/differ table as the D30 validation (see CATALOGUE_METRICS).
   Wire MT through the Researcher's catalogue route + the recompute Verifier as
   the other countries are.
4. **If NO structured route is reachable** (the WAF wins on every path), record
   that as the finding: MT catalogue questions are retrieval-bounded by the WAF,
   distinct from the five working countries. Fall back to extracting what the
   hardened Playwright HTML render gives, and state the reliability limit
   honestly. Do not paper over it.

## Constraints and reporting
- Keep the D24 deny-list enforced. No paid solvers, no proxies.
- Everything reproducible: commit the registry entry, the probe results, and the
  validation table. Add a SPEC change-log entry and update CATALOGUE_METRICS.
- Run `uv run pytest -q` before committing. Branch in a worktree
  (`EnterWorktree`); the shared `data/odmi.db` is a committed binary, so flag any
  DB change for merge.

## Verify before claiming done
- `data/catalogue/portals/MT.json` exists and the tool harvests MT without a
  deny-list hit, OR the no-structured-route finding is written up with evidence.
- A per-question MT validation table against ODMI GT, in the same shape as the
  other five countries.
