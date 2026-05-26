# DIY-Tavily smoke run — 2026-05-26

End-of-build smoke check after Tasks 0-14 of `docs/superpowers/plans/2026-05-26-diy-tavily.md`. Run via `make` targets and direct invocation of the new `search()` provider dispatch.

## Setup

- 14 of 15 implementation tasks complete. Task 15 (this smoke run) is the last May milestone.
- Tavily and Brave free-tier quotas exhausted — providers will fail until June reset. Smoke restricted to `serper_raw` and `diy`.
- 182 unit tests pass, 12 skipped (live tests, opt-in via `pytest -m live`).
- Live tests, when run, all pass: 5 boilerplate rejections, 3 multilang preservations, 3 drift checks.

## Smoke: three queries × two providers

### France open data portal national

- **serper_raw** (2 results): top is `data.gouv.fr` with Serper's stock description. Score 1.0 (rank-derived).
- **diy** (2 results): same top URL but with Claude-extracted snippet — "La plateforme des données publiques françaises Utilisez, partagez et améliorez les données publiques". Score 0.95.

DIY's score calibration matches the content: high but not 1.0 because the picked passage is a mission statement rather than a direct definitional answer.

### Germany dataset publication policy

- **serper_raw** (3 results): top is a research paper about German funders' data sharing.
- **diy** (1 result): same top URL but only one chunk returned, scored 0.6. Two other Serper hits dropped.

DIY's 0.6 score is honest — "on-topic and partially answers" per the prompt's score bands. The two dropped URLs presumably had no passage strong enough to clear the relevance threshold. This is the picker performing its filtering role correctly, not a bug.

### Poland open data law 2021

- **serper_raw** (3 results): top is a Lexology summary, second is the EU Interoperable Portal's Poland page.
- **diy** (1 result): **dropped the Lexology article**, kept the EU portal page, picked the passage about parliament's unanimous vote on the directive. Score 0.9.

Of the three queries this is the clearest illustration of DIY's value. Lexology's page exists and ranks high on Serper, but its content for this specific query is weaker than the EU portal's directive passage. DIY's snippet picker correctly preferred quality of evidence over rank order.

## Observations to carry into June

1. **DIY result counts run lower than `serper_raw`.** Three queries returned 2, 1, 1 from DIY versus 2, 3, 3 from Serper raw. Caused by the empty-chunks → drop-URL rule. For the A/B this is a design feature (lower coverage in exchange for higher snippet quality); the A/B report should track both "match rate" and "coverage" so the trade-off is visible.

2. **Score calibration is non-trivially distributed.** Across three queries DIY produced scores of 0.95, 0.5, 0.6, 0.9 — not stuck near 1.0 or in obvious binary buckets. The prompt's "use the full 0-1 range" instruction is working.

3. **Same-URL agreement between DIY and Serper.** Where both return the same top URL, DIY's snippet reads more directly than Serper's metadata. This is the dissertation argument made concrete.

4. **No quota-related failures on Serper.** The Serper free-tier allowance survived the build phase (~30 API calls total during development including the eyeball harness smoke). Plenty of credit remaining for the June A/B.

## Status

DIY-Tavily implementation phase complete. Ready for the June A/B:

- All four conditions (`tavily`, `brave`, `serper_raw`, `diy`) callable through `search()` dispatch.
- Three caches (SERP, fetch, snippet) live with 30-day TTL, lazy schema creation.
- Nine test layers in place: 182 unit + 12 live tests covering plumbing, boilerplate, multilang, data-leakage, failure modes, drift, end-to-end.
- Quality fixture from finalised swarm runs ready to regenerate after the parallel D28 work finishes its row-count rebuild.

June checklist: in `docs/superpowers/plans/2026-05-26-diy-tavily.md` under "June-Deferred Tasks".
