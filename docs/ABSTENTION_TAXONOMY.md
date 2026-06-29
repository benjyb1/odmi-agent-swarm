# Abstention and Failure Taxonomy

A diagnostic classification of every finalised pair where the swarm did not
commit an answer. Built read-only from `data/odmi.db` on 2026-06-24. The
classifier is `evaluation/abstention_taxonomy.py`; the per-pair record dump is
`evaluation/abstention_records.csv`. Nothing here writes to the pipeline or
feeds ground truth back into any agent.

Snapshot note: the DB was being written to by a concurrent dispatch window
while this ran. The figures below are frozen to a single classifier pass over
1,657 finalised pairs (580 non-committed). Re-running the classifier on a later
DB will move a few counts by one to three pairs as more batches land; the
shape and the conclusions are stable. Treat the exact integers as a snapshot,
not a constant.

This is the abstention companion to `docs/FAILURE_MODES.md`. That register
catalogues ways a wrong answer reaches "committed" (false positives). This
file catalogues the opposite tail: the pairs the swarm declined to answer, and
why. Where the failure-modes file is forward-looking and structural, this one
is empirical and after the fact.

## Population

An abstention is `final_answer = 'inconclusive'`. A failure is
`terminal_status = 'agent_failure'`. The union is the non-committed population.

| Slice | Count |
|---|---|
| Finalised pairs in `phase2_final` | 1,657 |
| Abstentions (`final_answer='inconclusive'`) | 548 |
| Failures (`terminal_status='agent_failure'`) | 65 |
| Union (non-committed) | 580 |
| Non-committed share of all finalised pairs | 35.0% |

The two sets overlap: 33 agent-failures also carry `inconclusive`, 26 carry a
null answer, and 6 sit on a committed-looking label that never cleared a gate.
The union is the honest denominator for "did not commit".

Almost every non-committed pair exhausted the retry budget: 557 of 580 reached
`retry_count = 3`. Abstention is not an early give-up; it is the state the
pipeline lands in after three full attempts fail to produce a defensible
answer.

### Where in the pipeline the abstention is decided

The headline structural fact: abstention is mostly **not** the Researcher
failing to find anything. Across the 548 inconclusive finals, the Researcher
proposed a committed answer (`yes`/`no`/a band) on at least one of its attempts
in 444 cases. Only 104 are pairs where the Researcher never once committed.
The other 444 had a candidate answer that was knocked down to `inconclusive`
by the Verifier or the Adjudicator over the retry chain. So the dominant
abstention is verification attrition, not retrieval emptiness.

Of the 548 inconclusive finals, 491 reached the Adjudicator. 171 ended in
`abstain` (D51, formerly `escalate_human`; the Adjudicator's confidence fell
below its 0.6 auto-promotion floor). The rest were ratified as `inconclusive` by
the Adjudicator or passed
through with a Verifier verdict on an answer that was already `inconclusive` by
that point.

## Categories

Derived empirically from the trail, in priority order (a pair is assigned to
the first category it matches). Counts are over the 580-pair union. The final
column is the ground-truth check: of the pairs in this category, how many had
the ODMI experts commit a real answer (anything other than `i don't know` /
`not applicable` / `n/a`). A high number there means the abstention was a
**miss**, not an honest deferral on a truly unknowable question.

| Code | Category | n | % of union | GT committed an answer |
|---|---|---:|---:|---|
| E | Verifier relevance rejection | 163 | 28.1% | 157 / 163 |
| G | Below confidence floor (0.65) | 146 | 25.2% | 134 / 146 |
| I | Researcher never committed | 73 | 12.6% | 70 / 73 |
| D | Evidence ungrounded (substring gate) | 66 | 11.4% | 61 / 66 |
| B | Fetch error (4xx/5xx/timeout) | 51 | 8.8% | 51 / 51 |
| A | Thin web / no search results | 38 | 6.6% | 38 / 38 |
| F3 | Search-empty hard failure | 21 | 3.6% | 21 / 21 |
| C | Deny-listed / MQA source contact | 8 | 1.4% | 8 / 8 |
| F1 | Schema-invalid hard failure | 5 | 0.9% | 5 / 5 |
| Z | Other / uncategorised | 9 | 1.6% | 9 / 9 |

Overall, **554 of 580 (95.5%)** non-committed pairs are ones where the ODMI
experts did commit an answer. The swarm's abstentions are overwhelmingly
misses against the gold standard, not cases where the question is truly
unanswerable. Only 26 pairs sit on a ground-truth `i don't know`, the one
slice where our abstention agrees with the experts' own uncertainty.

A second cut over the same population: in 374 of 580 pairs (64%) the
Researcher's own explanation explicitly states that the search snippets do not
contain the needed evidence ("the search snippets do not contain any evidence
about...", "no specific percentage...", "no explicit policy..."). This is the
web-unanswerable surface (FM-19 in `docs/FAILURE_MODES.md`) made measurable.
The categories below are largely different downstream expressions of that one
upstream cause.

### E. Verifier relevance rejection (163)

The Researcher committed an answer, the evidence quote passed the substring
gate (it was really on the page), but the Verifier judged the quote did not
entail the answer to the question and failed it across retries. Median
Researcher answer-confidence here is 0.65, sitting right on the commit floor,
so these are not low-confidence collapses; they are confident answers whose
evidence the Verifier found off-target.

Examples:
- `P25:MT` (Policy) GT=`yes`. "the search snippets do not contain any evidence
  about Malta-specific processes for assessing whether public sector bodies
  charge above marginal cost". The portal exists but the *process* question is
  not documented on the open web.
- `Q1:MT` (Quality) GT=`yes`. "no evidence of a pre-defined approach to keeping
  metadata up-to-date specifically for Malta's national open data portal".
- `PT12:MT` (Portal) GT=`no`. "no evidence about RSS feeds, Atom feeds, email
  notifications, or any subscription/notification feature on data.gov.mt".

### G. Below confidence floor (146)

The Researcher's best answer-confidence across all attempts stayed under the
0.65 commit floor (D37). The answer existed but the agent would not stand
behind it, so the floor abstained rather than commit a guess. This is the
floor working as designed; the question is whether the floor is calibrated
(see FM-26).

Examples:
- `PT9:MT` (Portal) GT=`no`, confidence 0.4. "no evidence of a feedback button,
  comment section, or user rating mechanism on data.gov.mt".
- `I2:MT` (Impact) GT=`yes`, confidence 0.35. "no evidence of a formal process
  in Malta to monitor or track the reuse of open data".
- `PT28:MT` (Portal) GT=`yes`, confidence 0.35. "the search snippets do not
  provide sufficient evidence that Malta's open data portal specifically
  monitors search keywords".

### I. Researcher never committed (73)

Across all attempts the Researcher only ever returned `inconclusive` (or
`other`). These are the closest to a true retrieval failure: the agent never
found enough to form a candidate.

Examples:
- `PT45:MT` (Portal) GT=`yes`. "the search snippets do not contain any direct
  evidence about whether data.gov.mt provides monitoring tools or feedback
  mechanisms".
- `PT23:NO` (Portal) GT=`yes`. "the search results only return road traffic
  datasets published on data.norge.no, not information about whether the portal
  itself monitors its own web traffic". A keyword collision: the query term
  ("traffic") pulls the wrong sense.
- `Q22:NO` (Quality) GT=`71-90%`. The portal uses DCAT-AP-NO and individual
  datasets carry the field, "but no aggregate statistic about the percentage of
  all datasets" is on the open web. A quantity that only the MQA computes.

### D. Evidence ungrounded, substring gate (66)

The Researcher committed an answer but the evidence quote failed the Verifier's
verbatim substring check (`agents/tools/substring.py`): the quote was not found
on the cited page, or the source URL was not among the snippets the Researcher
read. This is FM-08 (the fabricated-quote gate) firing as intended, plus its
FM-10 cousin (quote-URL mismatch). The pair abstains rather than commit an
unverifiable quote.

Examples:
- `I9-a:MT` (Impact) GT=`yes`. Committed an answer about Malta's multi-
  stakeholder forum but the quote was not grounded on the cited page.
- `P18:NO` (Policy) GT=`yes`, note "source_url not among search snippets". The
  answer was plausible but the URL did not match the read snippets.
- `P22:MT` (Policy) GT=`yes`. Referenced Malta's NAP under the Open Government
  Partnership but with no quote that survived the gate.

### B. Fetch error (51)

Pages were found in search but could not be retrieved: `url_unreachable`
failure mode, or fetch markers in the notes ("HEAD/GET returned status 403",
status 0, timeouts). The evidence may have existed behind the wall. This
cluster is heavily Malta: `data.gov.mt` sits behind a WAF that returns 403 to
the fetcher, so the Researcher sees only search snippets and never the page
body.

Examples:
- `I8-c:MT` (Impact) GT=`no`, "HEAD/GET returned status 403".
- `PT18:MT` (Portal) GT=`no`, "HEAD/GET returned status 403".
- `P18:MT` (Policy) GT=`yes`, confidence 0.72, repeated 403s. Note this one
  cleared the floor on confidence but the underlying page was never readable.

### A. Thin web / no search results (38)

No usable snippets anywhere in the trail (empty snippet blob, or a
`search_empty` signal) and the Researcher never assembled enough to commit.
Distinct from B in that B *found* URLs but could not fetch them; A found
little to begin with.

Examples:
- `Q4:FR` (Quality) GT=`yes`. France publishes time-series datasets but "no
  explicit policy or measure specifically ensuring complete temporal coverage"
  surfaced in search.
- `I9-c:FR` (Impact) GT=`yes`. A non-scored descriptive item with status-0
  fetches and thin returns.
- `I8-d:FR` (Impact) GT=`yes`. Similar: an informational item with no
  retrievable specifics.

### F3. Search-empty hard failure (21)

Same upstream cause as A but the pair terminated as `agent_failure` with
`final_failure_reason = 'search_empty'` rather than resolving to an
`inconclusive` label. An operational rather than reasoned abstention. Again
Malta-dominant via the 403 wall.

Examples:
- `PT18:MT`, `PT19:MT`, `I4:MT` (all Malta), each with empty/blocked returns
  and a hard `search_empty` termination.

### C. Deny-listed / MQA source contact (8)

The only place the answer reliably lives is on a deny-listed domain
(`data.europa.eu`, the MQA metadata-quality dashboard), which D24 blocks. The
agent correctly avoids citing the answer key, but with the answer fenced off it
cannot commit. These are almost all Quality-dimension percentage questions
whose authoritative figure is the MQA score.

Examples:
- `Q18:NO` (Quality) GT=`31-50%`. "none of the search snippets provide a
  specific percentage about how much metadata on data.norge.no uses DCAT-AP
  optional classes". That percentage is an MQA output.
- `Q9:MT` (Quality) GT=`yes`. Metadata-quality guidance question routed through
  the MQA surface.

### F1. Schema-invalid hard failure (5)

The agent produced output that failed schema validation
(`final_failure_reason = 'schema_invalid'`) and terminated. All five are
France pairs where the Researcher had a committed answer and reasoning but the
serialised response did not validate. A pure engineering fault, not a
reasoning or retrieval one.

Examples:
- `P10-a:FR`, `I4:FR`, `P20:FR`, each with substantive `answer_explanation`
  text but a `schema_invalid` termination.

### Z. Other (9)

Did not match a prior rule. Mostly Malta impact pairs with a committed answer
at 0.72 confidence and a "source_url not among search snippets" note that the
priority order did not route into D. Worth a manual glance but small.

## The "no" asymmetry

Splitting the abstentions by what the experts actually answered exposes a
structural limit, not a tuning problem.

| ODMI ground truth | Abstentions |
|---|---:|
| `no` (feature truly absent) | 279 |
| `yes` (feature present) | 243 |
| `i don't know` (experts also abstained) | 26 |
| percentage / other | 32 |

The experts answered `no` *more often* than `yes` among our abstentions. Many
of these are portal or process features that simply do not exist: no feedback
button, no RSS feed, no reuse-case section, no keyword monitoring. The swarm
searches, finds no evidence the feature exists, and abstains, because the
prompts forbid asserting a fact from absence of evidence. But for a `no`
answer, absence of evidence *is* close to the evidence. The swarm cannot
distinguish "the feature is absent" (a correct `no`) from "I could not find the
feature" (an honest abstain), so it abstains on both. Of the 279 GT-`no`
abstentions, 80 sit in E and 80 in G, the two largest categories, precisely
where a committed `no` would have matched the experts.

This is the single most actionable finding for accuracy: a meaningful fraction
of the abstention mass is the swarm declining to commit a `no` that it has
effectively already established by exhaustive non-discovery.

## Stratification

### By ODMI dimension

Rates use all finalised pairs as the denominator (pairs keyed by
question + country + experiment, so a pair re-run under several experiments is
counted per run).

| Dimension | Non-committed | Total runs | Rate |
|---|---:|---:|---:|
| Impact | 238 | 514 | 46.3% |
| Quality | 117 | 254 | 46.1% |
| Portal | 201 | 516 | 39.0% |
| Policy | 129 | 373 | 34.6% |

Quality and Impact abstain at the highest rate. Quality is the deny-list and
self-report dimension (its gold answers are MQA percentages or portal-admin
facts), and Impact is the "is there a process to monitor X" dimension whose
answers are rarely published. Policy abstains least: policy documents and
action plans are the most web-visible artefacts.

### Category by dimension

| Category | Policy | Portal | Quality | Impact |
|---|---:|---:|---:|---:|
| E verifier relevance | 29 | 43 | 29 | 62 |
| G below floor | 28 | 44 | 19 | 55 |
| I never committed | 7 | 39 | 8 | 19 |
| D evidence ungrounded | 19 | 10 | 10 | 27 |
| B fetch error | 3 | 20 | 15 | 13 |
| A thin web | 7 | 9 | 12 | 10 |
| F3 search-empty fail | 0 | 17 | 1 | 3 |
| C deny-list / MQA | 0 | 0 | 8 | 0 |
| F1 schema-invalid | 3 | 0 | 1 | 1 |

Reading the rows: the deny-list category C is wholly Quality, as expected.
Fetch errors (B) and search-empty failures (F3) concentrate in Portal, which is
where the WAF-protected national portals are probed directly. The "never
committed" category I is Portal-heavy: portal-feature questions ("does the
portal have X") are the hardest to answer from search snippets because the
feature is a UI element, not a document.

### By country

| Country | Non-committed | Total runs | Rate | Notes |
|---|---:|---:|---:|---|
| MT | 359 | 436 | 82.3% | data.gov.mt behind a 403 WAF; also bilingual (Maltese) |
| EE | 12 | 16 | 75.0% | small sample; portal returned a 403 in discovery |
| AL | 18 | 34 | 52.9% | low-resource language, thin web |
| HR | 27 | 59 | 45.8% | held-out headline run |
| NL | 177 | 664 | 26.7% | largest sample, most experiments |
| FR | 31 | 125 | 24.8% | strong portal, but Quality still fenced off |
| SE | 8 | 32 | 25.0% | held-out headline run |
| NO | 30 | 143 | 21.0% | |
| FI | 23 | 143 | 16.1% | |

Malta is the outlier and the reason is mechanical: the national portal returns
403 to the fetcher, so the bulk of Malta pairs degrade into fetch-error,
search-empty, and below-floor abstentions. This compounds the known Malta
bilingual confound (`docs/EXPERIMENTS_MALTA_FAILURES.md`): half the open-data
estate is in Maltese, and the half that is in English sits behind a WAF. Malta
abstentions should be read as a portal-access artefact, not a reasoning result,
and the swarm's true reasoning quality is better read off NL / NO / FI / FR /
SE, where rates sit at 16 to 27%.

### By experiment

The non-committed pairs span eleven experiment tags. The largest are
`exp19_verifier_search_multicountry` (146, mostly Malta), the unattributed
ad-hoc runs (99, mostly FR/NO/EE), `exp20_chaining_committing` (98, Malta),
`retry_chaining_mt_v1` (88, Malta) and `exp21_frozen_headline` (58, the
held-out HR/FI/SE). The Malta-heavy verifier-search and chaining experiments
dominate the count, which is consistent with the country picture above.

## What this tells us

### (i) What each category implies about the system

- **E + G together are 53% of all abstentions** and both reduce to the same
  thing: the Researcher reached a candidate answer the gates would not certify.
  E is the Verifier ruling the evidence off-target; G is the answer-confidence
  staying under the floor. The system is conservative by construction, and that
  conservatism is where the abstention mass sits. This is the price of the
  no-hallucination contract: the same gates that keep false positives down
  (FAILURE_MODES Part A) push borderline pairs into abstention.
- **The abstention is mostly a web-availability problem, not a reasoning
  problem.** 64% of pairs carry an explicit "the snippets do not contain the
  evidence" statement, and the high-abstention dimensions (Quality, Impact) are
  exactly the ones whose answers are not on the open web (MQA percentages,
  internal monitoring processes). The swarm reasons fine; the evidence is not
  reachable. This is FM-19 quantified.
- **A real engineering tail exists and is cheap to remove.** Fetch errors (B,
  51), search-empty failures (F3, 21) and schema-invalid failures (F1, 5) are
  77 pairs, 13% of the union, that are operational, not epistemic. The 403 wall
  on data.gov.mt alone accounts for most of B and F3.
- **The deny-list does its job but costs Quality coverage.** Category C is
  small (8) only because most Quality questions never get far enough to cite the
  MQA; the catalogue path (D30) is the intended answer for those, not web
  search. C is the visible edge of a larger fenced-off region.
- **The abstentions are misses, not honest unknowns.** 95.5% have a committed
  expert answer. The swarm is not declining the truly unanswerable; it is
  declining answerable questions because the evidence route is blocked, walled,
  or below threshold. This is the honest framing for the writeup: high
  abstention is a recall ceiling imposed by source availability and gate
  conservatism, not a sign the questions are impossible.

### (ii) How to detect each category programmatically

Every category here is derivable from columns already in the DB, which means
the swarm could self-label its own abstentions at finalisation:

- **A / F3 thin-web:** `search_snippets` empty/null on all attempts, or
  `final_failure_reason LIKE '%search_empty%'`.
- **B fetch error:** researcher `failure_mode = 'url_unreachable'`, or a regex
  for HTTP status markers (`status 0`, `40x`, `50x`, `timeout`) over the
  `notes` / `raw_response` text.
- **C deny-list:** substring scan of `fetched_urls` and `source_url` for
  `data.europa.eu`, `/mqa/`, `metadata-quality`. Already enforced upstream;
  here it is a post-hoc label.
- **D evidence ungrounded:** any verifier row with
  `substring_check_result = 'fail'` on a pair whose researcher committed an
  answer, or the literal note "source_url not among search snippets".
- **E verifier relevance:** last verifier `verdict = 'fail'` with
  `substring_check_result = 'pass'` (quote on page, ruled off-target) on a pair
  with a committed researcher answer.
- **G below floor:** `MAX(answer_confidence)` across researcher attempts
  `< 0.65` with a committed candidate. Directly the D37 floor.
- **I never committed:** every researcher `answer` in
  (`inconclusive`, `other`, null).
- **F1 schema-invalid:** `final_failure_reason LIKE '%schema_invalid%'`.
- **The "no" asymmetry** is detectable without ground truth as a *risk flag*:
  a pair where the Researcher's explanation contains absence language ("no
  evidence of", "does not appear to", "could not find any") and the candidate
  answer leans `no` is a probable should-have-committed-no. This does not peek
  at the gold answer; it reads the agent's own stance.

A natural next artefact is a `phase2_abstention_label` view that runs this
classifier as SQL and tags every non-committed pair live, so the dashboard can
show the abstention mix per run without a separate script.

### (iii) Uses of this taxonomy

**For the dissertation.** This is the abstention half of the evaluation story
and pairs directly with the false-positive register in
`docs/FAILURE_MODES.md`. The headline numbers are reportable as-is: a 35.0%
non-committed rate, of which 95.5% are misses against expert answers, driven by
a 64% web-evidence-gap rate that is heaviest in the Quality and Impact
dimensions. The "no" asymmetry is a clean, defensible structural finding: the
swarm cannot assert a negative from absence of evidence, so it abstains on a
large block of correct `no` answers. That is an honest negative result of the
kind the methodology explicitly counts, and it explains a recall ceiling
without hand-waving. The Malta caveat (an 82% abstention rate that is a WAF and
bilingual artefact, not a reasoning result) is exactly the sort of confound an
examiner will probe, and naming it pre-empts the question.

**For improving the system.** The taxonomy ranks the fixes by payoff:
1. The fetch-error and search-empty tail (B + F3, ~72 pairs, all operational).
   A Playwright fetch for WAF-403 portals, starting with data.gov.mt, recovers
   most of it. Cheap, mechanical, no epistemic risk.
2. The "no" asymmetry (E + G with GT-`no`, 160 pairs). A bounded,
   evidence-disciplined rule that lets the swarm commit `no` after a documented
   exhaustive non-discovery (a fixed set of targeted "does X exist" queries all
   returning nothing) would convert a large abstention block into matches,
   *if* it can be done without inflating false positives. This is the one to
   prototype behind a flag and measure against ground truth, never to hard-wire.
3. The deny-list / MQA region (C plus the Quality slice generally). The
   catalogue path (D30) already exists for exactly these; widening its country
   coverage retires this category rather than tuning it.
4. Confidence-floor calibration (G). 146 pairs abstain on the 0.65 floor. An
   empirical calibration of that threshold against ground truth (the FM-26
   mitigation) would show whether the floor is set where it should be, and
   whether a per-dimension floor beats a single global one.

The taxonomy also gives the with/without-Verifier ablation a target: categories
D and E are precisely the pairs the Verifier turns from a (possibly correct)
commit into an abstention. Running those pairs with the Verifier disabled and
scoring against ground truth would quantify how much real recall the Verifier
costs versus how many false positives it prevents, which is the central
self-verification trade-off the dissertation is trying to measure.

## Developed synthesis: what to do with the abstention findings

This taxonomy and the expert evidence-gap report (`docs/EXPERT_EVIDENCE_GAP.md`)
read the same population through different lenses and reach what looks like
opposite conclusions about the `no` abstentions. Resolving that apparent
conflict is the most useful thing the two documents do together.

### The `no` abstention: two readings, one resolution

This file calls the `no` asymmetry "the single most actionable finding for
accuracy": of the GT-`no` abstentions, 80 sit in category E and 80 in G, about
160 pairs where a committed `no` would have matched the experts. The
expert-evidence report reads the same pairs and calls them correct behaviour:
55 of the 78 distinct GT-`no` abstained pairs carry no positive assessor
justification, so there is no artefact to find and abstaining is right.

Both are true because GT-`no` is not one kind of question. It splits cleanly:

- **Publicly-visible-if-present.** "Does the portal have a feedback button / an
  RSS feed / a use-case section?" If the feature existed it would be on the
  portal, so a thorough search that finds nothing is good evidence of absence.
  Here a committed `no` from exhaustive non-discovery is epistemically sound, and
  these are the pairs this file is pointing at.
- **Internal-practice / self-report.** "Do you monitor reuse / run API analytics
  / have an impact methodology?" Absence of a public page says nothing, because
  the practice can exist unpublished inside the portal team. These are the pairs
  the expert-evidence report fences off as structural, and a `no` here would be
  a guess, not a finding.

The resolution is that any rule which commits `no` from non-discovery must be
gated on question type, allowed only for the publicly-visible-if-present set and
never for the internal-practice set. That single gate turns the conflict into a
bounded, defensible design and is the honest framing for the writeup: the swarm
under-commits `no` on questions where absence is evidence, and correctly abstains
on questions where it is not.

### If the commit-`no` rule is greenlit (direction i): design sketch

Not built; the decision to spend on it is open. Pre-registration sketch so it is
ready if chosen:

- Scope: only questions on a fixed allow-list of publicly-visible-if-present
  items (portal-feature PT questions, published-document Policy questions),
  derived from the question bank, never the I-series, PT-usage, or process
  Quality items.
- Trigger: a documented exhaustive non-discovery, a fixed battery of targeted
  "does X exist" queries (including native-language and portal-scoped) all
  returning nothing, logged as the evidence for the `no`.
- Guard: a hard false-positive ceiling on negative golds, measured against GT
  before adoption; the rule abstains rather than commit whenever the battery is
  incomplete or any query is inconclusive.
- Endpoint: per-class recall on GT-`no` and the negative-gold FPR, paired
  against the current abstain-always behaviour. Adopt only if `no`-recall rises
  materially with FPR held under the ceiling.

This relaxes the no-hallucination stance in one narrow, audited place, so it is
the one to prototype last and behind a flag, never to hard-wire.

### Recommended order for the system fixes

For the open i/ii/iii decision, cheapest and least risky first:

1. **(ii) Playwright for data.gov.mt.** Malta's 82% abstention is mostly a 403
   WAF fetch artefact (category B and F3), not reasoning. Clearing it
   de-confounds ~72 MT pairs and cleans every downstream abstention and accuracy
   number, including this taxonomy's and the expert-gap report's. Mechanical, no
   epistemic risk, highest information per pound. Do first.
2. **(iii) Recalibrate the 0.65 floor.** 146 pairs abstain on the floor
   (category G). An empirical calibration against GT (FM-26) shows whether the
   floor sits where it should and whether a per-dimension floor beats one global
   value. Low risk, no stance change.
3. **(i) Commit-`no` rule.** Highest accuracy reward (~160 pairs) but the only
   one that touches the core stance, so last, gated as above.

### What the dissertation can claim from this (his to write up)

Raw claims, with the supporting numbers, not finished prose:

- Non-committed rate ~35% of finalised pairs; 95.5% of those are misses against
  a committed expert answer, so abstention is a recall ceiling, not the
  questions being impossible.
- 64% of non-committed pairs carry an explicit "the snippets do not contain the
  evidence" note: the ceiling is source availability, heaviest in Quality and
  Impact, the dimensions whose answers are MQA percentages or internal processes.
- The `no` asymmetry is a structural finding, resolved by the question-type
  split above; report it as under-commitment on publicly-visible questions and
  correct abstention on internal-practice ones.
- The Malta 82% figure is a WAF and bilingual confound, not reasoning; true
  reasoning quality reads off NL/NO/FI/FR/SE at 16 to 27%. Naming it pre-empts
  the examiner.
- This is the abstention half of the evaluation; it pairs with the
  false-positive register in `docs/FAILURE_MODES.md` and is the recall context
  for the EXP-21 headline.

## Reproduce

```bash
uv run python evaluation/abstention_taxonomy.py
# prints category counts, stratification, GT split
# writes evaluation/abstention_records.csv (one row per non-committed pair)
```

The classifier is deterministic and reads only `phase2_final`,
`phase2_researcher_runs`, `phase2_verifier_runs`, `phase2_adjudications` and
`ground_truth`. It does not write to the DB.

## Change log

| Date | Change |
|---|---|
| 2026-06-24 | File created. 580-pair non-committed population classified into ten categories from a read-only trail walk. |
| 2026-06-24 | Added the developed synthesis: resolved the `no`-abstention conflict with the expert-evidence report via a question-type gate, sketched the gated commit-`no` design, recommended the i/ii/iii fix order, and listed the dissertation claims. |
