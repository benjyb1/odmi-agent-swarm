# Decision surface

Every decision in the swarm that could move the results, mapped end to end. This
is the register the optimisation programme triages from. It is descriptive: it
records what the system currently does and what else it could do, with a leverage
and testability rating so we can argue most of it away and spend effort on the few
knobs that matter.

## How this was built

Six parallel readers swept the full stack (Researcher and query generation; the
search and retrieval layer; the Verifier and post-answer validation; the
Adjudicator and Coordinator state machine; the deterministic catalogue subsystem;
and the scoring, classification and dispatch layers). Each extracted every
constant, threshold, ordering choice, prompt rule and control-flow branch with a
file and line reference. This document is the synthesis, deduplicated and rated.
Roughly 470 raw points collapsed to the entries below; the purely cosmetic ones
(telemetry counters, log truncation, stage-name strings) are gathered in the
appendix rather than rated.

## Rating scheme

- **Leverage** is my prior on how much the decision moves accuracy, abstention or
  cost: High, Med, Low.
- **Test** is how cleanly it can be measured in isolation:
  - *Clean*: can be A/B'd on frozen evidence with no confound.
  - *Confounded*: interacts with another knob (usually retries or the search
    provider), so it must be tested jointly or with the interacting knob held
    fixed.
  - *Hard*: changing it changes what evidence exists, so the comparison is not
    like-for-like and needs a re-run, not a replay.
- **Where**: file:line. Where a value is set in several places, the canonical one
  is listed and the duplicates noted.

## How to use it, and the rule that protects the dissertation

This register exists so we can optimise without overfitting. Two standing rules:

1. **Nothing is tuned on the held-out countries.** Declare the test set before any
   sweep. Tune on a development set (France plus Malta is the obvious choice given
   coverage), lock a configuration, and measure once on countries that were never
   in the loop. The harder countries are the test set, not the optimisation target.
2. **Sweeping a knob is a pre-registered experiment, not a fishing trip.** Each
   entry promoted to an experiment gets a hypothesis and a metric written down
   before it runs, and any multi-knob sweep carries a multiple-comparisons
   correction. The garden of forking paths is the main threat to validity here,
   not insufficient search.

The leakage caveat compounds under optimisation: ODMI publishes its own answers,
so a config selected purely on match rate can win by exploiting the leak. The
deny-list (SRCH-12) is the mitigation, and any optimisation run must keep it on
and audited.

---

## Stage 0 — Pair selection and dispatch

What gets run, how much, and with which defaults. These do not change a single
answer but they decide the sample the whole evaluation rests on, so they affect
every aggregate result.

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| SEL-1 | Which (question, country) pairs are dispatched | Manual `--questions/--countries` | High (defines the sample) | Hard | dispatch_subtrios.py |
| SEL-2 | Countries available at all | `COUNTRIES` dict, fail if absent | High | n/a | run_coordinator.py:250 |
| SEL-3 | Parallel concurrency | 4 subprocesses | Low (throughput, not answers) | Clean | dispatch_subtrios.py:204 |
| SEL-4 | Max pairs per dispatch circuit-breaker | 500 (`allow_large` to exceed) | Low | n/a | dispatch_subtrios.py:63 |
| SEL-5 | Cost-estimate constants (cold-start $0.10, retry uplift 1.2, history window 50, sample floor 5) | as listed | Low (display only) | n/a | dispatch_subtrios.py:47-137 |
| SEL-6 | Country code upcased | `.upper()` | Low | n/a | dispatch_subtrios.py:243 |

Note: there is **no stratified or random sampling**. The set is whatever was
dispatched by hand, which is the root cause of the France-heavy, yes-skewed
evaluation. The single highest-leverage decision in this whole register is SEL-1,
and it is currently made ad hoc. Fixing it (a declared dev set and a frozen,
balanced test set) matters more than any threshold below.

---

## Stage 1 — Question classification and answer shaping

How each question's answer space is fixed. A misclassification here silently
changes what counts as a correct answer for that question, so leverage is high and
it is invisible in the results unless audited.

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| CLS-1 | Classifier is rule-based, not LLM | deterministic parser of the rubric | High (sets every shape) | Clean (audit vs hand-label) | migrate_d28_shapes.py |
| CLS-2 | Fallback shape when rubric unparsable | `binary [yes,no]` | High | Clean | migrate_d28_shapes.py:96 |
| CLS-3 | Binary key whitelist | 6 keys (yes/no/other/NA/idk) | Med | Clean | migrate_d28_shapes.py:48 |
| CLS-4 | Percentage-band regex | `>N% / <N% / N-N% / N%` | Med | Clean | migrate_d28_shapes.py:59 |
| CLS-5 | Count-band regex | `N-N / >N / <N / yes,<count>` | Med | Clean | migrate_d28_shapes.py:60 |
| CLS-6 | Ordinal trigger words | all/majority/approx half/few/none of | Med | Clean | migrate_d28_shapes.py:57 |
| CLS-7 | Band ordering source | rubric insertion order | High (drives near_match) | Clean | migrate_d28_shapes.py:164 |
| CLS-8 | Allowed-answer ordering | yes-variants, then no, then tail | Low | Clean | migrate_d28_shapes.py:149 |
| CLS-9 | Case-insensitive key dedup | first occurrence wins | Low | Clean | migrate_d28_shapes.py:181 |
| CLS-10 | Always-allowed escape labels | `inconclusive`, `not_applicable` | Med | Clean | answer_shapes.py:44 |
| CLS-11 | Which shapes are "ordered" | percentage/ordinal/count only | High (near_match scope) | Clean | answer_shapes.py:59 |
| CLS-12 | Answer normalisation | case-insensitive, returns canonical | Med | Clean | answer_shapes.py:127 |
| CLS-13 | Band distance metric | `abs(idx_a - idx_b)` | Med | Clean | answer_shapes.py:142 |

CLS-1 and CLS-7 are worth an audit pass on their own: the entire band-adjacency
scoring rests on the rule-parser getting the shape and the order right, and a
single wrong order turns a near-miss into a differ or vice versa.

---

## Stage 2 — Catalogue route (deterministic, no LLM)

The bypass that computes nine Quality questions from harvested metadata. High
leverage on the Quality stratum specifically, and it is where the strongest
finding so far (the France self-report gap) came from. Every cutoff here is a
measurement choice an examiner can contest.

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| CAT-1 | Which questions are computable | `{Q12,Q13,Q16,Q17,Q18,Q21,Q22,Q25,Q27}` | High (Quality) | Clean | compute.py:32 |
| CAT-2 | Conformance vs presence split | `{Q16,Q17,Q18}` need RDF graphs | High | Clean | compute.py:35 |
| CAT-3 | Percentage band lower-bound inclusivity | bottom band exclusive, others inclusive at upper | Med (boundary cases) | Clean | metrics.py:73 |
| CAT-4 | Count-band boundary parsing | `>N`→(N+1,inf), `<N`→(0,N-1) | Med | Clean | metrics.py:89 |
| CAT-5 | Dataset "is licensed" rule | any non-sentinel licence at any level | High | Clean | metrics.py:141 |
| CAT-6 | Dataset "is open" rule | any licence maps to an open family | High | Clean | metrics.py:183 |
| CAT-7 | Download/access-URL scope | only datasets that have distributions | High (denominator) | Clean | metrics.py:145 |
| CAT-8 | "Any distribution qualifies" for URL/format | any, not all | High | Clean | metrics.py:151 |
| CAT-9 | SHACL sample size | 1000, deterministic even spacing | Med | Clean | metrics.py:226 |
| CAT-10 | SHACL pass criterion | zero violations, warnings allowed, no inference/imports | High | Clean | metrics.py:111 |
| CAT-11 | Recommended-predicate "uses ≥1" | at least one present | Med | Clean | metrics.py:285 |
| CAT-12 | Optional predicate list | hard-coded 24 URIRefs | Med | Clean | shacl.py:49 |
| CAT-13 | Licence family detection order | 15 regexes, first match wins (NC before BY) | High | Clean | licences.py:52 |
| CAT-14 | Sentinel "no licence" patterns | 9 substrings incl. `notspecified`, `other-*` | High | Clean | licences.py:37 |
| CAT-15 | Open-licence family list | external JSON, 11 families | High | Clean | data/catalogue/open_licences.json |
| CAT-16 | Open machine-readable format list | external JSON, 24 tokens | High | Clean | data/catalogue/open_formats.json |
| CAT-17 | Format/media-type folding tables | 18+18 alias maps | Med | Clean | formats.py:22 |
| CAT-18 | Adapter preference order | DCAT-AP RDF, then CKAN/udata/Estonia | High | Confounded (per portal) | harvest.py:47 |
| CAT-19 | Partial harvest still answers | yes, flagged `partial` | High | Hard | compute.py:107 |
| CAT-20 | Harvest pagination/stop/delay per adapter | varied; EE capped at 75/page | Med | Hard | harvest.py, adapters |
| CAT-21 | Per-country portal config (endpoint, route, licence_field, delay 1.0s) | one JSON per country | High | Hard | registry.py |
| CAT-22 | Catalogue confidences | retrieval 1.0, answer 0.95 | Med (feeds the 0.65 floor) | Clean | researcher.py:274 |
| CAT-23 | Graph synthesis choices (BNodes, date typing, URIRef rules) | as listed | Med | Clean | synthesise.py |

CAT-5/6/7/8 and CAT-13/14/15 are the live methodological choices behind the
self-report finding. They are defensible but each one is a place ODMI could say
"you measured it differently from us", so they need documenting in the writeup
regardless of whether they are ever swept. CAT-19 (answering off a partial
harvest) is the riskiest: a truncated harvest can bias a proportion in either
direction, and it is currently silent in the answer.

---

## Stage 3 — Query generation (LLM call 1)

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| QRY-1 | Number of queries | 2-3 (`min 1, max 3`), capped by `num_queries` | High | Confounded (with retries) | researcher.py:44 |
| QRY-2 | Query-gen model | inherits default (Sonnet) | Med (cheap call) | Clean | researcher.py:141 |
| QRY-3 | Query-gen max_tokens | 200 | Low | Clean | researcher.py:142 |
| QRY-4 | Language mix rule | 1 English, +1 native if non-English | High (low-resource countries) | Hard | prompts/researcher.py:61 |
| QRY-5 | Query length guidance | 5-10 words | Med | Hard | prompts/researcher.py:61 |
| QRY-6 | Portal-targeting query | optional 3rd, when relevant | Med | Hard | prompts/researcher.py:63 |
| QRY-7 | Retry-divergence instruction | "generate different ones" + feedback | High (retry quality) | Confounded | prompts/researcher.py:68 |
| QRY-8 | Prompt version | v2 | Med | Clean | researcher.py:48 |

QRY-4 is the one that matters once we leave France. The whole multilingual story
turns on whether the native-language query helps, and it is untested outside a
data-rich, mostly-English/French country.

---

## Stage 4 — Search and retrieval

The layer the architecture debate is really about. High leverage throughout, and
most of it is Confounded or Hard because changing retrieval changes what evidence
the model ever sees.

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| SRCH-1 | Provider and fallback order | auto: Tavily, then DIY, then Brave | High | Hard | search.py:24 |
| SRCH-2 | Tavily-exhausted detection | keyword match on rate/quota/limit/credit, sticky global flag | Med (operational) | Clean | search.py:304 |
| SRCH-3 | DIY empty/exception falls through to Brave | yes | Med | Confounded | search.py:324 |
| SRCH-4 | max_results_per_query | 5 (set in 4 places) | High | Confounded (recall vs noise) | search.py:348 |
| SRCH-5 | Narrow-to-trusted-then-widen | trusted first, wide only if empty | High | Hard | researcher.py:370 |
| SRCH-6 | Widen trigger | only when narrow returns zero | High | Hard | researcher.py:381 |
| SRCH-7 | Trusted-domain list per country | `data/trusted_domains/<cc>.json` | High | Hard | trusted_domains.py |
| SRCH-8 | Brave/Serper include-domain cap | first 8 domains | Med | Confounded | search_serper.py:21 |
| SRCH-9 | Result dedup and ordering | by URL, first-occurrence order | Med (ordering bias) | Clean | search.py:359 |
| SRCH-10 | Serper relevance score | `1/position` | Low | Clean | search_serper.py:61 |
| SRCH-11 | Deny-list contents | 12 domains + 7 path fragments | High (leakage control) | Clean | blocked_domains.py:29 |
| SRCH-12 | Deny-list enforcement | exclude at query time AND post-filter, all providers | High | Clean | search.py:153 |
| SRCH-13 | DIY SERP results then fetch budget | break at max_results | High | Confounded | search_diy.py:121 |
| SRCH-14 | DIY fetch parallelism | 5 | Low | Clean | search_diy.py:28 |
| SRCH-15 | DIY Playwright fallback trigger | empty-after-strip or timeout | Med | Confounded | search_diy.py:43 |
| SRCH-16 | trafilatura settings | favor_recall=True, tables in, comments out | Med | Clean | extract.py:36 |
| SRCH-17 | Raw HTML cap before extract | 2,000,000 chars | Low | Clean | fetch.py:38 |
| SRCH-18 | Fetch timeout | 15s (httpx), 30s (Playwright) | Med (recall on slow sites) | Clean | fetch.py:32 |
| SRCH-19 | User-Agent and Playwright disguise | fixed UA, anti-automation flag, en-GB locale | Med (some sites block) | Hard | fetch.py:26,196 |
| SRCH-20 | Cloudflare challenge handling | markers + 4s wait | Med | Hard | fetch.py:202 |

SRCH-5/6 (narrow-then-widen) is the single most important untested retrieval
decision: narrowing to trusted domains trades recall for precision, and the widen
only fires on a total miss, so a question whose answer sits on an untrusted domain
but where the narrow search returned one weak trusted result never widens. SRCH-4
(only 5 results) and SRCH-7 (the hand-curated trusted lists) are the next two.

---

## Stage 5 — Snippet handling (what the model actually reads)

The bottleneck identified in the architecture discussion: the reasoning model sees
truncated excerpts, not pages. Every cap here is a ceiling on what can be answered.

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| SNIP-1 | Snippet chars shown to reasoning call | 600 per result | High | Clean | search.py:377 |
| SNIP-2 | All results passed vs top-k | all deduped results | Med | Clean | search.py |
| SNIP-3 | DIY page text shown to picker | 16,000 chars | Med | Clean | snippet_picker.py:32 |
| SNIP-4 | Picker passage cap | 500 chars each | Med | Clean | snippet_picker.py:31 |
| SNIP-5 | Picker single-vs-multi threshold | top chunk ≥0.7 returns only that chunk | Med | Clean | snippet_picker.py:29 |
| SNIP-6 | Picker max passages | 3 | Med | Clean | snippet_picker.py:57 |
| SNIP-7 | Picker scoring bands | 0.8-1.0 / 0.5-0.7 / 0.2-0.4 / 0-0.1 | Med | Clean | snippet_picker.py:55 |
| SNIP-8 | Picker model and max_tokens | inherits default, 1500 | Med | Clean | snippet_picker.py:94 |
| SNIP-9 | Multi-chunk separator | `" ... "` | Low | Clean | snippet_picker.py:30 |

SNIP-1 is high-leverage and trivially testable: 600 chars is a guess, and whether
the answer-bearing sentence survives that cut is exactly the retrieval bottleneck.
This is the cheapest high-value sweep in the register (replay over cached pages).

---

## Stage 6 — Reasoning call (LLM call 2)

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| REAS-1 | Reasoning model | default Sonnet (EXP-9 varies) | High | Clean | researcher.py:434 |
| REAS-2 | max_tokens | 2000 | Low | Clean | researcher.py:435 |
| REAS-3 | Temperature | 0.0 | Med (determinism vs diversity) | Clean | llm.py:192 |
| REAS-4 | Prompt variant | full vs compressed (EXP-8) | Med | Clean | researcher.py:304 |
| REAS-5 | The `inconclusive` 0.5 rule (in-prompt) | abstain if conf would be <0.5 | High (abstention rate) | Clean | prompts/researcher.py:66 |
| REAS-6 | Forbidden-source rule (in-prompt) | mirrors deny-list | High (leakage) | Clean | prompts/researcher.py:88 |
| REAS-7 | Literal-quote requirement | verbatim quote required | High (drives substring gate) | Clean | prompts/researcher.py:80 |
| REAS-8 | Single-source citation | one URL, must be in snippets | Med | Clean | prompts/researcher.py:84 |
| REAS-9 | Two self-reported confidences | retrieval + answer, [0,1], uncalibrated | High (gates everything downstream) | Clean | models.py:182 |
| REAS-10 | Confidence calibration | none | High | Clean | n/a |
| REAS-11 | Quote min length | 10 chars | Low | Clean | models.py:180 |

REAS-9/REAS-10 are the quiet giant. Two **uncalibrated** self-reported confidences
drive the abstention decision (REAS-5), the 0.65 commit floor (LOOP/ADJ), and the
Verifier pass gate. If the model's 0.7 does not mean 70% correct, every threshold
built on it is mis-set. Measuring calibration (reliability curve of answer_confidence
vs actual correctness) is high-value and clean, and it would tell us whether the
0.5/0.65 family of thresholds is even meaningful.

---

## Stage 7 — Post-answer validation (deterministic)

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| VAL-1 | URL reachability gate | `head_ok`, status <400, GET range-fallback | Med | Clean | fetch.py:377 |
| VAL-2 | WAF statuses to Playwright | {403,429,503} | Med | Clean | fetch.py:349 |
| VAL-3 | trust_score thresholds | trusted 1.0, authoritative 0.6, other 0.3, blocked 0.0 | Med | Clean | validator.py:110 |
| VAL-4 | Does trust_score gate anything? | no — annotates only | Med (latent: could gate) | Clean | researcher.py:535 |
| VAL-5 | Authoritative heuristic | `.gov/.gouv/.ec.europa.eu/.gov.uk` | Med | Clean | validator.py:76 |
| VAL-6 | Hard-coded FR/EU seed trusted lists | as listed | Med | Clean | validator.py:37 |
| VAL-7 | source_url-in-snippets check | note only, no fail | Med | Clean | researcher.py:519 |
| VAL-8 | Quote substring check deferred to Verifier | not checked at Researcher | High (placement choice) | Clean | researcher.py:476 |

VAL-4 is a finding in itself: the trust score is computed, overrides the model's
self-reported value, is stored, and then gates nothing. It is a dial wired to
nothing. Either it should feed the commit decision or it is dead weight; both are
worth stating.

---

## Stage 8 — Verifier

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| VER-1 | Strategy in use | passed in; 4 exist (disprove/negation/steelman/blind) | High | Clean (EXP-6) | verifier.py:395 |
| VER-2 | Single strategy vs ensemble | single | High | Clean | n/a |
| VER-3 | Independent search vs check-only | independent adversarial search | High | Hard | verifier.py:460 |
| VER-4 | Adversarial query direction | search for the opposite/adjacent label | High | Hard | prompts/verifier.py:72 |
| VER-5 | Substring source | stored snippets, else live fetch | Med | Clean | verifier.py:162 |
| VER-6 | Substring normalisation | NFKC + casefold + strip punctuation + collapse ws | High (strictness) | Clean | substring.py:31 |
| VER-7 | Substring fail weighting (in-prompt) | "weight heavily toward reject" | High | Clean | prompts/verifier.py:242 |
| VER-8 | Adjacent-band miss is a fail | yes, all strategies | High | Clean | prompts/verifier.py:264 |
| VER-9 | Blind pass confidence floor | ≥0.6 | High | Clean | prompts/verifier.py:439 |
| VER-10 | Blind answer-agreement override | Python flips pass→fail if answers differ | High | Clean | verifier.py:560 |
| VER-11 | Verifier model and max_tokens | default, 1500 | Med | Clean | verifier.py:505 |
| VER-12 | Catalogue answers recomputed, not searched | deterministic verify path | High (Quality) | Clean | verifier.py:409 |
| VER-13 | Catalogue verify confidences | 0.98 match / 0.9 mismatch / 0.5 unavailable | Med | Clean | verifier.py:316 |
| VER-14 | Independent snippet preview to model | 8 results, 200-300 chars | Med | Clean | prompts/verifier.py:143 |
| VER-15 | Invalid verifier answer | noted, not rejected | Med | Clean | verifier.py:552 |

VER-6 deserves a hard look: the substring gate is the main fabrication defence, and
its strictness is set entirely by the normalisation choices. Too loose and
paraphrase passes as a verbatim quote; too strict and a real quote fails on a
stray character. VER-1/VER-2 is the registered EXP-6 question (which strategy, or
an ensemble), and VER-8 (adjacent-band = fail) interacts directly with the
near_match scoring (SCORE-7), so they must be reasoned about together.

---

## Stage 9 — Adjudicator

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| ADJ-1 | When invoked | only after retries exhausted | High | Confounded | run_coordinator.py:1305 |
| ADJ-2 | Four verdicts | researcher/verifier/neither/escalate | High | Clean | prompts/adjudicator.py:46 |
| ADJ-3 | Low-confidence auto-escalation | verdict forced to escalate if conf <0.6 | High | Clean | adjudicator.py:29 |
| ADJ-4 | Trusts its own answer at finalise (D32/33) | yes | High | Clean | run_coordinator.py:317 |
| ADJ-5 | Adjudicator retrieval_confidence | hard-coded 0.7 | Med | Clean | run_coordinator.py:337 |
| ADJ-6 | Model and max_tokens | default, 1200 | Med | Clean | adjudicator.py:104 |
| ADJ-7 | Reasoning truncation | 300 chars to final | Low | Clean | run_coordinator.py:332 |
| ADJ-8 | Invalid adjudicator answer | noted, not crashed | Med | Clean | adjudicator.py:145 |

ADJ-1 (only after the full retry budget) is a structural choice with cost
implications: the Adjudicator is the most expensive path and only ever runs on the
hard tail, so its measured value is entangled with how many retries preceded it.
ADJ-3 (0.6) and the commit floor (LOOP-7, 0.65) are two different confidence gates
a few points apart, both unexplained; they should be reasoned about as one policy.

---

## Stage 10 — Coordinator loop

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| LOOP-1 | Max retries | 3 (4 attempts) | High | Confounded | run_coordinator.py:859 |
| LOOP-2 | Researcher `inconclusive` forces retry | yes, except final (D35) | High | Confounded | run_coordinator.py:1125 |
| LOOP-3 | Verifier-reject retries until budget | yes, then adjudicate | High | Confounded | run_coordinator.py:1265 |
| LOOP-4 | Accept-Verifier-pass gate | pass AND not abstain AND conf ≥0.65 | High | Clean | run_coordinator.py:834 |
| LOOP-5 | Null confidence defaults to 0.0 (fails gate) | yes | Med | Clean | run_coordinator.py:1274 |
| LOOP-6 | Queries accumulate to force divergence (D33) | yes | Med | Confounded | run_coordinator.py:1062 |
| LOOP-7 | Commit-confidence floor | 0.65 (D37) | High | Clean | run_coordinator.py:813 |
| LOOP-8 | Sub-floor pass becomes inconclusive | yes | High | Clean | run_coordinator.py:319 |
| LOOP-9 | Model escalation on retry (EXP-8) | off by default | Med | Clean | run_coordinator.py:816 |
| LOOP-10 | Evidence chaining (EXP-7) | off by default | Med | Confounded | run_coordinator.py:868 |
| LOOP-11 | Evidence corpus cap | 40 items | Low | Clean | run_coordinator.py:735 |
| LOOP-12 | Resume window / eligibility | 60 min, retry_count 0, clean rows only | Med (reproducibility) | Hard | run_coordinator.py:593 |
| LOOP-13 | Resumed row carries no snippets | forces Verifier re-fetch | Med | Clean | run_coordinator.py:1022 |

LOOP-1, LOOP-4 and LOOP-7 are the spine of the commit-vs-abstain behaviour and are
all confounded with each other: more retries change the abstention rate, the
confidence floor changes how many retries fire, and the pass gate sits on the same
confidence the floor uses. They cannot be swept one at a time honestly; they need a
small joint design. This cluster, plus REAS-9 calibration, is where the
abstention/accuracy trade-off actually lives.

---

## Stage 11 — Scoring and evaluation

Not part of a run, but it defines "correct", so a change here moves every headline
number without touching the swarm.

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| SCORE-1 | Abstention counts against accuracy | `inconclusive` in denominator, never matches | High | Clean | db.py:128 |
| SCORE-2 | Accuracy denominator | match+near+differ+abstained | High | Clean | db.py:402 |
| SCORE-3 | Accuracy numerator | exact match only (near excluded) | High | Clean | db.py:403 |
| SCORE-4 | Bare-`yes` matches `yes%` on binary only | yes | High | Clean | db.py:135 |
| SCORE-5 | Bare-`no` exact only | yes | Med | Clean | db.py:143 |
| SCORE-6 | Exact match is case/space-insensitive only | no fuzzy | Med | Clean | db.py:130 |
| SCORE-7 | near_match = adjacent band, 3 ordered shapes, sentinels excluded | yes | High | Clean | db.py:154 |
| SCORE-8 | Main-runs filter | `experiment_id IS NULL` | High | Clean | db.py:181 |
| SCORE-9 | Gold not normalised at load | raw strings, normalised only at compare | High | Clean | load_ground_truth.py |
| SCORE-10 | Ground-truth cycle | 2025 xlsx, merged_responses | High | Hard | load_ground_truth.py:23 |

Two traps here. SCORE-1/2/3 are a reporting choice, not a fact: counting
abstentions against accuracy gives the conservative 64.5%, excluding them gives
88% on committed answers. The dissertation must state which it means and ideally
report both, because they answer different questions. SCORE-9 (gold normalised
only at compare time, by `LOWER`/`TRIM`) means any quirk in the raw ODMI strings
that those two functions do not catch will silently read as a `differ`; this is
worth an audit of the gold column against the swarm's label vocabulary.

---

## Cross-cutting infrastructure

| ID | Decision | Current | Leverage | Test | Where |
|----|----------|---------|----------|------|-------|
| INFRA-1 | Default model | `claude-sonnet-4-6` | High | Clean | llm.py:69 |
| INFRA-2 | SDK retries / timeout | 8 retries, 60s | Low | Clean | llm.py:83 |
| INFRA-3 | Structured-output 2-attempt retry | stricter JSON reprompt on fail | Med | Clean | llm.py:229 |
| INFRA-4 | Cost table | hard-coded per-model USD | Low (display) | Clean | llm.py:60 |
| INFRA-5 | Cache TTL | 30 days, 3 layers | Med (reproducibility) | Clean | search_cache.py:37 |
| INFRA-6 | Cache key normalisation | query+max_results+sorted domains; URL lowercased | Med | Clean | search_cache.py:115 |
| INFRA-7 | Cold-cache toggle | reads off, writes on (`no_cache`) | Med (experiment hygiene) | Clean | search_cache.py:50 |
| INFRA-8 | GBP conversion | 0.79, display only | Low | n/a | run_coordinator.py:1117 |

---

## Triage: what to test first

Promoting the few high-leverage, testable, high-uncertainty entries. Everything
else is documented and left at its current value unless a result implicates it.

1. **SEL-1 — the evaluation sample.** Not a knob, the precondition. Declare a
   balanced dev set and a frozen held-out test set before anything else. Highest
   leverage in the register and currently ad hoc.
2. **REAS-9/REAS-10 — confidence calibration.** Measure whether self-reported
   answer_confidence tracks correctness. Clean, cheap (re-scores existing rows),
   and it tells us whether the entire 0.5/0.6/0.65 threshold family is set on
   sand.
3. **LOOP-1 / LOOP-4 / LOOP-7 — the commit/abstain spine.** One small joint design
   over retries, pass gate and commit floor. This is where the
   accuracy-vs-abstention trade-off is decided.
4. **SNIP-1 — the 600-char snippet cap.** Cheapest high-value sweep; pure replay
   over cached pages; directly tests the retrieval bottleneck.
5. **SRCH-5/6 — narrow-then-widen.** Does trusted-domain narrowing help precision
   or just suppress recall? Needs a re-run, but it is the core retrieval design
   choice and the one most likely to matter on harder countries.
6. **VER-1/VER-2 — verifier strategy or ensemble (EXP-6, already registered).**
7. **VER-6 — substring-gate strictness.** The fabrication defence; set entirely by
   normalisation choices.
8. **SRCH-4 — results per query (5).** Recall vs noise, confounded with retries.
9. **The ablations** that quantify component value rather than tune it: remove the
   Verifier, remove the Adjudicator, remove narrow-then-widen, replace the
   reasoning call with a trivial baseline. Descriptive, overfitting-proof, and the
   strongest "does each part earn its place" evidence for the writeup.

Things to **document and leave alone** unless implicated: all telemetry/naming
(appendix), cost constants (INFRA-4, SEL-5), Serper scoring (SRCH-10), most fetch
disguise settings (SRCH-19/20), and the long tail of Low-leverage entries above.

## Open questions this surfaced

- VAL-4: trust_score is computed and stored but gates nothing. Wire it in or
  declare it dead.
- ADJ-3 (0.6) vs LOOP-7 (0.65): two confidence gates a few points apart with no
  shared rationale. Reconcile into one stated policy.
- CAT-19: answering off a partial harvest can bias a proportion silently. Decide a
  minimum-coverage threshold or carry the partial flag into the confidence.
- SCORE-9: gold is normalised only at compare time. Audit the raw gold vocabulary
  against the swarm's labels for silent `differ`s.

## Appendix — cosmetic, non-result-affecting

Telemetry counters (`_PROVIDER_USAGE_COUNTERS`, `_BLOCKED_RESULT_COUNTER`), stage
and substage name strings, walkthrough print trimming (100 chars / 5 items), error
message truncation (200-300 chars), usage-context string formats, prompt
name/version identifier strings, dry-run write-skipping, and the GBP display rate.
These are recorded for completeness and carry no leverage on the answers.
