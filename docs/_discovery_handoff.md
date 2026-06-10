# Portal discovery: session handoff (2026-06-10)

Paused mid-task. This note is the resume point for the portal-discovery
sub-project (worktree `vigilant-agnesi-3135ed`, branch
`claude/vigilant-agnesi-3135ed`). Delete this file once tasks below are done.

## State: built, tested, committed

All committed on this branch; full suite was green (585 passed, 13 skipped)
plus newer discovery tests:

- `agents/tools/catalogue/discovery/` package: `seeds.py`, `probes.py`
  (CKAN incl. `/data` prefix, uData, paged DCAT-AP feeds, OpenDataSoft,
  piveau, data.json, SPARQL with `sparql_endpoint` hint, hint-driven FDK),
  `verify.py` (route choice, one-page sample verification, caveat
  auto-detection: HU/RO rdf-without-licence fallback, FDK missing
  downloadURL, JSON-synthesis), `emit.py` (registry emission with D24 URL
  gate, no overwrite without force), `run.py` (orchestrator + CLI).
- D24 hardening: `_fetch.py` re-checks the redirect chain and grew a
  guarded `post_json`.
- Seed file `data/catalogue/portal_seeds.json`: all 36 countries, sourced
  without the EU aggregator, every entry annotated.
- Tests: `tests/test_catalogue_fetch_guard.py`, `test_portal_discovery_*.py`
  (probes/verify/emit/seeds/run), `test_discovery_ceiling.py`.
- Ceiling-lift analysis `evaluation/discovery_ceiling.py`
  (`--report` flag consumes a discovery report).
- Three discovered registries already emitted and committed:
  IE (ckan_json, caveats rdf_feed_omits_dct_license +
  conformance_synthesised_from_json), LU (dcat_rdf first-party feed),
  SI (ckan_json, no_licence_metadata_on_any_route). All three drive
  `harvest_country` unchanged (one-page harvests verified live).

## Live findings so far

- AT: relaunched on piveau -> needs_new_adapter (probe added).
- SE: EntryScape, SPARQL on admin.dataportal.se (seed hint added) ->
  needs_new_adapter.
- MT: WAF-blocked from this environment (every host 403/JSON-404), same
  class as EE's IP block -> honest failed.
- AL, BA: live portals, no recognisable API -> failed.

## Interrupted: the 36-country experiment run (task 7)

A background run `uv run python -m agents.tools.catalogue.discovery.run
--all --report evaluation/results/discovery_report.json` was killed at
4/36 by the laptop closing (report only written at the end; partial
console log in `evaluation/results/discovery_run_partial_2026-06-10.log`).
It is idempotent (no emission, no DB writes). **Resume by re-running the
same command** (background, ~20-40 min, throttled), then:

1. Read the report; for each `verified` country, re-run with `--emit`
   for just those CCs (or eyeball first). Do not `--force` over
   DE/EE/FR/HU/NL/RO/IE/LU/SI.
2. `uv run python -m evaluation.discovery_ceiling --report
   evaluation/results/discovery_report.json` for the ceiling-lift table.
3. Commit the report + any new registries.

## Then: task 8 (docs)

- New SPEC decision: use **D46** (D44 merged; D45 claimed by the
  unmerged `audit-fix-batch` branch). Document: seed provenance rule,
  fingerprint probes, verification + caveat auto-detection, emission
  gate, redirect-chain guard, fallback policy (failed countries keep the
  web-search path, flagged "no deterministic route"), and the experiment
  numbers from the report.
- `docs/PORTAL_DISCOVERY.md` (design + per-country outcome table),
  update `docs/CATALOGUE_METRICS.md` per-country route table,
  `docs/PROJECT_LOG.md` session entry, CLAUDE.md status block line.
- UK English, no em dashes. Commit; do NOT push. Branch merges later.

## Task list state

Tasks 1-6 completed. Task 7 (36-country run + report) in progress,
interrupted. Task 8 (SPEC/docs) pending.
[1/36] AL https://opendata.gov.al ...
  -> failed error=no stack fingerprint matched
[2/36] AT https://www.data.gv.at ...
  -> needs_new_adapter new_stacks=['piveau']
[3/36] BA https://odp.iddeea.gov.ba ...
  -> failed error=no stack fingerprint matched
[4/36] BE https://data.gov.be ...
  -> failed error=no stack fingerprint matched
[5/36] BG https://data.egov.bg ...
  -> failed error=no stack fingerprint matched
[6/36] CH https://opendata.swiss ...
(partial console log appended above from /tmp/discovery_run.log; *.log is gitignored)
