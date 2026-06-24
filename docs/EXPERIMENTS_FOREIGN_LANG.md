# Foreign-language search: pre-registered designs

Written before any run so the analysis plan is fixed blind (R1). The headline
artefact here is EXP-22, the query-language ablation on Albania. The downstream
levers are sketched as follow-ons, sequenced after EXP-22 locates the
bottleneck. All designs are DIY-only (provider closed, D43) and draw only from
the dev set (NL, MT, NO, FR, AL); the eight D47 held-out countries never appear.

## Two different limits: thin web versus foreign language

The abstention taxonomy and the expert evidence-gap report split the
non-committed mass into two halves with different fixes:

- **Thin web.** The answer is not on the open web at all, in any language. It is
  an internal-operations claim, an assertion of absence, or simply unpublished.
  This is a data-availability limit. No retrieval or translation reaches it, and
  abstaining is the correct behaviour of an evidence-grounded system. About half
  the abstained pairs sit here.
- **Foreign language.** The answer exists on a public page, but in the national
  language, on a national-TLD source the English-first pipeline reaches poorly.
  This is a retrieval and comprehension limit, and it is fixable. The cited
  assessor evidence is overwhelmingly national-TLD and frequently non-English
  (see `docs/EXPERT_EVIDENCE_GAP.md`), so a real slice of the findable half is a
  language problem.

The point of the foreign-language programme is to attack the second half
without pretending the first half is reachable. EXP-22 is the experiment that
tells the two halves apart on a thin-web, low-resource dev country.

## What is already in production

Native-language query generation is **not** a new feature. The Researcher's
query-gen prompt (`phase2_researcher_query_gen` v2) already instructs one
English query plus a native-language query when the country is not
English-speaking, and AL pairs verifiably issue well-formed Albanian queries
already, for example `"Shqipëri të dhëna të hapura ndikim mjedisor ndryshimet
klimatike"` and `"site:opendata.gov.al strategji të dhëna dinamike"`. So:

| Option | Status |
|---|---|
| (a) native-language query generation | already production |
| (b) bilingual querying (English + native) | already production |
| (c) translate fetched pages to English before the snippet-picker | not built |
| (d) native-language snippet-picking | not tested as an arm |
| (e) DeepL query translation | not built; redundant with the LLM native query, and DeepL has no Albanian |

The lever for the findable half is therefore no longer "add native queries". It
is, first, to measure whether the native queries we already issue actually buy
recall (EXP-22), and then, if they do, to reach and read the national-language
pages once fetched (the (c)/(d) follow-ons).

---

## EXP-22: query-language ablation on Albania

**Lineage.** Bilingual querying has run in production since the query-gen prompt
was written, and its value has never been measured. AL is the only thin-web,
low-resource country in the dev set; Albanian (sq) is unsupported by DeepL, so
the LLM-generated native query is the only available native-language signal and
the clean variable to ablate. This is an ablation of existing behaviour, not a
feature addition.

**Question.** Do the native-language queries the Researcher already issues raise
candidate recall on AL over English-only querying? And, by the size of that
gap, is AL's abstention a foreign-language limit (native queries help) or a
thin-web limit (they do not, because the evidence is not on the Albanian web
either)?

**Dataset.** AL, all 143 questions (`data/questions/all_questions.json`,
`countries: ["AL"]`). AL ground truth: 77 yes-tier, 22 `no`, 18 `i don't know`,
the rest bands or `n/a`; 99 binary golds, 22 of them negative. One country, both
arms over the identical pair set, so recall is paired per pair.

**Arms (one variable: query language).** `bilingual` (production default,
`knobs: {}`) versus `en` (English-only, `knobs: {query_language: "en"}`). Every
other knob is held at the EXP-21 frozen production config: `provider=diy`,
`strategy=verifier-disprove`, `max_results_per_query=5`, `num_queries=3`,
`max_retries=3`, verifier counter-search `always`, floor 0.65, picker on,
adjudicator standard, unchained. `type: retrieval`, cache forced off (both arms
search cold so the `en` arm cannot ride a `bilingual` cache hit).

**Manipulation check (must pass before the result is read).** The `en` arm must
issue no native-language query and the `bilingual` arm must issue at least one,
audited over `phase2_researcher_runs.search_queries_used`. If the LLM ignores
the English-only instruction the ablation is void, not a null result.

**Endpoints (fixed now).**
- Primary: candidate recall, the fraction of answerable AL pairs whose gold
  answer appears in at least one Researcher attempt, per arm, with Wilson CIs.
- Co-primary: abstention rate (final `inconclusive`) per arm.
- Secondary: commit accuracy, false-positive rate on the 22 negative golds,
  cost per pair with retries counted (R9), and the share of fetched pages whose
  body is non-English (the language surface the picker then has to read).
- Paired McNemar on per-pair recall (same pairs, two arms).

**Inference rule (fixed now, the reason the experiment exists).** Let
`delta = recall(bilingual) - recall(en)`.
- `delta >= +0.05` and the McNemar test favours `bilingual`: the native query is
  load-bearing on AL, so a measurable slice of AL's gap is foreign-language, not
  thin-web. Keep bilingual, and the (c)/(d) page-comprehension levers become
  worth building because the evidence is being reached in Albanian.
- `delta` within +/- 0.05: the native query adds no recall on AL, so AL's
  ceiling is thin-web, the evidence is not on the Albanian web either, and the
  fix is data availability, not language. This does not switch bilingual off on
  one country; it flags the native query as possibly non-load-bearing and queues
  a multi-country confirmation before any production change.
- `delta <= -0.05` (English-only wins): the native query is actively diluting a
  thin query budget on a thin-web country. A real, reportable cost finding, again
  pending multi-country confirmation before any switch.

The margins are pre-set so a small sample cannot be read as a win, and AL's size
(143 pairs, fewer once `i don't know` and `n/a` are dropped) means this is a
dev-set locating experiment, not the last word; a positive result is confirmed
on more dev countries before any default changes.

**Constraints.** One variable only (query language); DIY-only; cache off;
held-out countries never used; all other knobs frozen at the EXP-21 production
config. The `en` arm is built behind `--query-language en` (default `bilingual`,
byte-identical to production), see `tests/test_query_language_ablation.py`.

**Pre-registration and timing.** The design is locked here in git. The
`experiments` table row (R1/D27) is created at dispatch. Dispatch waits until
EXP-21 has finished, to protect the frozen headline run and avoid contending for
the shared CLIProxyAPI budget. Spec: `evaluation/specs/exp22_foreign_lang_al.json`.

---

## Follow-on levers (sketched, not yet pre-registered)

These are built only if EXP-22 shows the native query is load-bearing on AL
(`delta >= +0.05`), which would mean Albanian-language evidence is being reached
and the remaining loss is downstream comprehension, not query coverage.

- **(c) Translate fetched pages before the picker.** After fetch, machine
  translate the page body to English before the snippet-picker reads it. Tests
  whether the picker is failing to select evidence it did fetch because the page
  is in the national language. DeepL has no Albanian, so this lever is tested on
  a DeepL-supported dev country (NL or NO), not AL.
- **(d) Native-language snippet-picking.** Leave the page in the national
  language and let the picker, which is an LLM, select the snippet in-language,
  measuring whether the comprehension gap is in the picker or downstream at the
  verifier substring gate (D34) when the quote is non-English.

Both are retrieval-internal recall questions, so they respect the DIY-only
decision and never compare providers.

## Status

EXP-22 is designed and locked; the `--query-language` knob is built and unit
tested; the spec file is dispatch-ready. The run is gated only on EXP-21
finishing and the Claude budget. The follow-on levers are sketches, to be
pre-registered only if EXP-22 implicates language over data availability.
