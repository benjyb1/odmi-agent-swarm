# Snippet-picker call-volume analysis and options

Started as a read-only investigation, 2026-07-13. Sections 1-2c are unchanged
read-only analysis. Section 2d flagged live held-out-cache contamination
(pre-exp31-blockers item 3); that was then **purged from the canonical DB**
per instruction (see 2d for the purge record). All figures from the MT
production run of 2026-07-13 held in the `new-session-8a9e79` worktree DB
(`/Users/benjyb/Desktop/MscProject/.claude/worktrees/new-session-8a9e79/data/odmi.db`)
unless stated otherwise.
The `snippet-picker-cache-analysis-c91879` worktree DB is stale (latest picks
2026-07-02), so all queries below target the `new-session-8a9e79` copy.

## 1. When a picker call fires, and its cache key

Call path per query:

- `search_many` ([agents/tools/search.py:315](agents/tools/search.py:315))
  loops the query list, calls `search()` per query, and dedups the OUTPUT by
  URL with a `seen` set ([search.py:336-354](agents/tools/search.py:336)).
- `search()` -> `diy_search` ([agents/tools/search_diy.py:115](agents/tools/search_diy.py:115)).
- Inside `diy_search`: SERP (cached, keyed on `query|max_results|domains`),
  parallel fetch (cached, keyed on **normalised URL**), then a picker call per
  fetched page ([search_diy.py:240-257](agents/tools/search_diy.py:240)):
  ```python
  cached_chunks = cache.snippet_get(query, text, picker_model=picker_model)
  if cached_chunks is None:
      chunks, _ = pick_snippet(query=query, url=r.url, page_text=text, ...)
      cache.snippet_put(query, text, chunks, picker_model=picker_model)
  ```
- Snippet cache key = `sha256(query | sha256(page_text) | picker_model)`
  ([search_cache.py:121-134](agents/tools/search_cache.py:121)). Production
  passes `picker_model=None`, so the key is effectively `(query, page_text)`.

Key structural fact: the picker runs **before** `search_many`'s URL dedup. A
page that surfaces under query A and again under query B is fetched from cache
both times but **picked twice** (two different query keys), and the second
`SearchResult` is then **discarded** by `search_many`'s `seen` set. That
discarded pick is pure waste.

Drivers:

- Researcher: `search_many` over `num_queries` (prod 3) queries
  ([researcher.py:440](agents/researcher.py:440)); a wide fallback re-runs the
  **same** queries with no domain filter only if the narrow pass returned
  nothing ([researcher.py:458](agents/researcher.py:458)) - same query keys, so
  the wide pass **cache-hits**, no extra picks.
- Verifier: runs its **own** independent `search_many`
  ([verifier.py:611-656](agents/verifier.py:611)) with `verifier_search="always"`.
- Retries (D33): each retry generates **divergent** queries - the query-gen
  prompt is fed "Queries already tried (generate different ones)"
  ([researcher.py:164-168](agents/researcher.py:164)). New query string -> new
  cache key -> miss -> live re-pick of the same cached page.

## 2. Measured picker volume and cache hit rate (2026-07-13 MT run)

A live picker call writes a `claude_usage_log` row with
`context = 'snippet_pick:' || url[:80]`; a cache hit calls no LLM and is not
logged. So logged rows = live calls = cache **misses**.

| Metric | Value | SQL |
|---|---|---|
| Live picker calls | 1019 | `SELECT count(*) FROM claude_usage_log WHERE context LIKE 'snippet_pick%' AND substr(timestamp,1,10)='2026-07-13'` |
| Pairs producing picks | 38 | same, `count(DISTINCT subtrio_id)` |
| Picks per picking-pair | 26.8 | 1019/38 |
| Distinct snippet keys written | 1013 | `SELECT count(*) FROM search_cache_snippet WHERE substr(picked_at,1,10)='2026-07-13'` |
| **Snippet cache hit rate** | **~0.6%** (<=6/1019) | 1019 live calls vs 1013 keys written |
| Fetch cache rows for `portal.data.gov.mt` | 1 | `SELECT count(*) FROM search_cache_fetch WHERE url='https://portal.data.gov.mt'` |

The snippet cache is doing almost nothing on a real run: divergent queries mean
keys essentially never repeat. The fetch cache, keyed on URL, caches each page
exactly once. So the pages ARE cached; only the picker re-runs.

### Decomposition of the 1019 picks

| Bucket | Count | % |
|---|---|---|
| Genuine new (pair, URL) first-picks | 739 | 72.5% |
| Same-page re-picks under a divergent query, same pair | 280 | 27.5% |

SQL for the split:
```sql
WITH p AS (SELECT subtrio_id, substr(context,14) url FROM claude_usage_log
           WHERE context LIKE 'snippet_pick%' AND substr(timestamp,1,10)='2026-07-13')
SELECT count(*) total, count(DISTINCT subtrio_id||'|'||url) distinct_pair_url,
       count(*)-count(DISTINCT subtrio_id||'|'||url) redundant FROM p;
-- 1019 | 739 | 280
```

The 280 re-picks are the addressable pool. Of these, only the ones discarded
**within a single `search_many` call** are behaviour-neutral to remove; the
rest are the same page re-read across attempts/agents and their picks are
actually used. A time-gap proxy (gap between successive same-URL picks in a
pair) bounds the split:

| Gap between same-URL re-picks | Count | Interpretation |
|---|---|---|
| <= 20s | 85 | almost certainly same `search_many` call -> neutral |
| 21-90s | 164 | mostly same call, some cross-agent -> mixed |
| > 90s | 31 | across attempt/agent -> behaviour-changing |

So the provably-neutral yield floors at ~85 picks (8.3%); the bulk of the 280
is the same authority page re-read across the retry/verifier boundary.

### Retries dominate the bill

| retry_count | picking pairs | picks | picks/pair | % redundant |
|---|---|---|---|---|
| 0 | 7 | 56 | 8.0 | 23% |
| 1 | 6 | 96 | 16.0 | 28% |
| 2 | 3 | 76 | 25.3 | 21% |
| 3 | 22 | 791 | 36.0 | 28% |

22 of 38 picking pairs exhausted retries and consumed **78%** of all picks
(791/1019). The floor with no retries is 8 picks/pair (Researcher + Verifier,
3 queries each). Redundancy sits at ~25% regardless of depth - it is
structural, not a tail effect.

## 2b. The Serper layer - we DO re-find the same pages

The snippet cache and fetch cache are separate from the Serper (SERP) layer.
Where each stands on the same run:

- **Fetch cache (keyed on URL):** works. `portal.data.gov.mt` fetched once,
  reused everywhere. No waste to recover here.
- **SERP cache (keyed on `query|max_results|domains`):** ~1016 live Serper calls
  on the run, ~0% hit rate, for the same reason as the picker - divergent queries
  never repeat the key. Those 1016 calls returned 4322 result slots covering only
  **1325 distinct URLs**. The same pages come back again and again:

  | URL | distinct queries that returned it |
  |---|---|
  | mita.gov.mt/.../Public-Administration-Data-Strategy-2023.pdf | 218 |
  | portal.data.gov.mt/ | 182 |
  | data.europa.eu/.../malta-builds-transparency... | 125 |
  | economy.gov.mt/.../Malta-Digital-Decade-...pdf | 118 |
  | mita.gov.mt/.../NationalInteroperabilityFramework_2-1.pdf | 105 |

  SQL:
  ```sql
  WITH s AS (SELECT query,payload FROM search_cache_serp WHERE substr(fetched_at,1,10)='2026-07-13'),
  u AS (SELECT DISTINCT query, json_extract(je.value,'$.url') url FROM s, json_each(s.payload) je)
  SELECT url, count(*) FROM u GROUP BY url ORDER BY 2 DESC;
  ```

So the instinct is correct **for Serper**: a handful of authority pages are
re-discovered by 100-220 queries each. The waste is that Serper is query-keyed,
not that pages are not cached - the pages ARE cached at the fetch layer; it is
the *finding* of them that repeats.

Two distinct levers, not one:

- **Cut Serper:** stop re-finding known authority pages. A per-country seed-URL
  set (the ~20-50 recurring pages, fed straight to fetch, skipping Serper) or
  simply fewer queries. Behaviour-changing only if it alters the candidate set;
  if the seeds are pages Serper would have returned anyway, mild.
- **Cut snippet:** independent - even with pages seeded, the picker still runs
  per (query, page) because the query selects the chunk (Section 3). Seeding URLs
  does **not** reduce picker calls on its own.

The one lever that cuts **both** at once is fewer retries (Section 2 / Rank 2):
each retry generates fresh divergent queries that each trigger a Serper call
**and** per-page picks, and they re-find the same pages and oscillate.

## 2c. Caching viability (simulated from existing data, zero API spend)

**RAM is not a constraint.** The whole cross-country page cache already lives in
SQLite on disk:

| Cache table | On disk |
|---|---|
| `search_cache_fetch` (18,037 pages, 219 MB text) | 239 MB |
| `search_cache_serp` | 51 MB |
| `search_cache_snippet` | 31 MB |

Mean page 12.4 KB. A single country's page pool (MT ~2,000-2,500 distinct pages)
is ~28 MB; all 36 countries ~220 MB. You would load per-country slices, not the
lot. Holding this in memory is trivial.

**The pages are stable; the queries are not.** This is the whole story for a
Serper cut. Comparing today's run against all prior cache history:

| Reuse signal | Overlap with prior runs |
|---|---|
| Distinct **queries** seen before today | 25 / 803 = **3%** |
| Distinct **URLs** Serper returned that were already known | 938 / 1338 = **70%** |

The current SERP cache is keyed on the query, so it captures the 3% and misses
everything - which is why its hit rate on a real run is ~0%. But 70% of the pages
those novel queries surface were **already in the cache from earlier runs**. The
reuse potential is real and large; it is simply stored under the wrong key.

**Committed-evidence concentration (MT, all history).** 1810 committed answers
cite 525 distinct URLs. Coverage by the top-N most-cited pages:

| Seed set | Coverage of committed answers |
|---|---|
| Top 10 | 29% |
| Top 30 | 50% |
| Top 100 | 73% |

So a per-country page pool of ~100 URLs would already hold three-quarters of the
evidence the swarm actually commits to; the remaining 27% is a genuine long tail.

**What this means for a Serper cut.** Caching pages by URL does not, on its own,
reduce Serper - Serper runs *before* fetch to discover URLs. The 70% only
converts to fewer Serper calls if retrieval draws candidates from the per-country
pool instead of re-issuing a fresh Serper query for every novel phrasing. That
changes the candidate set the picker sees, so it is behaviour-changing (bucket b)
and needs the NL/MT experiment to price the fidelity cost. The RAM and
reuse-potential questions, though, are already answered: RAM fine, ~70% of
surfaced pages reusable.

## 2d. Held-out 8 (BA MK ME BG FI HR SE BE): caching does not apply the same way

These are the D47/D57 frozen headline set. The prior-run caching logic in 2c
(NL/MT: 70% URL reuse, 3% query reuse, 100-URL pool covers 73% of evidence)
**does not transfer**, and the cache that exists for these countries is a
liability, not an asset.

**The cache is not cold - it is contaminated.** D57 records two pre-freeze
touches: `exp21_frozen_headline` (2026-06-24, partial FI/HR/SE) and
`expC_held_neg_licide` (2026-06-27/28, all eight), both voided for reporting.
The bytes were never deleted:

```sql
SELECT substr(fetched_at,1,10) d, count(*) n FROM search_cache_fetch
WHERE url LIKE '%.ba/%' OR url LIKE '%.mk/%' OR url LIKE '%.me/%' OR url LIKE '%.bg/%'
   OR url LIKE '%.fi/%' OR url LIKE '%.hr/%' OR url LIKE '%.se/%' OR url LIKE '%.be/%'
GROUP BY d;
-- 2026-06-24: 955 rows, 2026-06-27: 1715 rows (the two voided runs), plus a long tail
```

2,770 fetch-layer rows total for these eight; ~24k SERP rows reference held-out
queries. **This is exactly [[pre-exp31-blockers]] item 3**, flagged 2026-07-12
and still open: "purge or `--no-cache` and write it in." The canonical checkout
(`/Users/benjyb/Desktop/MscProject/data/odmi.db`) carries the same rows (2,126
matching fetch entries) - this is not a worktree-local artefact.

**Why this overrides the caching-gains question.** If the headline run reads
this cache normally (reads on by default), it silently reuses pages, SERP
results, and (with `picker_model=None`) snippet picks from the voided runs.
That is not a performance win; it is undisclosed reuse of held-out-derived
evidence in the run whose entire purpose is a clean, first-touch estimate. Any
caching architecture proposed for the eight (2b/2c ideas included) must sit
**behind** this fix, not in front of it.

**Required before dispatch, one of:**
1. Purge `search_cache_{serp,fetch,snippet}` rows for the eight countries'
   domains/queries before the headline run, or
2. Run the headline with `--no-cache` (the existing `_READ_DISABLED` cold-cache
   toggle, EXP-2) so every layer recomputes live regardless of what is stored.

Option 2 is simpler and already exists as a flag; it also means the headline run
gets **zero** caching benefit by design - which is correct methodologically, but
worth saying plainly: whatever Serper/picker reduction Section 2c projects for
NL/MT does **not** apply to the frozen run.

**Where caching DOES help for the held-out set: post-headline only.** Once the
headline run has executed cold and reported, the pages it fetches become a
legitimate, undisclosed-reuse-free cache for any *later*, clearly-labelled
replay or ablation (e.g. EXP-28-style zero-cost reruns of the same final
config). That is the same pattern already used for `trio_s46` cache reuse in
EXP-28. It is not available for the headline run itself.

## 2e. Purge executed (2026-07-13) and reassessment for the full 8-country run

**Purge record.** On instruction, purged the held-out-8 rows from the canonical
`/Users/benjyb/Desktop/MscProject/data/odmi.db`:

| Layer | Match method | Rows deleted |
|---|---|---|
| `search_cache_fetch` | URL domain pattern (`.ba/ .mk/ .me/ .bg/ .fi/ .hr/ .se/ .be/`), spot-checked for false positives (`.me/` risk is real - Montenegrin sites vs generic `.me` vanity domains - all 20+ sampled were genuine `data.gov.me`/Montenegrin-news pages) | 3,962 |
| `search_cache_serp` | exact query match against every query pulled from `phase2_researcher_runs.search_queries_used` + `phase2_verifier_runs.independent_search_queries` for the 8 countries (11,014 distinct queries) | 11,014 |
| `search_cache_snippet` | same query set | 29,104 |

Backup taken first: `data/odmi.db.bak-preheldoutpurge-20260713-153926`. Post-purge
`VACUUM` shrank the file 646 MB -> 539 MB. Verified zero rows remain on all three
layers. **Not fixed by this:** any other worktree DB copy (e.g.
`new-session-8a9e79`) still carries the old contaminated rows - whichever
worktree actually dispatches EXP-31 needs its own purge, or a fresh copy of the
canonical DB, or `--no-cache` as a backstop regardless.

### What caching gains to expect on the full run, now that it's genuinely cold

The framing changes for this run versus the MT/NL numbers in 2a-2c. There is
**no cross-run reuse** to bank on - that would be the same contamination
problem again. What's left is legitimate **within-run** reuse across the
143 questions asked per country, and it splits cleanly by layer:

- **Fetch layer: works, no change needed.** The first question that touches a
  country's national portal caches it; the other ~142 questions for that
  country hit the cache for free. This is the existing, correct behaviour
  (Section 1) and needs nothing new to benefit from it.
- **SERP layer: caching gives ~0% here too, structurally.** 143 questions
  about different ODMI dimensions generate mostly distinct queries even
  within one country, so the query-keyed SERP cache will behave like the MT
  numbers in 2c: ~0% same-run hit rate, `~70%` URL-level overlap (same
  pages, different queries). Caching the SERP layer as currently keyed
  will not visibly cut Serper calls on this run; only reducing the number of
  *queries issued* (fewer retries, fewer queries/attempt) does that.
- **Snippet layer: same ~25-30% structural redundancy as MT**, for the same
  reason (D33 divergence + retries), independent of any caching fix.

**Rough scale.** 8 countries x 143 questions = 1,144 base pairs. Using the MT
rate (1,019 picker calls / 84 attempted pairs approx 12.1 calls/pair, before any
fix) as an order-of-magnitude proxy, expect on the order of ~12-14k picker
calls and a proportional Serper-query count across the full run, before any
optimisation. The held-out countries are more likely to run to full retries
than MT/NL (less-tuned trusted-domain lists per pre-exp31-blockers item 2), so
this is a floor, not a ceiling.

**What's safe to apply to THIS run without re-opening methodology:**

- **Rank 1 (within-call URL dedup, Section 5) is bucket (a), byte-identical.**
  Safe to ship into the frozen config before dispatch - it only removes picks
  `search_many`'s own dedup was already discarding. Cuts picker calls by
  ~8-15%; does **not** reduce Serper calls, because Serper already runs once
  per query regardless of URL overlap.
- **Rank 2 (fewer retries) is NOT safe to bolt on now.** It is the one lever
  that cuts both Serper and picker calls together (fewer retries = fewer query
  rounds entirely), but `max_retries` has not been validated on the NL/MT dev
  set and is not part of any registered D57/EXP-31 config decision - I checked
  `docs/SPEC.md` and `docs/EXPERIMENTS_FINAL_PROGRAMME.md`, no entry pins it.
  Changing it for the headline run without that validation repeats the exact
  mistake D50 (neg_licence) was rejected for: an appealing untested cut applied
  to the run that produces the dissertation's most defensible number. If the
  Serper/picker cost of the full run is a genuine problem, the NL/MT pilot
  (Section 5, Rank 2) needs to run and clear the adoption rule **before**
  EXP-31 dispatches, not during it.

**Bottom line:** ship the free dedup now; the retry cut is the real lever for
Serper reduction but needs its validation pass first if you want it in the
headline run rather than only in later cycles.

## 3. Is the picker query-sensitive in practice?

For pages picked under more than one query in the last two run-days
(2026-07-12/13), comparing distinct chunk outputs per page:

```sql
WITH recent AS (SELECT page_text_hash, query, chunks_json FROM search_cache_snippet
                WHERE substr(picked_at,1,10) IN ('2026-07-13','2026-07-12')),
g AS (SELECT page_text_hash, count(DISTINCT query) nq, count(DISTINCT chunks_json) nc
      FROM recent GROUP BY page_text_hash HAVING nq>1)
SELECT CASE WHEN nc=1 THEN 'identical' WHEN nc<nq THEN 'partial' ELSE 'all different' END, count(*)
FROM g GROUP BY 1;
```

| Page class (n=635 multi-query pages) | Pages | Share |
|---|---|---|
| Identical output regardless of query (query-insensitive) | 180 | 28% |
| Partial overlap | 201 | 32% |
| Every query a different output (query-sensitive) | 254 | 40% |

So on **72%** of multi-query pages at least one query produced byte-different
chunks. A page-level cache that ignores the query would change the evidence on
those pages. It is **not** behaviour-neutral.

Concrete: the most re-picked page, `portal.data.gov.mt/` (105 picks / 31 pairs),
under 12 divergent queries returned the **same** top chunk 10 times and an
**empty** pick twice. This is the query-insensitive class in the flesh - a thin
homepage with one boilerplate description. The two empties matter: a page-level
cache serving the boilerplate for those queries would ADD evidence the swarm
currently does not see (empty -> URL dropped today). Evidence changes either way.

## 4. Does forcing query divergence help retrieval? (your direct question)

Two findings, both against the divergence loop paying its way:

1. **Divergent queries re-surface the same pages, not new ones.** Serper returns
   the national portal homepage for almost any MT open-data query. `portal.data.gov.mt/`
   was picked in 31 of 38 pairs, `msdi.data.gov.mt/` in 17, `mita.gov.mt/...`
   in 16. Divergence changes the query string; Serper hands back the same
   authority pages. The value of a retry is a query-conditional **re-read** of
   already-fetched pages, not the discovery of new pages.

2. **On thin pages the re-read finds nothing new; the committed answer
   oscillates.** For the portal homepage, 10/12 divergent queries returned the
   identical passage and 2 returned nothing. Tracking the Researcher answer
   across retries (`phase2_researcher_runs`, MT today), the answer changes
   between attempt 0 and the final attempt in ~65-75% of retrying pairs, but it
   **oscillates** rather than converges:
   - `inconclusive -> no -> inconclusive -> no`
   - `inconclusive -> yes -> inconclusive -> yes`
   - `inconclusive -> no -> inconclusive`

   Attempt 0 is almost always `inconclusive` at low confidence; retries flip it
   on and off. The final committed answer is largely a function of which attempt
   happened to run last, not of accumulated evidence.

To your second worry - "how do we stop them pulling the wrong info again" -
there is currently no such guard. The loop re-reads the same thin pages and can
land a different (possibly wrong) reading each attempt. The oscillation is the
symptom. This is a methodology finding worth reporting in its own right, not
only a cost issue.

## 5. Options, ranked

Bucket key: **(a)** behaviour-neutral, byte-identical picked chunks, safe to
ship; **(b)** behaviour-changing, needs an NL/MT dev experiment (D22/D47) before
adoption.

### Rank 1 - Within-call pre-pick dedup **(a, neutral)** - SHIP

- **Mechanism.** In `search_many`, thread the emitted-URL `seen` set down into
  `diy_search` (or filter the SERP against already-emitted URLs before the
  fetch/pick loop), so a URL already emitted in this call is not picked again.
- **Why byte-identical.** Those second picks are already thrown away by
  `search_many`'s `seen` dedup today; the kept result is the first query's pick,
  unchanged. Empty-then-non-empty is preserved because an empty first pick never
  enters `seen`.
- **Reduction.** Floor ~8.3% (85/1019), realistically ~10-15%. Exact figure
  needs a one-line counter on the `seen` set; it cannot be read off the logs.
- **Risk.** Low. One function, no evidence change, no experiment.

### Rank 2 - Cut `max_retries` 3 -> 1 **(b, behaviour-changing)** - HIGHEST LEVERAGE

- **Mechanism.** Lower the Coordinator retry ceiling. retry>=2 attempts produce
  no new pages and an oscillating answer (Section 4).
- **Reduction.** Up to ~50-60% of picks. retry=3 pairs alone are 78% of volume;
  removing attempts 2-3 removes most of that.
- **Bucket justification.** Retries change the committed answer 65-75% of the
  time, so this is not free - it must be validated. But the change is oscillation,
  not convergence, so the expected match-rate cost is plausibly ~zero.
- **Experiment.** NL + MT dev set, arms `max_retries in {1,2,3}`, one variable,
  pinned Researcher/Verifier model (4.6) and DIY provider. Compare match-rate,
  FP-rate, abstention, picks/pair. Pilot 10-20 pairs against the last baseline
  before the full battery (cost-savvy dispatch).
- **Risk.** Medium. Directly answers your divergence question and is the biggest
  single cut.

### Rank 3 - Pair-level page cache across queries/attempts/agents **(b)**

- **Mechanism.** Cache a page's picked chunks keyed on page only; reuse for every
  query, attempt, and agent in the pair.
- **Reduction.** ~27.5% within-pair plus the cross-agent reuse on top.
- **Bucket justification.** 72% of multi-query pages return different chunks per
  query (Section 3); serving one query's pick for all changes evidence, including
  flipping empty -> boilerplate.
- **Experiment.** Same NL/MT harness; the metric is committed-answer delta and
  match-rate vs baseline.
- **Risk.** Medium-high. Larger fidelity surface than Rank 2.

### Rank 4 - Two-tier: page candidate-chunk cache + cheap query re-rank **(b)**

- **Mechanism.** One LLM pass per distinct page extracts top-K candidate
  passages once; a non-LLM re-rank (BM25 / embedding) picks per query. Replaces
  ~26.8 LLM picks/pair with ~19.4 (distinct URLs) or fewer.
- **Reduction.** Largest structural cut, potentially >50%.
- **Bucket justification.** Changes the selection algorithm itself.
- **Risk.** High. Most engineering, biggest behaviour shift, hardest to validate
  as equivalent. Right long-term answer to "the retry value is a re-read", but
  not a near-term win.

### Rank 5 - Smaller picker model (Haiku) **(b)** - orthogonal

- Cuts cost per call ~10x but **not** call volume. EXP-17 territory. Compose with
  any option above; does not address the volume problem you asked about.

### Rank 6 - Thin-homepage suppression **(b)** - brittle

- Detect low-content authority homepages Serper returns for every query and pick
  once per pair. Heuristic "thin" definition; the 2 empty returns show even thin
  pages are not perfectly stable, so not neutral. Low priority.

## 6. Recommendation

- **Ship now (neutral):** Rank 1, within-call pre-pick dedup. Provably
  byte-identical, ~8-15% fewer picks, no experiment.
- **Validate next (behaviour-changing, best cut):** Rank 2, cut `max_retries`
  3 -> 1, on NL + MT. The answer-oscillation evidence says attempts 2-3 add noise,
  not signal, so this is the likely free 50%+ cut and it settles the divergence
  question at the same time.
- Hold Rank 3/4 until Rank 2 lands - if fewer retries already removes most of the
  volume, the page-level cache and the two-tier rebuild may not be worth their
  fidelity risk.
