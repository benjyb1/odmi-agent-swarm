# The Expert Evidence Gap: where ODMI assessors find the answers we abstain on

Diagnostic, read-only. Produced 2026-06-24 against `data/odmi.db`. No pipeline
code was changed and no expert answer or expert source was written into any
table the swarm reads. This document exists for our understanding of the
abstention pattern and must not bleed back into the swarm (D24).

Snapshot and scope. The integers below are a single read taken on 2026-06-24
while EXP-21 was still finalising the held-out countries (HR, FI, SE). They are
a snapshot, not a constant: a later read moves them by a few pairs. The
verified-exact figures held on the day were 4,373 populated explanations, 553
inconclusive / 65 agent-failure / 33 overlap, and 249 distinct abstained pairs;
re-running the generator (see Reproduce) on a later DB returns the same shape on
a larger denominator. The population also pools dev countries (NL, MT, NO, FR,
AL) with the held-out set and one earlier ad-hoc country (EE), so it reads the
abstention pattern, not the headline result. The clean writeup should report the
pattern on the dev set, with the held-out countries as confirmatory only after
EXP-21 completes and is frozen. None of this peeks at held-out answers in a way
that reaches the swarm: the join is read-only and stays behind the D24 firewall.

## Question

For the (question, country) pairs the swarm keeps abstaining on, how did the
ODMI assessors actually answer, and where did they get their evidence? Are we
structurally missing an evidence channel the assessors rely on?

Framing that governs the whole analysis: ODMI answers are produced by Capgemini
as a third-party assessor, not by a self-assessment survey. The assessor's
evidence sits in `ground_truth.explanation` (4,373 of 5,148 rows populated).
The one exception is a portion of the Quality dimension, which is country
self-report.

## Headline answer

Yes, there is one dominant missing channel, and it is mostly structural rather
than findable. Across the pairs we abstain on, the assessor's evidence is, in
order of frequency:

1. A first-person assertion of internal practice with no public artefact
   ("The NDP monitors the use of APIs requests from the portal"). Unreachable
   from the open web by construction.
2. A bare assertion of absence, when the answer is "no". An expert records
   "no" with no positive evidence, because none is required. Nothing for us to
   find.
3. A deep-linked public source off the main portal: a national-portal
   sub-page, a national-language government document or PDF, a LinkedIn post, a
   Google Form, a university research page.

Channels 1 and 2 are structural: the evidence is not on the web in a form any
search could reach, because it is an internal-operations claim or an assertion
of non-existence. Channel 3 is findable in principle but sits where our
DIY (Serper + trafilatura) pipeline is weakest: deep, off-portal, and
frequently in a national language.

The single clearest channel we are missing is **the assessor's privileged,
first-person knowledge of a country's internal open-data operations** (process,
methodology, monitoring, team practice), recorded as plain prose with no
citation. This is the questionnaire's self-report surface, and it extends well
beyond the Quality dimension the methodology already flags as self-report.

## What the swarm actually abstains on

Finalised results live in `phase2_final`. Across 1,669 finalised rows, 585 did
not commit: 553 returned `final_answer='inconclusive'` (an abstention) and 65
ended `terminal_status='agent_failure'` (33 of those are also `inconclusive`).
Deduplicated to distinct question x country, that is 249 abstained pairs over
nine countries (MT 72, FR 31, NO 30, HR 27, NL 27, FI 23, AL 14, SE 13, EE 12).

Non-commit rate is broadly flat across the four ODMI dimensions, which already
argues against a single dimension-specific cause:

| Dimension | Pairs | Abstain | Fail | Non-commit | % |
|---|---|---|---|---|---|
| Quality | 254 | 102 | 5 | 104 | 40.9 |
| Impact | 519 | 193 | 12 | 199 | 38.3 |
| Portal | 516 | 166 | 41 | 186 | 36.0 |
| Policy | 378 | 92 | 7 | 96 | 25.4 |

The questions we abstain on most are not spread evenly across question types.
They cluster on items that ask about a country's **internal practice**, phrased
in the first person and addressed to the country, with the giveaway "If yes,
please describe **your** process / **your** approach":

| Question | Dim | Non-commit | Text (abridged) |
|---|---|---|---|
| PT24 | Portal | 19/20 | Do you run analytics on API usage? |
| I8-b | Impact | 18/29 | (reuse-understanding activity) Surveys |
| I8-d | Impact | 17/27 | (reuse-understanding activity) Other |
| P6 | Policy | 17/30 | Does the strategy outline measures to incentivise citizen-generated data? |
| Q20 | Quality | 15/19 | Do you investigate the common causes of lack of DCAT-AP compliance? |
| I22 | Impact | 15/30 | Is any data on open data's environmental impact available? |
| I6 | Impact | 14/26 | Do you have a methodology to measure open data impact? |
| PT9 | Portal | 13/29 | Does the portal offer per-dataset feedback (button/comments)? |
| Q4 | Quality | 12/20 | Do you ensure published data covers the full time series? |
| I2 | Impact | 10/25 | Are there processes to monitor the level of reuse? |

These are not "find a fact on a web page" questions. They are "describe what
your organisation does internally" questions. That is the structural mismatch
the rest of this document quantifies.

## How the assessors answered the pairs we abstain on

Joining the 249 abstained pairs to `ground_truth.response`:

| Assessor answer | Pairs |
|---|---|
| yes (any tier) | 135 |
| no | 78 |
| i don't know | 12 |
| percentage band / other | 24 |

Two things stand out. First, 78 of the abstentions are pairs the assessor
answered **no**. A "no" is an assertion of absence; ODMI needs no positive web
evidence to record it. 53 of those 78 carry no substantive justification at
all. There is nothing for the swarm to find, and the swarm's adjudication rule
explicitly refuses to convert "we could not find it" into "no" (see the swarm
reasoning quoted below). Half our abstentions are therefore the system behaving
correctly against an unfalsifiable target.

Second, of the 135 the assessor answered **yes**, 129 carry an explanation,
but only 76 of those cite any URL at all. The other 53 are prose-only, and
48 of the 129 (37%) are written in the first person ("our", "we", "us").

## Source-type classification of the 129 assessor "yes" explanations

Programmatic extraction of every URL from the explanation text, then
classification by the kind of source:

| Source type | Count | What it is |
|---|---|---|
| Prose-only, no URL | 53 | First-person assertion of internal practice. No artefact to fetch. |
| National-portal deep-link | 47 | A sub-page of the national portal (community pages, use-case sections, dataset pages). |
| Other web domain | 13 | Civic-tech, statistics-office, sector bodies, NGO pages. |
| Government doc / legislation | 9 | Legislation registers, ministry roadmaps, national gazettes. |
| Code repository | 3 | University / project domains and GitHub. |
| Google Doc or Form | 2 | A live survey form standing in as the evidence. |
| Social media | 2 | A LinkedIn activity post. |

Seven of the cited sources are PDFs (Finnish circular-economy report, the
Bothorel report on French data policy, a Cour des comptes review, two
Norwegian regjeringen.no PDFs).

### Verbatim examples (the load-bearing ones)

Prose-only internal-operations assertion, no URL, the swarm cannot reach it:

> I2 / MT (assessor: yes): "The NDP monitors the use of APIs requests from the
> portal."

> PT24 / MT (assessor: yes): "API usage is being monitored by the underlying
> data sharing platform. All APIs from the Public Service are hosted on the
> Interoperable Layer which has its own monitoring capability over and above
> the analysis of the Portal. The insights are analysed by IT team to enable
> improvements."

Off-portal, deep-linked public source, findable in principle but exactly where
DIY search is weak:

> I8-d / FR (assessor: yes): "The French open data team carries out social
> media campaigns ... : https://www.linkedin.com/feed/update/urn:li:activity:7310984416070123520
> ... https://forum.data.gouv.fr/"

> I8-b / FR (assessor: yes): "One example of a survey conducted by the National
> Institute for Geographic and Forestry Information ... : https://tally.so/r/3xROXy"

The human assessor finding the question ambiguous, in their own words:

> I22 / SE (assessor: no): "COMMENT: We have obviously misinterpreted this
> question, and we do not currently have that kind of data. However, we are
> planning to start collecting this type of data when we launch an updated
> version of the Swedish dataportal later this year ... Therefore we have ...
> our reply to NO."

For contrast, the swarm's own reasoning on I2 / MT, which shows the abstention
is principled, not a retrieval failure:

> "The Researcher's 'no' answer is based entirely on absence of evidence rather
> than positive evidence of absence. The cited sources ... are completely
> irrelevant to whether the Maltese [portal monitors reuse]. ODMI adjudication
> rules explicitly prohibit converting 'we could not find it' into 'no'."

The assessor knew, from inside the Maltese portal team, that the NDP monitors
API requests. The swarm searched the open web, found no public page that says
so, and correctly refused to guess. The gap is not retrieval quality. The gap
is that the fact was never published.

## Recurring domains

258 URLs across the abstained explanations, 97 distinct domains. The recurring
ones are national open-data portals and national government / legislation
sites, not generic web sources:

| Domain | URLs | Kind |
|---|---|---|
| data.gouv.fr | 35 | FR national portal |
| data.overheid.nl | 19 | NL national portal |
| datalandsbyen.norge.no | 15 | NO portal community |
| portal.data.gov.mt | 8 | MT national portal |
| avaandmed.eesti.ee | 8 | EE national portal |
| legifrance.gouv.fr | 8 | FR legislation |
| legislation.mt | 8 | MT legislation |
| hri.fi | 7 | FI regional portal (Helsinki) |
| regjeringen.no | 7 | NO government |
| avoindata.fi | 6 | FI national portal |
| github.com | 6 | Code |
| data.norge.no | 5 | NO national portal |
| ouverture.data.gouv.fr | 5 | FR portal sub-domain |

By top-level domain the cited evidence is overwhelmingly national: .fr 77,
.no 45, .mt 24, .nl 19, .hr 19, .fi 18, .ee 10, .se 8, against .com 16 and
.org 4. At least 70 of the 258 URLs carry an explicit non-English language path
or sit on a national-language source (legifrance, narodne-novine, regjeringen,
ilmatieteenlaitos, klimatanpassning, boverket). The evidence channel is
national-language and portal-adjacent, not English and not general-web.

## Findable versus structural

Splitting the 135 assessor-"yes" abstentions by whether the evidence is in
principle reachable:

| Category | Pairs | Reachable from open web? |
|---|---|---|
| Cites at least one public URL | 76 | Yes, in principle (findable-but-missed) |
| Prose-only first-person self-report | 53 | No (structural) |
| Bare "yes", no explanation | 6 | No (structural) |

Adding the 78 "no" abstentions, of which 53 carry no positive justification:
those are structural too, because there is no artefact that confirms an absence.

Rolled up across all 249 abstained pairs:

- Structural (no public artefact exists to be found): the 59 prose-only or
  bare "yes" cases, plus the 53 unjustified "no" cases, plus the 12 "i don't
  know" cases. About 124 pairs, roughly half.
- Findable-but-missed (a public URL exists that we did not reach): the 76 "yes"
  pairs that cite a URL, plus some of the 25 "no" pairs that cite supporting
  context. Order of 80 to 100 pairs.

The split is therefore close to even, but the two halves call for different
responses. The findable half is an engineering problem (reach deep, off-portal,
national-language sources). The structural half is not a bug at all; it is the
correct behaviour of an evidence-grounded system pointed at claims that have no
public evidence.

## Are we structurally missing an evidence channel, and which one?

Yes. The channel is the assessor's first-person, privileged knowledge of a
country's internal open-data operations, recorded as uncited prose in the
questionnaire. "The NDP monitors API requests." "We've added a survey module."
"Digg conducted 8 in-depth interviews." "The insights are analysed by the IT
team." None of these is on a web page. The assessor either is the portal team
or interviewed it, and the questionnaire is the only place the claim is written
down. This channel powers the I-series (impact awareness and measuring reuse),
the PT-usage items (PT24, PT25), and the process Quality items (Q1, Q4, Q9,
Q20, Q23). It is wider than the Quality self-report carve-out the methodology
currently names.

We are also weak on, but not structurally barred from, the deep, off-portal,
national-language public channel: LinkedIn posts, Google Forms, sub-domain
portal pages, ministry PDFs, national gazettes. That is the findable-but-missed
half, and it is a retrieval-coverage problem.

We are not missing the things we already do well: top-level national portal
pages and legislation registers appear in the explanations and are within
reach; the abstentions concentrate away from them.

## Implications

### (a) For the dissertation writeup

- Reframe a large share of abstentions as correct behaviour, not failure. Half
  the abstained pairs have no public evidence (internal-operations prose or an
  unjustified "no"). An evidence-grounded swarm should abstain there. This is a
  positive result for the D35/D37 abstention design and the "absence of
  evidence is not evidence of absence" rule, and it is a direct, quantified
  answer to RQ4 (which question categories are beyond reach and why).
- Name the structural ceiling precisely. ODMI's own instrument mixes
  assessor-verifiable items with self-report items that are not verifiable from
  the open web, and the self-report surface is broader than the Quality
  carve-out. The I-series and the portal-usage and process items are
  effectively self-report regardless of dimension label. This is a finding
  about the ODMI methodology, not only about our system. The I22 / SE comment
  ("We have obviously misinterpreted this question") shows the human assessors
  hit the same ambiguity, which strengthens rather than weakens the point.
- Separate the two failure halves in the failure-mode taxonomy. "Irretrievable
  because never published" (structural) and "retrievable but off-portal /
  national-language and missed" (coverage) are different modes with different
  fixes. Reporting them merged would understate how much of the gap is a
  property of the target rather than of the swarm.
- Use the national-language, off-portal evidence finding to support RQ3. The
  cited evidence is overwhelmingly national-TLD and frequently non-English,
  which is consistent with language and retrieval depth driving abstention in
  the findable half.

### (b) Concrete, testable ways to reach the missing channels (no leakage)

These target only the findable-but-missed half. The structural half cannot and
should not be closed by retrieval; closing it would mean manufacturing answers,
which is the failure the whole project is built to avoid. None of the
following touches ODMI publications or writes expert answers into the swarm;
they widen retrieval over independent public sources only, and all remain
behind the D24 deny-list.

1. Deep-link the national portal, do not stop at its front page. Many
   "yes" explanations point to fixed sub-paths: use-case sections, community
   pages, per-dataset pages, forum and post sub-domains (forum.data.gouv.fr,
   data.overheid.nl/community, datalandsbyen.norge.no). A portal-aware
   crawler that enumerates these known sub-sections per country would convert a
   measurable slice of the 47 portal-deep-link pairs. Testable: re-run the
   abstained portal-deep-link pairs with sub-section enumeration on, measure
   commit-rate lift against the held-out rule.
2. Add a national-language query arm. The cited domains are national-TLD and
   often non-English. Issue search queries in the country's primary language
   (and, for bilingual estates such as Malta, both languages) and let
   trafilatura extract the national-language page before any translation step.
   Testable as a DIY-internal retrieval arm under the existing experiment
   protocol; it is a recall question, not a provider question, so it respects
   the DIY-only decision.
3. Whitelist a small set of off-portal source types the assessors actually use:
   LinkedIn activity posts, Google Forms / tally.so survey links, national
   statistics offices, civic-tech domains (imamopravoznati.org, parlametar.hr).
   Probe these explicitly when a question is about reuse activity or user
   research. Testable: per-question-family source-type routing, measured on the
   I8-series and PT-usage abstentions.
4. Improve PDF reach. Seven "yes" pairs rest on ministry / audit-office PDFs.
   Confirm the fetch pipeline extracts text from large government PDFs
   (regjeringen.no content-asset PDFs, info.gouv.fr reports) and add them to
   the candidate set when a strategy or report is referenced.
5. Detect and label the structural cases rather than chasing them. When a
   question is a known internal-practice item (the I-series, PT24/PT25, the
   process Quality items) and no public artefact is found, record an explicit
   "no public evidence channel exists" disposition distinct from a retrieval
   failure. This does not change the answer; it improves the honesty of the
   reporting surface and stops these pairs being counted as the same kind of
   miss as a truly findable one. Testable by re-classifying the current
   abstentions and checking the split against this document's structural set.

The order that buys the most: 2 (national-language queries) and 1 (portal
sub-section enumeration) together address the bulk of the 76 findable pairs;
5 (structural labelling) reframes the other half without pretending to answer
it.

One correction to that order, found on a later read. The native-language query
arm (item 2) is not a new build: the Researcher already generates a native query
alongside the English one (`phase2_researcher_query_gen` v2), and AL pairs
verifiably issue well-formed Albanian queries. So the lever for the findable half
is no longer "add native queries" but "measure whether the native queries we
already issue actually help, and reach native-language pages once fetched". The
foreign-language experiment is therefore an ablation of the existing behaviour,
designed in `docs/EXPERIMENTS_FOREIGN_LANG.md`, not a feature addition.

## Reproduce

```bash
uv run python evaluation/expert_evidence_gap.py
# prints ground-truth coverage, the non-committed population, distinct abstained
# pairs by country, non-commit by dimension, the assessor-answer split, a
# source-type classification of the yes-tier explanations, recurring domains,
# and the findable-vs-structural split.
uv run python evaluation/expert_evidence_gap.py --db /path/to/odmi.db
```

The generator is deterministic and strictly read-only (opens the DB with
`mode=ro`). It reproduces the population, dimension, assessor-answer and
findable-vs-structural numbers exactly for a given DB state. Two honest caveats
on the source-type table: the script counts URLs, while the table above counts
pairs by their dominant source, so the integers differ by unit; and the
portal / government / other split is a transparent host-and-path heuristic
(see `PORTAL_HOSTS` and `classify_url`), not the manual judgement used for the
table. The script is the reproducible companion; the prose table is the curated
read.
