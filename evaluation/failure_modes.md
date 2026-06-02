# Failure-mode analysis: swarm answers that disagree with ODMI ground truth

Diagnostic pass over every finalised main-run pair (`experiment_id IS NULL`)
that does not match ODMI's 2025 published answer. Match status uses
`_MATCH_STATUS_SQL` from `dashboard/lib/db.py` verbatim. No code or data was
changed. Companion file: `evaluation/failure_modes.csv` (one row per failed
pair).

## The failure set

Of 149 finalised main-run pairs:

| match_status | n |
|---|---|
| match | 101 |
| differ | 43 |
| no_swarm_answer | 5 |
| near_match | 0 |
| no_ground_truth | 0 |

So 48 failed pairs: 43 `differ` plus 5 `no_swarm_answer`. There are no
`near_match` rows, so the adjacent-band logic never fires in the main runs.

Two facts about the failure set shape everything below.

First, the swarm answer is almost always `inconclusive`. Of the 43 `differ`
pairs, 38 are `inconclusive`, 4 are `no`, and 1 is `yes`. ODMI's answer is
`yes` (or a positive band) in 41 of 43. The swarm is not picking the wrong
label from a menu. It is declining to commit to a label that ODMI did commit
to.

Second, the failures concentrate by country. FR contributes 36 of 48 (FR has
125 of 149 pairs) and EE contributes 12 of 16 EE pairs. EE fails almost
everywhere it runs. DE, NL and RO contribute zero failures between them, but
they only have 8 pairs, so that is not yet a signal.

## A receipts gap that constrains this analysis

The brief asked me to judge, from cached fetched content, whether the correct
evidence was physically in hand. For the main runs that is mostly not possible,
and that is itself a finding worth stating plainly.

`search_cache_fetch` holds 104 rows (96 from the D29 DIY backend, 7 httpx, 1
playwright). Only 38 of the 1,228 fetched-URL entries across the failure set
(3.1%) are present in it. `search_cache_snippet` is keyed by query hash and
covers 36 of 579 main-run queries, nearly all from the DE experiment. The
main runs used Tavily, whose snippets were consumed inline and never persisted:
`raw_response` stores only the model's own output JSON, and
`search_provider_calls` is empty on the rows I checked.

So for the main runs there is no faithful record of the raw retrieved text. The
trail I can replay is the agent's self-reported `evidence_quote`, `notes` and
`failure_mode`, the URLs it listed, the Verifier's `substring_check_result`,
and ODMI's own `explanation` (which frequently names the exact source URL). I
classified on that basis, plus one live web check, and I flag confidence
honestly per row. This gap should be closed before the next batch: persisting
retrieved snippets is a precondition for the reproducibility the project
otherwise holds itself to.

## Codebook

Seed modes I kept (sometimes renamed or merged):

- **evidence_absent_or_self_report** (seed: evidence absent from open web). The
  gold answer is the country's own questionnaire narrative about an internal
  practice, a survey, a forum, a dashboard, or a figure that needs catalogue
  computation. Often there is no retrievable public artefact. The
  catalogue-derivable subset (Q12, Q17, Q18 and EE Q12 here) is a named
  sub-type: the answer is a percentage that has to be computed over the
  catalogue, not searched for.
- **ground_truth_contested** (seed). Swarm well sourced and plausibly right;
  ODMI loose, stale, or a self-report the swarm contradicts. Candidate swarm
  win.
- **selection_or_interpretation_miss** (merge of seed selection miss and
  interpretation miss). A public artefact existed and was reachable, often
  with its URL printed in ODMI's own explanation, but the swarm gave up or read
  it too narrowly. Merged because, without the fetch cache, I cannot reliably
  separate "fetched the wrong page" from "read the right page wrongly".
- **inconclusive_collapse** (seed). The swarm produced a supportable label at
  some retry, then abandoned it to `inconclusive`, and the abandonment was not
  driven by the substring gate.
- **format_failure** (seed). Answer invalid or out of the allowed set. Covers
  the 5 `schema_invalid` no_swarm_answer pairs and PT37 (a binary `yes` emitted
  for an ordinal question).

Seed modes I did **not** use as written: "search miss" collapsed into
selection_or_interpretation_miss because I cannot prove a source was never
fetched without the cache; the seed "inconclusive collapse" split, with most of
its mass moving into the new substring-gate mode below.

New modes I added (see next section).

## Failure types we did not anticipate

These are the more important part of the story. The headline failures are not
about query generation at all. They are about the verification and
finalisation machinery throwing away answers the swarm had already found.

### N1. verifier_substring_gate_collapse (10 pairs, primary)

The Verifier runs a verbatim substring check: it tries to find the
Researcher's quoted passage inside the cited page. When the check fails it
tends to reject (`verdict=fail`), the loop retries, and the answer decays to
`inconclusive`.

The check fails almost all the time. Across every main-run Verifier round the
result is 187 fail, 94 pass, 6 not_attempted. A 66% failure rate, on matched
pairs too. The reason is structural: the pages were not re-fetched (or returned
403), and a Tavily snippet is rarely a verbatim substring of the live page. So
the gate is not testing whether the evidence is real. It is testing whether a
snippet can be re-matched against text the system does not hold, and the answer
is usually no.

The clearest case is PT10 (EE). The Researcher found the Estonian portal's own
source code at retry 1, with `dataset-rating.entity.ts` and `metadataRating`,
and answered `yes`. ODMI confirms datasets can be rated when logged in. The
Verifier rejected it on the substring check, the loop reverted to
`inconclusive`, and that is the final answer. I11 (FR) is the same shape: the
Researcher answered `yes` on the public reuse taxonomy at
`data.gouv.fr/fr/reuses/`, the substring check failed, and it flipped to `no`.
The Verifier's own counter-evidence cited that exact page.

This mode is invisible to both levers on the table. Diverging the queries
(lever A) does not matter when the answer was already found. Telling the
Researcher which labels failed (lever C) does not matter when the rejection was
a verification artefact, not a wrong label.

### N2. adjudication_propagation_loss (4 pairs, primary)

In four pairs the Adjudicator computed the ODMI-correct answer and the pipeline
then wrote `inconclusive` to `final_answer` anyway.

The cause is in `scripts/run_coordinator.py:973-990`. On `verifier_correct`
the final output is synthesised from the Verifier's answer, not from
`adjudicator_answer`. On `escalate_human` and on the `researcher_correct`
branch the code takes the last Researcher output. In all of these the
`adjudicator_answer` field is populated but never used. So:

- I16 (EE): adjudicator_verdict `verifier_correct`, adjudicator_answer `yes`,
  final `inconclusive`.
- I17 (EE): same.
- P26-b (FR): same.
- PT14 (FR): adjudicator_verdict `researcher_correct`, adjudicator_answer
  `yes`, but the last Researcher retry had decayed to `inconclusive`, so the
  code took that.

These are free wins lost to plumbing. The swarm reached the right answer and
discarded it on the way to the database. No lever is involved; this is a one
function fix.

### N3. zero_weight_descriptive (1 primary, 7 pairs flagged)

Seven `differ` pairs sit on questions with `max_score=0`: the I8 and I9 Impact
sub-questions and P14 (EE). These are descriptive or contextual items. I8-d is
literally the question text "Other" with scoring yes=0/no=0. A swarm-vs-ODMI
disagreement here moves no score. Counting them as errors overstates the
failure rate. One pair (I8-d) has nothing else going on and is classified here
as primary; the rest carry it as a contributing flag.

### N4. fetch_blocked_403 (contributing, 10 pairs)

Estonian government hosts (`riigiteataja.ee`, ministry PDF stores) and some FR
pages returned 403 to the fetcher (`failure_mode=url_unreachable`). The
evidence exists but the current fetch stack cannot reach it. This is the main
reason EE collapses: the law or standard ODMI cites is real and public, but the
fetcher is locked out, and then the substring gate finishes the job. Recorded
as a contributing factor, not a primary mode, because it co-occurs with N1 or
with evidence_absent.

## Counts

Primary mode, all 48 failed pairs:

| primary_mode | n |
|---|---|
| evidence_absent_or_self_report | 19 |
| verifier_substring_gate_collapse | 10 |
| format_failure | 6 |
| selection_or_interpretation_miss | 6 |
| adjudication_propagation_loss | 4 |
| zero_weight_descriptive | 1 |
| ground_truth_contested | 1 |
| inconclusive_collapse | 1 |

By dimension (primary mode):

- Impact (11): 5 evidence_absent, 3 substring_gate, 2 propagation_loss, 1 zero_weight.
- Policy (9): 3 evidence_absent, 3 selection_miss, 2 substring_gate, 1 propagation_loss. Plus 3 format_failure no_swarm pairs are Policy.
- Portal (12): 4 substring_gate, 3 evidence_absent, 1 propagation_loss, 1 contested, 1 inconclusive_collapse, 1 format_failure.
- Quality (12): 8 evidence_absent, 3 selection_miss, 1 substring_gate. Plus 1 format_failure no_swarm pair is Quality.

By country: FR 36, EE 12.

Contributing factors: verifier_substring_gate 10, fetch_blocked_403 10,
evidence_absent 5, zero_weight 5, ground_truth_contested 3, selection_miss 2.

A more useful cut than the raw table: group by what would actually move the
number.

- **Recoverable inside the current swarm (15 pairs).** N1 (10) plus N2 (4)
  plus the one inconclusive_collapse. In every one of these the swarm produced
  the ODMI-correct answer at some point and then lost it, to the substring gate
  or to the finalisation code. This is the single most actionable block and
  neither lever A nor C is the fix.
- **Reachable but missed (6 pairs).** selection_or_interpretation_miss. The
  artefact was public, usually URL'd in ODMI's own explanation, and the swarm
  gave up, four of the six at retry 0.
- **Structurally out of reach (19 pairs).** evidence_absent_or_self_report.
  Self-reports and internal practices, plus the catalogue-derivable
  percentages. Web search is the wrong tool for these.
- **Format (6 pairs).** Five schema failures and one out-of-set label.
- **Contested or zero-weight.** Removed from the error count on the merits, see
  below.

## Ground-truth-contested list (candidate swarm wins for a human glance)

- **PT4 (FR), confirmed.** Swarm `no`, confidence 0.92, quoting data.gouv.fr's
  own guide that it has no SPARQL endpoint and redirects to data.europa.eu. I
  confirmed this live on 2026-06-02: the page reads "Il n'existe actuellement
  pas de point d'acces SPARQL directement sur data.gouv.fr." ODMI's `yes`
  cites a generic REST API reference, which is not a SPARQL access point. The
  swarm is right and ODMI is loose.
- **Q12, Q17, Q18 (FR), strong.** ODMI self-reports `>90%` for licence
  coverage and DCAT-AP conformance with an N/A explanation. The D29/D30 work
  already showed France's independently recomputed coverage is far lower
  (around 38% for licences, around 32% for conformance). The swarm's
  `inconclusive` is the more honest web answer, and ODMI's self-report is the
  contested side.
- **Q12 (EE), weak.** Same catalogue-derivable percentage shape; the EE
  catalogue was 403-blocked so neither side is verified here.
- **P6 (FR) and P10-b (FR), interpretation disputes.** P6: ODMI reads the
  open-to-all roadmap as a measure to incentivise citizen-generated data; the
  swarm read "incentive measures" narrowly and said `no`. P10-b: ODMI's `yes`
  is aspirational ("ministries are working on inventories ... will include
  ..."). The swarm's `no` is defensible. Both deserve a human call rather than
  being scored as swarm errors.
- **I11 (FR), borderline.** Primary mode is the substring gate, but ODMI's
  taxonomy claim is loosely worded and the swarm's `no` is not unreasonable.
  Listed for completeness.

## Pairs I could not classify

None were left unclassified. Every one of the 48 has a primary mode with a
cited reason in the CSV. The classifications I hold most loosely are the EE
pairs where 403s prevented me from seeing what the fetcher saw (Q1 EE, Q10 EE,
marked low/medium confidence), and the selection-versus-absence calls on the
rt0 FR give-ups (P17, P18, Q4, Q11), where without the fetch cache I am
inferring reachability from ODMI's printed URLs rather than from the swarm's
own retrieval.

## What the mix implies for the interventions, stated straight

The two levers on the table address a minority of the failures, and not the
largest minority.

**Lever A** (feed the Verifier's rejection reason into the query generator so
searches diverge) is relevant to the 6 selection_or_interpretation_miss pairs
and possibly to some substring-gate pairs, if a different query happened to
surface a page the Verifier could re-match. That is its ceiling: roughly 6 to
12 pairs, and for the substring-gate cases it treats the symptom. The
Researcher's queries do repeat verbatim across retries, exactly as observed
(I8-a runs the same three queries at rt0, rt1 and rt3), so the diagnosis behind
A is real. It is just not where most of the loss is.

**Lever C** (tell the Researcher which labels already failed) maps cleanly onto
exactly one differ pair, PT37, where constraining output to the allowed set
would have turned `yes` into `all datasets`. It does nothing for the dominant
`inconclusive`-versus-`yes` pattern, because the problem there is not label
selection within a bounded space. The Researcher frequently did try `yes` and
had it rejected. C helps eliminate; the swarm's difficulty is committing.

The higher-yield fixes are neither A nor C:

1. **Repair the Verifier substring gate** (N1, 10 pairs, plus it is the engine
   behind the 187 fails and many escalations). Verify against actually-fetched
   page text, or allow a normalised or semantic match, instead of rejecting
   quotes that cannot be re-matched on un-fetched or 403'd pages.
2. **Use `adjudicator_answer` when finalising** (N2, 4 pairs, immediate). A
   one-function change at `run_coordinator.py:973-990`.
3. **Persist retrieved snippets** so verification has something real to check
   and so this analysis is reproducible. This underpins fix 1.
4. **Route catalogue-derivable questions to the D30 tool**, not web search
   (Q12, Q17, Q18, EE Q12). Compute, do not search.
5. **Fix the fetcher's 403 handling** for government hosts and PDFs (N4, 10
   pairs, mostly EE). A better user agent, headless browser fallback, or
   per-host retry would unblock real public sources.
6. **Decide the policy on self-report questions** (19 pairs). For these,
   `inconclusive` is often the honest answer and ODMI's value is an unverifiable
   self-report. Either escalate to a human, or stop scoring these as swarm
   errors.

## Honest interpretation

The retry-repetition story is true but it is a side plot. The main story is
that the swarm is not bad at finding answers; it is bad at keeping them. In 15
of 43 disagreements the swarm produced the ODMI-correct answer and then lost it,
to a substring check that fails two times in three even on good pairs, or to a
finalisation path that ignores the Adjudicator's own conclusion. Those are
verification and plumbing defects, not search defects, and neither lever under
consideration touches them. The next largest block, 19 pairs, is questions
whose answers live in the country's self-report and not on the open web, where
`inconclusive` is arguably correct and the right move is to change how we score
them rather than how we search. The levers A and C remain reasonable for the
narrow slices they fit, selection misses and out-of-set labels, but adopting
either as the headline response would be optimising the smaller problem. The
uncomfortable result is that the cheapest, largest accuracy gain is to fix the
Verifier and the coordinator, and the project cannot fully measure any of this
until it starts saving what its agents actually read.
