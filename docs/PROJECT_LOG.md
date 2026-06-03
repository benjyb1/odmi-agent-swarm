# Project Log

Session-by-session technical log. Decisions go in `SPEC.md`. Narrative for the
dissertation goes in Notion. This file is what was tried, what was learned,
and what comes next, written from the perspective of the work as it happens.

Entries newest first.

---

## 2026-06-03 — Session 20d: remove the cost soft limit (D40)

Ripped out the local cost soft limit. It was a three-layer thing (D20): a
pre-flight refusal if projected cost exceeded a notional budget, a low-water stop
that halted spawning at 95% of the cap, and a clean rate-limit shutdown. The
first two only ever got in the way. The "budget" was a guessed arithmetic
equivalent of a flat CLIProxyAPI subscription, not a real balance, and the proxy
strips the rate-limit headers so the figure never tracked actual Max capacity. So
the gate refused or stalled real runs against a number that meant nothing.

Removed the threshold, both aborts, the `soft_limit_usd`/`force` params and the
`--soft-limit-usd`/`--force` flags, the `CostEstimate`/`DispatchResult` budget
fields, the dashboard slider and progress-toward-limit bar, and the Run Console
"Force release" checkbox. Kept the clean 429 shutdown (the only real ceiling) and
the rolling 5-hour spend as a plain information meter on the sidebar, Run Console,
and Costs page. The pre-flight estimate still logs a projection; it just no longer
blocks anything. Annotated D20 as superseded and added D40. 438 non-live tests
pass.

Then put back the one guard that's actually worth having (D41), reframed as a
circuit breaker rather than a budget. The real worry is a misspecified experiment
eating the whole 5-hour Max window, so the guard works on real units and sits far
above any real run. Pre-flight: refuse a single dispatch above 500 pairs (the
cross-product footgun is 5,148; legitimate runs are ~100-150), overridable with
`--allow-large` and surfaced as a one-off checkbox in the Run Console. Mid-flight,
opt-in: `--max-calls` stops spawning once the batch's own logged calls reach a
cap, for the runaway-loop case. Both silent in normal use. `DispatchResult` gained
`aborted_oversize` / `calls_capped`. New `tests/test_dispatch_runaway_guard.py`
(8 cases, with `time.sleep` monkeypatched so the 500-pair test doesn't spend 25s
on the spawn stagger); 446 non-live passing.

---

## 2026-06-03 — Session 20c: EXP-7 chained retry arm (built, gated, pre-registered)

Built the chaining arm for EXP-7. The loop spends up to eight calls per pair but
treats each retry as a fresh shot: the Verifier searches the web every round,
finds real counter-evidence, and the loop keeps only its verdict and bins the
rest. D33 already carries queries and the rejection reason forward and D34
persists the snippets, so the evidence was being thrown away on the floor next to
the persistence that could have carried it. EXP-7 asks whether chaining it
recovers more correct answers per call without raising the false-positive rate.

Three changes, all behind a `--chained` flag that defaults off: feed the
Verifier's counter-evidence back into the Researcher on retry (not just the
verdict and a query), accumulate a de-duped evidence corpus across rounds and
carry it forward, and have the Adjudicator synthesise over the whole corpus. The
D37 commit floor and the abstention rules are untouched in both arms; the
treatment only changes what each call sees, never the bar it has to clear. That
separation is what lets a recovery gain be read as better evidence use rather
than a lowered threshold.

The hard constraint was that the EXP-8/9 baseline and production must not move,
because they are measured against this same loop and another tab is about to run
them on Malta. So the carried evidence rides in the per-call user message, not the
system prompt: `prompt_versions` rows stay put, and an empty corpus renders
byte-for-byte as the old prompt. Wrote `tests/test_chained_evidence.py` (18 cases)
to pin exactly that, plus that the corpus carries forward when populated and that
the flag defaults off. 418 non-live tests pass.

Pre-registered in `docs/EXPERIMENTS_CHAINING.md` under R1 to R12: Malta primary
(no-gold-rich, so a false `yes` is visible), baseline vs chained, balance-aware
endpoints with the false-positive rate as a co-primary, paired McNemar and
Wilcoxon, one confirmatory joint claim. The run is gated only on the Malta
dispatch (search quota, shared with EXP-6/8/9) and Claude headroom. Logged as D39;
EXP-7 status board and the SPEC current-status block updated. No swarm was
dispatched: pure code and docs, so this ran fully parallel to the Malta tab.

Then built the analysis harness too (`evaluation/chaining_analysis.py`,
pre-run requirement 2), so it is ready and tested before the data exists rather
than thrown together after. A pure stats layer (PairOutcome classifiers, the
per-arm summary, and a paired comparison that runs McNemar on both recovery and
the committed-but-wrong indicator, Wilcoxon on calls, and a mechanical joint
verdict against the 0.05 false-positive margin) sits over a thin DB layer that
reuses `_MATCH_STATUS_SQL`, so recovery means the same thing here as on the
dashboard. Balanced accuracy is reported only when both binary classes are
present, so a one-class sample cannot masquerade as balance-aware. 15 new tests,
including a temp-SQLite round trip for the arm split and call counting.

Next: when the Malta dispatch lands, confirm the resume path does not let a
Researcher row cross arms, then run baseline and chained in sequence on the same
Malta pair set and point the harness at the experiment_id.

---

## 2026-06-03 — Session 20b: experiment rules and the base-rate trap

Wrote a universal rulebook for the experiments. The trigger was a concrete
failure: the early runs leaned on France, but France's binary gold is 119 `yes`
to 1 `no`, so a model that says `yes` to everything scores about 99% and a false
positive never shows. Accuracy there measures nothing, and false positives were
slipping through unseen.

Added section 0 to `EXPERIMENTS_PROTOCOL.md`, twelve numbered rules (R1 to R12)
that every experiment now answers to. R4 is the new one: report the majority-class
baseline beside every accuracy number, use a balance-aware metric when the classes
are skewed, and pick the evaluation country by minority-class share subject to a
well-resourced-language constraint. Computed the No-share for every country from
`ground_truth`; Malta is the standout (English is official, so no language
confound, and about 30 `no`-gold binary questions), Netherlands the runner-up.
France, Estonia, and Lithuania (zero negative binary golds) are barred as primary
sets.

Applied the rule rather than just stating it. EXP-6 (verifier strategies)
retargeted from its France-dominated should_fail class to Malta-primary; the
France and injected candidates stay as a robustness arm, and the harness strata in
`evaluation/verifier_strategies.py` were rebuilt around primary / secondary /
robustness roles. Verified it degrades cleanly: with no Malta data yet, the
primary stratum is empty and the run falls back to an 82-candidate robustness arm,
labelled as such. Pre-registered EXP-8 (cost-side, Family 1) and EXP-9 (model
variants, Family 3) on Malta. Wrote a rubric audit (protocol section 12): it finds
that EXP-1's France accuracy figure is degenerate although its provider win-share
result stands, and that EXP-3's Lithuania "discriminating control" cannot
discriminate a false positive on binary, since Lithuania has no negative binary
golds at all.

All three optimisation runs are blocked on a Malta Researcher dispatch, which is
pending search quota, the same gate as the parked D28 Phase 3. Nothing was run.
Recorded as SPEC D38.

---

## 2026-06-03 — Session 20a: the experiments programme, and a branch merge

Two strands: running the search experiments, and untangling the branch mess that
several parallel Claude windows had left behind.

The experiments were pre-registered in `EXPERIMENTS_PROTOCOL.md` before any run,
so the numbers cannot be reverse-fitted to a hypothesis. Two adversarial
methodology reviews caught three real holes in the first draft: a win metric that
counted ties as DIY successes, a deny-list applied unequally across providers
(DIY scrubbed after fetch while Tavily and Brave excluded at query time), and a
judge that saw the gold answer and so could reward keyword overlap rather than
evidence. All three are fixed in the apparatus.

EXP-1 is the headline. On the full FR non-Quality stratum (90 pairs) DIY wins 89%
of the 55 decided pairs, Wilson CI [78, 95], sign-test p < 1e-4, leading every
web-answerable dimension. It supersedes the n=18 pilot. The caveats stay
attached: position consistency 81%, and the answer-blind judge agrees with the
answer-given verdict on only 67% of the subsample, so the judge is somewhat
swayed by seeing the answer.

Apparatus built and tested: a stats module (Wilson, sign test, McNemar, Wilcoxon,
Krippendorff alpha); evidence normalisation and pre-fetch deny-list parity so the
blind judge cannot fingerprint a provider; a Groq / Llama-3.3-70B cross-family
judge (Gemini was first choice but both keys had zero generate quota) and an
answer-blind variant; adjudication caching so a killed judge run resumes from
disk; and a multi-provider pairwise harness with Copeland ranking.

What did not finish: the machine kept restarting and killing background jobs, so
EXP-4/5 (one four-provider judge run yields both) stopped near 882 of ~1080
verdicts and resumes from the cache. EXP-3 (multilingual EE/LT/IS) was skipped
after the LT/IS dispatch repeatedly stalled at search. EXP-2a/2b are selected but
not dispatched. The Groq cross-family backfill is built and tested but blocked by
the free-tier daily token cap, so it waits for the window to roll over. EXP-6
(the other window's verifier-strategy experiment) is partially run at 3/89.

The cleanup: all of this had landed on `gate-retry-fixes` along with the other
windows' D34-D37 and EXP-6/EXP-7 work, while `main` had drifted to a single
worktree-isolation commit. Merged `gate-retry-fixes` into `main` so main is the
frontier again (CLAUDE.md auto-resolved, no manual conflict), pushed it, and
pruned the seven stale agent worktrees. The partial EXP-6 rows in `odmi.db` stay
local and out of main until that experiment finishes.

Next: resume EXP-4/5 from the cache, backfill the Groq cross-family agreement
once the quota resets, then run EXP-2a/2b.

---

## 2026-06-02 — Session 19: scrub the stale LangGraph claims

The report draft described the swarm as "LangGraph-based". It is not, and never
has been in the shipped code. D3 originally specified a graph framework, but the
Coordinator landed as a plain Python state machine (`run_coordinator.py`), and
the deviation has sat in the file header and PROJECT_LOG since Session 12
without ever propagating back to the design and report docs. Anyone reading
METHODOLOGY or REPORT_PRELIM would have come away with the wrong stack.

Fixed the claims rather than the history. D3 is amended in SPEC, not deleted, so
the original reasoning and the reason it was dropped both survive. METHODOLOGY
§5/§8, AGENT_DESIGN §1/§5/§8, REPORT_PRELIM, and the slide source now say "plain
Python state machine". AGENT_DESIGN §5 keeps its graph vocabulary (state, edges,
nodes) under a banner that says to read it as the plain-Python equivalent, since
the control flow it describes is still accurate.

While checking the dependency list I found that no Python file imports langgraph
or langchain at all. All three (`langgraph`, `langchain-anthropic`,
`langchain-community`) were dead weight. Removed them. The catch: the LLM
interface imports `anthropic` directly, and `anthropic` was only in the
environment as a transitive dependency of `langchain-anthropic`. Removing the
langchain packages would have silently broken `agents/tools/llm.py` on the next
clean install. Promoted `anthropic>=0.87` to a direct dependency and re-locked.
335 tests pass (the one collection error, `test_provider_ab.py`, is the parked
provider-A/B work and predates this).

Kept on purpose: the "we considered and rejected LangGraph" record in CLAUDE.md,
this log, and the `run_coordinator.py` header, plus the related-work citations
in REPORT_PRELIM §2.2 and references.bib. Those are not false claims, they are
the audit trail.

---

## 2026-06-02 — Session 18: why retries do not move, and two fixes (D32, D33)

Started from a complaint that subtrio retries keep returning the same answer.
The read-only diagnosis confirmed it: on contested pairs the Researcher repeats
its first answer most of the time, and the query generator was the cause. It
gets the same input every round (country, portal, question), so it reissues
near-identical queries. PT8 FR ran byte-identical queries on two attempts; P11
and P12 EE varied by one token across four. Of 68 retried pairs, 41 never
changed their answer.

The plan was to diversify retries (feed the rejection reason into the query
generator, and exploit the bounded answer space to eliminate failed labels).
Before building, a failure-mode analysis of all 43 ground-truth disagreements
was run. It overturned the premise. The swarm is not mislabelling: 38 of the 43
are the swarm saying `inconclusive` where ODMI committed to `yes`. It finds
answers and then loses them. Two engines: a verification gate that rejects on a
rematch artefact (the cited page is never re-fetched or returns 403, so a Tavily
snippet is not a verbatim substring of the live page; 179 of 266 main-run
substring checks fail), and a finalisation step that discards the Adjudicator's
answer. The latter was a plain bug: `coordinate` rebuilt the final answer from
the verdict label, taking the last Researcher output on `researcher_correct`
even when the Adjudicator had committed to `yes` in `adjudicator_answer`.

Fixed the two that are cheap and provable now. D32: finalisation reads
`adjudicator_answer` for every resolved verdict, via a new pure helper. A
stored-row replay flips four pairs to match (P26-b FR, PT14 FR, I16 EE, I17 EE)
with no re-run. D33: kept the divergent-retry change, scoped down: the query
generator now sees the rejection reason, the suggested query, and the queries
already tried, and is told to vary them. Honest about its size, the analysis
says this is worth about six pairs, not the headline fix.

Left for next: the verification gate. It should check the quote against the
text the Researcher actually read, not a re-fetch, and stay strict rather than
loosen to a semantic match (the gate enforces the no-hallucination guarantee).
That fix needs retrieved snippets to be persisted first; the fetch cache
currently holds about 3% of what main runs read, which is also a reproducibility
hole worth closing in the same change. 297 non-live tests passing.

Then did the gate fix the same day (D34). Persisted the Researcher's snippets and
pointed the substring check at them instead of a live re-fetch. The mechanism
works: the gate's pass rate went from 33% to 88% on a 15-pair forward re-run
(`gatefix_v1`), so the false rejections are gone. But it recovered no pairs on its
own. With the false rejection removed, the Researcher answers `inconclusive` at R1
and the Verifier accepts the abstention, so the loop terminates before retrying.
The broken gate had been forcing retries by failing; removing it removed the
exploration that sometimes reached `yes`. The next constraint is clear and was
not obvious before this run: the Verifier should treat `inconclusive` as
keep-trying, not a pass, and a retry floor should stop the rt0 give-ups. Two pairs
reached `yes` (I16 EE, P26-b FR) on Researcher luck, not via the Adjudicator,
which was never exercised. A concurrent session was building the search-experiment
apparatus in the same tree at the same time; the gate work is committed separately
to keep the two clean. 335 non-live tests passing.

Then closed the loop with D35: `inconclusive` is an abstention, so it triggers a
retry (same 3-retry budget) and escalates to the Adjudicator if the budget runs
out, rather than terminating the run. Deliberately did not add a "keep the best
answer across retries" rule: that would pass through answers the Verifier
refuted, and the Adjudicator (D32) is the proper place to overturn a refutation.
This was the missing half. Where the gate fix alone recovered nothing, the early
read of the re-run (`inconc_retry_v1`, on top of D34) is the opposite: the first
three gate-collapse pairs all flipped from `inconclusive` to the correct `yes`
(I11, I5, I8-a FR), because the Researcher now retries past its R1 abstention and
the fixed gate accepts the `yes`. The full re-run confirmed it: 12 of 14 pairs
recovered to match (P25 FR errored), against 2 of 14 under the gate fix alone and
0 in the original run. The two misses are honest: PT33 FR stayed inconclusive
through the Adjudicator (its ground-truth answer is a compound string), and PT14
FR committed to `no` where the truth is `yes`, the cost of forcing a commitment.
So the gate fix was necessary but inert on its own; the abstention rule was the
half that moved the numbers, 2/14 to 12/14. 368 non-live tests passing.

## 2026-06-02 — Session 17: catalogue-metrics tool for the computed Quality questions (D30)

The Quality questions that ask for a share of the national catalogue ("what
percentage of metadata carries a licence", "what percentage is DCAT-AP
compliant") were unanswerable by web search: the answer is a computed statistic,
not a fact on a page, and the one source that publishes it (the MQA) is the
deny-listed data.europa.eu (D24). The swarm abstained and scored ~47% on
Quality. This session built a deterministic tool that computes the metric
ourselves from each country's live catalogue.

Started with a discovery pass over the six Phase B portals (live, national only,
no europa.eu): FR udata, DE/RO/HU CKAN, NL CKAN-DONL, EE custom NestJS. FR, DE,
RO and HU expose a national DCAT-AP RDF feed; NL and EE do not. That shaped the
design: a per-country adapter layer with the DCAT-AP RDF route as the common
path (rdflib gives a per-dataset graph that drives both the field-counting and
the SHACL conformance), and JSON adapters where there is no national RDF, with a
DCAT-AP graph synthesised from the JSON for conformance.

Scope is nine metrics (Q12, Q13, Q16, Q17, Q18, Q21, Q22, Q25, Q27). Q26/Q28/Q29
are flagged ambiguous in `docs/CATALOGUE_METRICS.md` with proposed definitions
awaiting sign-off; P29 (events) and Q2 (a harvesting self-report) are out of
scope. Conformance (Q16) runs the official SEMIC DCAT-AP 2.1.1 mandatory SHACL
shapes through pyshacl; the band comes from the question's own `allowed_answers`,
never from ground truth. Raw harvests cache gzipped on disk (gitignored, FR/DE
are 74k/151k datasets); the committed receipt is two new tables. The tool routes
in through `run_researcher` (before web search) and a recompute Verifier that
re-derives the band from the cache and passes iff it matches.

Validation was the interesting part. The tool never reads ground truth to
compute; it is read only afterwards to score. Results (exact/near/differ over
nine): HU 8/1/0, NL 5/0/4, DE 4/2/3, FR 4/1/4, RO 3/3/3; EE could not be
harvested (403, IP block). Three findings fell out, none of them tool errors.
(1) The self-report ceiling: France was awarded full marks self-reporting `>90%`
everywhere, but our recompute reads 37.8% licence coverage and 31.9% mandatory
conformance. The first sample read higher (66.9%) because the udata feed is
order-biased; the 5,000-dataset figure is the better estimate. (2) Strict SHACL
catches real non-conformance: DE reads 4.2% because its checksums omit the
mandatory `spdx:algorithm`, which the `>90%` self-report hides. Our Q16 is a
stricter lens than the MQA's per-property scoring, by design. (3) The tool
surfaces questionable ground truth: ODMI's recorded RO answers for several
questions are contradicted by a live catalogue that clearly exercises them, so
here the recompute looks more accurate than the gold.

Two route findings worth keeping: HU and RO publish a DCAT-AP RDF feed that
carries no `dct:license` at all, so they harvest via CKAN JSON instead;
validating HU also exposed two synthesis bugs (untyped dates failing the
mandatory shapes, and CKAN download-URL fidelity) that were fixed. 33 new
offline tests; 246 non-live passing.

Next: a fuller FR/DE harvest for population figures (the samples are
order-biased), the three flagged ambiguous metrics once their definitions are
signed off, and an EE retry from a non-blocked IP.

---

## 2026-06-02 — Session 16: cancel button on active subtrio cards

Small Run Console affordance with a careful destructive path behind it. Each
active card now carries a ✕ in the top-right. Clicking it aborts that one
subtrio and removes everything it has written, so a mis-fired or stuck run can
be cleared without hand-editing the database.

The implementation hangs off two facts already in place. The coordinator
records its own `os.getpid()` in `subtrio_status.process_pid` when it opens the
status row, so each in-flight run is individually addressable. And every
phase2_* table carries `pair_run_id`, which is the subtrio_id, so a run's rows
can be deleted in isolation from any earlier finalised run of the same
(question, country) pair.

`db.cancel_subtrio` reads the pid, confirms it still belongs to this
coordinator with a `ps -ww` command-line check (guarding against PID reuse on a
shared machine), sends SIGTERM and escalates to SIGKILL if it lingers, then
deletes the run's rows across the four phase2_* tables and `subtrio_status`.
The coordinator has no SIGTERM handler, so it dies without running any teardown
and cannot rewrite a status row after the delete. `claude_usage_log` is left
alone, same as `delete_pair`, so the cost receipt survives. Read-only deploys
short-circuit before any kill or delete.

The dispatcher copes with the kill on its own: the coordinator's exit code is
not the rate-limit sentinel, so the dispatch thread just releases its semaphore
and lets the next pair start. New `tests/test_cancel_subtrio.py` pins the
scoping (only the target run goes, siblings and the usage log stay) and the
unknown-id no-op.

---

## 2026-06-01 — Session 15: search knobs as experiment conditions (D31)

Follow-on from the DIY work. The DIY pipeline costs five to eight times the
Claude calls of Tavily per pair, because it runs the extraction on our own
model (up to five snippet-picks per search). The obvious lever is to drop the
search knobs: fewer queries, fewer results per query. But the knobs were
hard-coded, so there was no way to test that trade-off.

Threaded the three knobs end to end: provider, max-results-per-query, and a
query cap, from `dispatch_subtrios` through `run_coordinator` and `coordinate`
into `run_researcher` / `run_verifier`, where they reach `search_many` (which
already accepted provider and the result cap, it just was never passed one).
Defaults are untouched, so existing main runs are byte-for-byte the same;
`tests/test_search_knobs.py` pins both the threading and the no-change default.
The Run Console grew an optional experiment block (provider, results, query
cap, experiment_id, condition_label) that forwards the knobs to the dispatcher.

The experiment itself (D31): hold provider=diy, the models, and the pairs
fixed, vary only the knobs, and compare `diy_full` (3x5) against `diy_lean`
(2x3), with `diy_q3r3` (3x3) to see which knob carries the cost. Quality is
accuracy against ODMI ground truth; cost is calls/tokens/£/retries per pair
from `claude_usage_log`. The one to watch is retries: a leaner search that
fails more often triggers another full round, so a cheaper per-search config
can be dearer per pair. Defined and runnable, not yet run.

Also flagged a pre-existing broken test (stale page path in
`test_apptest_handoff`) for a separate fix. 215 non-live tests passing.

---

## 2026-06-01 — Session 14: DIY-Tavily fixed and benchmarked (D29)

Came back to the DIY search pipeline now that the June search quotas had
reset. Started by critically assessing why the layer-2 snippet-quality
fixture was stuck at 31%, and researched how Tavily and Brave actually work
(two cited research briefs; the load-bearing finding is that both extract
main content, chunk it into ~500-char windows, and rerank the chunks against
the query rather than truncating a page and handing it to one model call).

**Root cause (not the picker, the input).** A throwaway no-Claude diagnostic
(`evaluation/diagnose_extraction_ceiling.py`) measured where the accepted
evidence quote survives at each pipeline boundary. With the old path the
quote was present in the picker's input only 38% of the time; with
trafilatura run on the raw HTML, 78%. The bug was ordering: `fetch_text`
stripped tags and truncated to 4000 chars before trafilatura, so the picker
ate script/nav/cookie soup and trafilatura was a dead `is_html=False` no-op.
The picker was performing at its 38% ceiling. Classic fix-the-input, not the
symptom.

**Fix (TDD).** New `fetch_html` / `fetch_rendered_html` return raw HTML;
`search_diy._fetch_and_clean` runs trafilatura on the raw HTML then caps;
picker `PAGE_TEXT_CAP` 8000 → 16000 (prompt v2). The layer-2 test was also
wrong: it scored overlap with a raw byte match instead of the project's own
`substring.normalise` (what the Verifier actually accepts on). Corrected both;
snippet quality 31% → 58% live.

**Adjudicated DIY-vs-Tavily (the real metric).** Per Benjy's steer, the right
question is not "did DIY reproduce Tavily's exact quote" but "given the
question, whose evidence answers it better". Built a blind, position-swapped
Opus adjudicator (`search_adjudicator` prompt/tool; `evaluation/diy_vs_tavily.py`)
that sees the ODMI gold answer and both systems' evidence as System A / System
B. The smoke test caught a real harness bug (queries were joined to questions
on `run_id`, a batch id, so Q12's query bled onto PT33/Q18; fixed to
`pair_run_id`, and fixed the same latent bug in `build_snippet_fixtures.py`
that had mislabelled every fixture Q6/FR). A first run came back over-strict
(it treated ODMI's justification as a checklist); re-anchored the judge on the
answer label (per D22) and re-ran.

**Result (36 FR pairs, vs Tavily basic):** DIY 12 wins, 2 ties, 4 losses, 18
both_fail. On the 18 decisive pairs DIY is not worse 78% of the time and
out-wins Tavily 3:1, leading on every answerable dimension. That meets the
≥80%-as-good target within the noise (n=18, 67% judge position-consistency).

**The bigger finding.** Half the questions, and all nine Quality questions,
both-failed: their gold answer is an MQA metric on the deny-listed
data.europa.eu (D24) or a questionnaire self-report, so no open-web search can
reach them. That caps the swarm's ceiling on those questions independent of
provider, and is worth a methodology note in its own right.

**Robustness, surfaced by the eval and fixed:** `_extract_json` now recovers
JSON wrapped in fences with trailing prose (the Opus judge did this), and
`pick_snippet` degrades to an empty result instead of crashing when the model
emits unescaped inner quotes inside the JSON. Both also harden the live swarm.

**Next.** Chunk + rerank on the picker input (research Tier-1) is the lever to
clear 80% unambiguously, but it is diminishing-return against the sample noise
and the deny-list ceiling, so it is deferred. The agreed 5-provider A/B is the
better next use of effort. 213 non-live tests passing.

---

## 2026-05-26 — Session 13: D28 Phase 2 end-to-end

Five staged commits in one session. The five answer shapes (binary,
percentage_band, ordinal_magnitude, count_band, categorical) now flow
from the DB into the agents and back out through the dashboard.

**Stage A** — `scripts/migrate_d28_shapes.py`. Adds `answer_shape`
and `allowed_answers` JSON columns to `questions`. Classifier maps
`response_scoring` strings to one of the five shapes. Output: 124
binary, 12 percentage_band, 3 ordinal_magnitude, 2 count_band, 2
categorical. Adds the `inconclusive` literal to `AnswerLiteral`.
Migrates the 22 honest-other rows in `phase2_final` (plus their 38
researcher / 46 verifier upstream rows) from `other` to
`inconclusive`. Tests in `tests/test_d28_classifier.py` (15 cases)
lock in the classification rules. Q2's duplicate `1` / `'1'` keys
in the ODMI rubric are deduped at classification time.

**Stage B** — shape-aware agents. `AnswerLiteral` becomes
`LegacyAnswerLiteral` (documentation only); `answer` /
`verifier_answer` / `adjudicator_answer` are now `str` with a
length sanity check, validated at runtime via the new
`agents/tools/answer_shapes.py` module. `ResearcherInput`,
`VerifierInput`, `AdjudicatorInput` carry `answer_shape` and
`allowed_answers`. Researcher prompt V3: includes an "Answer space"
block listing the allowed labels; collapses honest uncertainty to
`inconclusive` rather than `other`; `other` is only emitted when
it appears in the ODMI rubric. Verifier prompts all bumped to V3
with shape-aware counter-evidence rules; the negation strategy now
branches the inversion direction per shape rather than hard-coding
yes / no. The adversarial query-gen prompt bumped to V2. Adjudicator
V3 receives the same answer space. Each runner post-validates the
emitted label and normalises case differences. 13 new tests in
`tests/test_answer_shapes.py`.

**Stage C** — `near_match` SQL. `_MATCH_STATUS_SQL` adds an EXISTS
subquery over `questions` and `json_each(allowed_answers)` that
finds adjacent-band misses on the three ordered shapes and tags
them `near_match`. `accuracy_summary()` now returns both `accuracy`
(exact) and `accuracy_within_one_band` (counting near matches as
hits). `country_outcome_counts()` adds the new outcome label. Nine
integration tests in `tests/test_match_status_near_match.py`.

**Stage D** — dashboard. Match badge palette gains a yellow
"Adjacent band (D28)" tile. Results KPI strip is five tiles
(Pairs, Match, Near, Differ, Within one band). Database page KPI
strip splits Match / Near / Differ and shows both exact and
within-band accuracy. Coverage filter dropdown adds "Near match
(adjacent band)". Analytics per-group table adds a `within-band %`
column next to `match %`. Home page country chart adds a yellow
band for the near-match outcome; the KPI accuracy caption mentions
near matches when present. Questions page now shows the `Shape`
column so it's obvious at a glance which questions use band /
ordinal / categorical answer spaces.

**Stage E** — tests + smoke-test. 13 new tests in
`tests/test_shape_aware_prompts.py` confirm the allowed-answer
list propagates from the DB through the input models into the
user messages seen by Researcher, Verifier (all four strategies),
and Adjudicator. Smoke dispatch of Q12:FR (a percentage_band pair)
booted cleanly: subtrio_status row written, Coordinator reached
the search stage. **Phase 3 — the actual re-dispatch of the 19
forced-collapse pairs plus broadening to the other 22 non-binary
questions across FR / DE / NL / RO — is deferred**: both Tavily
and Brave search quotas are currently exhausted (per the May 25
incident logged on D26 / D27). The shape-aware pipeline is ready
and tested; it re-runs against the new schema as soon as D29
(DIY-Tavily) lands in June.

Test count: 122 passing (39 baseline + 15 classifier + 13
answer_shapes + 9 match_status + 13 shape-aware prompts + 33
that were already there from prior work). All in `pytest -q`.

**Open issues / followups.**
- The smoke-test subtrio for Q12:FR (`c19828cb`) was reaped to
  `orphaned` after the search step failed. Once D29 lands the
  same pair can be re-dispatched cleanly.
- `agents/tools/band_check.py` was considered but not built. The
  idea: extract percentages from the Researcher's evidence quote
  and check whether they fall in the claimed band. Useful but not
  load-bearing for the dissertation. Worth adding in Phase 3 once
  we have real band-shape pairs flowing through.
- The Verifier negation strategy's shape-aware language should be
  empirically compared against the V2 yes/no version once both
  produce real data. Q12 in particular is where the new prompt
  earns its keep.

---

## 2026-05-26 — Session 12: per-shape answer schema, forced-collapse cleanup (D28)

Working through what the swarm can actually answer turned up a
structural mismatch. The Researcher / Verifier / Adjudicator output
is constrained to `Literal["yes", "no", "other", "not_applicable"]`
([agents/models.py:30](agents/models.py:30)), but only 121 of the 143
ODMI 2025 questions have a yes/no rubric. The other 22 want a
percentage band (`>90%` to `<10%`), an ordinal magnitude
(`all` to `none`), a count band (P29's `yes, >9` etc., Q13's
`1-4` / `5-10` / `>10`), a small categorical (P14's `top-down` /
`bottom-up` / `hybrid`), or a fixed timing bucket (Q3). On those, the
swarm had no choice but to collapse to `other`, which throws away the
discrimination ODMI scores on. A `71-90%` answer scores 20, `10-30%`
scores 2; both would have been `other` today.

**Decision.** D28: per-shape discriminated union with five shapes
(`binary`, `percentage_band`, `ordinal_magnitude`, `count_band`,
`categorical`). Each question carries its shape via a new
`answer_shape` column on `questions`, plus an `allowed_answers` JSON
column where band labels vary per question. Considered the flat
`answer: str` validated against `allowed_answers` alternative; the
shape is worth the extra design work because (a) Verifier prompts
need to branch on shape anyway to express "find evidence the right
band is one step lower", (b) substring-check verification needs
different code paths for yes/no versus numeric bands, and (c)
near-miss scoring in evaluation (a useful dissertation result)
requires ordered bands rather than opaque strings.

**Cleanup, this session.** The DB held 148 finalised pairs, 41 with
`final_answer = 'other'`. Split:

- 19 forced collapses on non-binary questions. The swarm had no way
  to express the right answer. Hard-deleted along with their
  upstream Researcher (39), Verifier (39), Adjudication (3), and
  `subtrio_status` (19) rows. Backup at
  `data/odmi.db.bak-pre-D28-20260526T100409Z`. Cascade SQL ran in
  one transaction.
- 22 honest "couldn't tell" outcomes on binary-rubric questions.
  Kept. These are real evaluation signal: the swarm had `yes` and
  `no` on offer and picked `other` for a reason (D24 forbidden-
  source refusals, low confidence, or honest uncertainty).

DB now at 129 finalised pairs, $13.28 (~£10.49) cumulative spend.

**Still to build.** Phase 2 of D28: schema migration on `questions`,
classifier pass to tag every question with its shape, discriminated
union in `agents/models.py`, branched prompts for Researcher /
Verifier / Adjudicator, `near_match` state in `_MATCH_STATUS_SQL`.
Phase 3: re-dispatch the 19 deleted pairs under the new shape, plus
broaden to the other 21 non-binary questions across FR / DE / NL /
RO.

**Followups.**
- Verifier prompt rewrite for each non-binary shape. The current
  "if Researcher said X, find evidence for not-X" rule doesn't
  translate cleanly to bands.
- Substring-check logic needs a number-extraction path for
  percentage bands. Yes/no can keep its literal substring match.
- Dashboard will eventually need a shape-stratified accuracy
  breakdown (binary-question match rate vs. band-question match
  rate vs. ordinal match rate). Worth a dissertation chapter.

---

## 2026-05-14 — Session 11: hard ban on ODMI sources

Walked through the swarm with one question: where could an ODMI
publication contaminate evidence? The audit turned up two
smoking-gun problems and a thirty-row contamination history.

**Smoking guns.** First, `agents/tools/validator.py` had
`data.europa.eu` in `_DEFAULT_TRUSTED["FR"]` and `_DEFAULT_TRUSTED["EU"]`
with a trust score of 1.0. Every ODMI URL was treated as the most
authoritative source the swarm could possibly cite. Second, the
Verifier disprove prompt (line 208) explicitly listed
"the European Commission's own ODMI publication" as a top-tier
authoritative source — a direct instruction to the model that the
ground truth was a valid source.

**The deny-list.** New module `agents/tools/blocked_domains.py` is
the single source of truth. Twelve domains
(`data.europa.eu`, `publications.europa.eu`, `op.europa.eu`,
`europeandataportal.eu`, web archive caches, Google cache mirrors)
plus seven path fragments (`/open-data-maturity`, `/odmi`,
`merged_responses`, `2025_odm_questionnaire`, etc.). `is_blocked(url)`
and `blocked_reason(url)` are the two public helpers.

**Five-layer defence.** `agents/tools/search.py` passes
`exclude_domains` to Tavily, adds `-site:` clauses to every Brave
query, and post-filters results through `_scrub_blocked()` regardless
of provider. `agents/tools/fetch.py` refuses `fetch_text`,
`fetch_rendered_text`, and `head_ok` with
`failure_mode="blocked_data_leakage:<reason>"`. `validator.py`
force-returns 0.0 for any blocked URL and no longer treats
`*.europa.eu` as authoritative by pattern. Researcher v2 prompt and
all four Verifier v2 prompts spell out the forbidden-sources list
and the `rejection_reason="forbidden_odmi_source"` tag. Last line:
`scripts/check_data_leakage.py` scans the three URL columns across
the swarm tables, exits non-zero on any hit, and offers `--purge`
to delete tainted pair_runs.

**Historical contamination.** The audit on the existing DB flagged
30 violations (8 Researcher `source_url` rows, 18 Verifier
`counter_source_url` rows, 4 phase2_final `final_source_url` rows)
all on `data.europa.eu`. These pre-date D24 and demonstrate the
problem was real. They'll be purged once Benjy reviews.

**Tests.** New `tests/test_blocked_domains.py` (30 cases): known
forbidden hosts, blocked path fragments, legitimate URLs, empty
and malformed input, deny-list immutability sentinels. All pass.
`pytest` added as a uv dev-dependency.

**Followups.**
- Run `--purge` on the audit script when ready, then re-run any
  affected pair_runs through the new code path.
- The "narrow domain → wide fallback" branch in
  `agents/researcher.py` still widens to the open web when trusted
  domains yield zero results. The new deny-list will refuse ODMI
  URLs in the wide fallback too, so this is safe, but worth
  watching once we run on harder questions.
- Verifier resume (only Researcher resume is implemented from
  session 10) is still the next architectural gap.

**Harness CLI.** New `scripts/harness.py` is the one-stop entry
point for the operations I'd otherwise have to compose by hand:
`status` for DB summary (filterable by country), `pending` and
`recent` for the queue, `audit` and `purge-leakage` for the
data-leakage workflow, `run --country FR --budget-gbp X` for
budget-gated dispatch (computes avg pair cost from
`claude_usage_log` and selects the head of the pending list that
fits), `run-pair QID CC` for a single named pair. Read-only by
default. Destructive commands require `--yes`; without it they
print the planned action and exit. Slide deck regenerated with a
"DATA-LEAKAGE GUARDRAIL (D24)" callout next to the existing
termination-rule callout on the "How it works" slide. Also
fixed a latent bug in the audit script: `_PURGE_TARGETS` now
uses `phase2_adjudications` (the actual table name) and
`subtrio_status.subtrio_id` (the correct column there), not the
imagined `pair_runs` parent table or `phase2_adjudicator_runs`.

---

## 2026-05-14 — Session 10: resume from partial subtrios

Follow-up to session 9. Since CLIProxyAPI strips Anthropic's
rate-limit headers, we can't predict when the Claude Max 5-hour wall
will hit. Batches dying mid-flight is therefore a fact of life, and
the answer has to be "tolerate it gracefully" rather than "avoid it."

**The contract.** Half-filled `phase2_researcher_runs` or
`phase2_verifier_runs` rows are fine on their own — none of the
dashboard surfaces treat them as completed. The only completion
marker is a `phase2_final` row, which is written from a single point
at the end of `coordinate()`. If the process dies before that point,
the pair counts as not-done everywhere. That contract was already in
place; today's change adds resume to it.

**Resume logic.** At the top of `coordinate()`, before the retry
loop, look for a prior subtrio_status row for the same pair that:
- has a `phase2_researcher_runs` entry with retry_count=0,
- never produced a `phase2_final` row, and
- is either orphaned / interrupted_rate_limit / failed, or just
  stale (no update in the last 60 minutes).

If one is found, mark the prior subtrio_status row
`stage='superseded'` with a reference to the new subtrio_id, then
load the prior Researcher row back into a ResearcherOutput. The new
subtrio's retry-loop first iteration sees `resumable is not None` and
short-circuits the Researcher step entirely; the Verifier runs on the
cached Researcher output. Retries 1+ run Researcher normally if the
Verifier rejects.

**Cost / audit.** The resumed Researcher's tokens stayed in
`claude_usage_log` under the prior subtrio_id (never deleted). The
new subtrio's only charges are Verifier + possibly Adjudicator. The
`researcher_run_id` foreign key on the new Verifier row points back
to the prior Researcher row, so the audit trail still works.

**What's not handled (yet).** Verifier resume. If a subtrio dies
mid-Adjudication, we still re-run the Verifier on the next attempt
(the resume only short-circuits Researcher). That's fine: the
Verifier is cheap relative to the Researcher and the Adjudicator
rarely fires. Punt this until we see it actually bite.

---

## 2026-05-14 — Session 9: search resilience, trusted domains, rate-limit probe

Tavily May credits are running low. The session pivots to "still
serving searches after Tavily's quota wall."

**Probe.** `scripts/probe_ratelimit.py` fires one Sonnet call via
CLIProxyAPI on localhost:8317 and dumps every response header. The
result: six headers, none of them `anthropic-ratelimit-*`. The proxy
strips them, so we can't read Claude Max's remaining-capacity through
this path. The £ soft limit on the sidebar stays as a guessed
arithmetic-equivalent for now; bypassing the proxy with a direct
Anthropic API key would be the only way to read the real signal.

**Brave fallback.** `agents/tools/search.py` rewritten as a single
`search(query, ...)` that tries Tavily, catches
`UsageLimitExceededError`, flips a session-scoped flag, and falls back
to Brave Search for the rest of the run. Brave's `include_domains`
gets translated into a `site:` clause group. `session_usage()` returns
per-provider counts plus the exhausted flag so the dashboard can show
which provider served what.

**Trusted domains.** New `agents/tools/trusted_domains.py` plus six
JSON files in `data/trusted_domains/`. Each country lists its national
open-data portal plus 4-8 authoritative government domains. The
Researcher's search step now narrows on `include_domains` first; if
the narrow search returns nothing, a wide retry runs automatically.
The expected effect is a meaningful quality lift (less random
re-publication noise in results) and a small Tavily-credit save where
the narrow search returns enough. `data.europa.eu` is deliberately
absent from every list because D22 deny-lists it (host of the ODMI
ground-truth assessments).

**Bug fix.** `dashboard/pages/2_Results.py` `_render_card` blew up
with `'float' object has no attribute 'strip'` when pandas inferred
some `final_answer` values as floats from SQLite. Hardened with
`pd.notna(...)` + `str(...)`.

**What's next.** If Tavily credits actually run out and we burn
through Brave's free 2,000-query monthly cap too, the architectural
fix is "skip search entirely for Portal-dimension questions; fetch the
trusted portal URL directly via Playwright as the primary evidence
source." That's bigger surgery to the Researcher and is left for
session 10.

---

## 2026-05-13 — Session 8: Database page, per-pair delete, dedup, £

A second pass on top of Session 7's ground-truth pivot. The pieces
that landed:

**Database page.** New `dashboard/pages/5_Database.py`. Shows the full
5,148-pair coverage grid (every ODMI question × country, with the
latest swarm answer joined in if any). Filters: country, dimension,
coverage state (`All` / `Covered` / `Not yet covered` / `Matches` /
`Differs`), free-text search across question_id, ODMI answer, and
swarm answer. Below the grid: a delete-a-pair form that previews how
many rows would be removed from each table before the user confirms.

**Per-card delete on Results.** Each Results card grew a
`🗑 Delete all swarm rows for this pair` expander. Two-step
confirmation. `claude_usage_log` is left alone so cost audit stays
intact.

**Run Console duplicate check.** `db.already_finalised(qids, ccs)`
returns one row per requested pair that already has a `phase2_final`.
The launcher renders an amber warning with the list. Default is to
skip the duplicates; an opt-in checkbox runs them anyway. To support
sparse dispatches, `scripts/dispatch_subtrios.py` gained a
`--pairs QID:CC` CLI argument, and the Run Console always passes
that now instead of `--questions × --countries`.

**Progress strip.** Top-of-page on the Run Console: five small
metric tiles (In flight / Researching / Verifying / Adjudicating /
Queued) plus an `st.progress` bar for the most recently dispatched
batch. Updates every 1.5 s as a separate fragment.

**Currency switch.** Every cost display now reads as £. New
`dashboard/lib/currency.py` exposes `USD_TO_GBP=0.79` and
`format_gbp()`. Sites updated: Home KPI strip and hero, sidebar
session widget, Run Console pre-flight, Results card technical
details, Costs page chart + tables, generate_slides.py KPI, and every
runner-script CLI print (`run_coordinator`, `run_researcher`,
`run_verifier`, `dispatch_subtrios`). Soft-limit slider takes £
input and converts to USD for the dispatcher. The
`estimated_cost_usd` SQLite column is unchanged.

**Doc sweep.** SPEC.md change log + Current Status + "Where to look
for what" updated. CLAUDE.md notes the £ display layer. README's
quickstart already covered the relevant commands so no rewrite
needed. PROJECT_LOG (this entry) is the narrative.

**Memory.** New feedback memory captures the "after a substantial
change, sweep the canonical docs and commit + push" ritual so future
sessions don't drift again.

**What's next.** Same as Session 7's next-section: scale to harder
ODMI dimensions, add Hungary and Estonia, run the Verifier strategy
comparison.

---

## 2026-05-13 — Session 7: ODMI ground truth supersedes hand-marking

The hand-mark workflow has been the dangling tail of D8 for weeks. This
session it got removed.

**The trigger.** Realising that `2025_odm_questionnaire_data.xlsx` ships
the `merged_responses` sheet: 5,148 (question, country) rows with the
country's actual answer, ODMI's accepted decision, awarded score, and
the rationale text. Every pair already has ground truth. The custom
three-dimension rubric and the hand-mark CSV workflow were both
constructed before this fact was used.

**The pivot.** Added a new SQLite `ground_truth` table and
`scripts/load_ground_truth.py`. Loaded all 5,148 rows for cycle 2025.
Replaced the rubric stratification axis with the ODMI dimension axis
(Policy / Portal / Quality / Impact) which is already in the data.

**Match logic.** `dashboard/lib/db.py:_MATCH_STATUS_SQL` does
case-insensitive trimmed comparison of `final_answer` against
`response`, with a `yes`-prefix special case so swarm `yes` matches
ODMI multi-tier responses (`yes, 3-5`, `yes, >9`, etc.).

**Dashboard.** Home KPI strip now shows Accuracy vs ODMI; country chart
splits bars into Matches / Differs from ODMI rather than Verifier
success / failure. Results Cards view shows ODMI's recorded answer
next to the swarm's with a match badge and an expandable ODMI
explanation. Hand-marks page removed from the sidebar.

**Numbers at the moment of the cut-over.** 11 finalised swarm pairs
across FR / DE / NL / RO, all matching ODMI 2025 (Policy dimension,
high-resource countries). Total spend around $1.02. The 100% will not
survive the move to harder dimensions, which is the point.

**Spec.** D22 added (ground truth supersedes hand-marks; D6/D8/D9/D10
no longer operational; data-leakage deny-list flagged). D23 added
(Streamlit Cloud auto-deploys on push to `main`, verify the URL after
every dashboard-touching push). RQ2 reframed in METHODOLOGY.md.
Sections 3 and 4 of METHODOLOGY retained as historical record with a
header note.

**Slide deck.** Regenerated against the new schema. KPI strip now
reads Pairs finalised / Accuracy vs ODMI / Ground-truth coverage /
Total LLM spend. Country chart legend reads Matches / Differs from
ODMI 2025. Caveat strip explains that ODMI assessments are one cycle
old, so a disagreement is not automatically a swarm error.

**Doc sweep.** CLAUDE.md, README.md, SPEC.md, METHODOLOGY.md, and the
read-only-mode copy on the dashboard all rewritten to match.

**What is next.** Verifier strategy comparison (D15/Q12), scale-out
to harder ODMI dimensions, add Hungary and Estonia. Then the deny-list
mitigation for data.europa.eu in `agents/tools/search.py` before the
first big saturated run.

---

## 2026-05-13 — Session 6: Coordinator follow-ups

Short session. Two patches on top of the day-5 coordinator.

**`--dry-run` and `--walkthrough` flags on `run_coordinator.py`.**
- `--dry-run` short-circuits the five DB-write helpers
  (`subtrio_status`, `phase2_researcher_runs`, `phase2_verifier_runs`,
  `phase2_adjudications`, `phase2_final`). `claude_usage_log` is
  deliberately not gated: the tokens are real even when the "run" is
  fake, and suppressing the usage log would let the rolling 5-hour
  budget under-count actual Anthropic spend.
- `--walkthrough` prints every Researcher / Verifier / Adjudicator
  stage event to stdout. Off by default so dashboard-spawned
  subprocesses don't flood their per-batch log file.
- Implementation: two module-level booleans (`_dry_run`,
  `_walkthrough`) set at `coordinate()` entry. The five DB helpers
  short-circuit when `_dry_run` is True. The two `on_step` lambdas
  passed to Researcher and Verifier now chain through a verbose
  printer.
- Smoke test (P1/FR, `--max-retries 0 --dry-run --walkthrough`):
  R1: yes (0.88) $0.021. V1: fail (0.72) $0.035 (substring check
  correctly caught a stale guides.data.gouv.fr quote). Adjudicator:
  researcher_correct (0.82). Terminal: `accepted_by_adjudicator`.
  Five gated tables: zero new rows. Six `claude_usage_log` rows
  captured with subtrio_id and context labels intact.

**`docs/KNOWN_GAPS.md` written.** Forward-looking note documenting the
three deferred failure modes from the day-5 contract audit:
resume from interruption (D22-D25), CAPTCHA / 403 detection, human-queue
CSV writer. Each entry covers trigger condition, observable symptom,
current workaround, rough cost-to-build. Indexed from SPEC.md's
"Where to look for what" table. The idea is that when something
unexpected happens during a real run, the symptom-to-triage path is
short.

### Open at end of session

Same as session 5. The two patches don't change the "next session"
priority list:
1. Drive a real multi-question batch through the dashboard.
2. Migrate hand-marks from the Word doc to CSV + git commit (unlocks D9).
3. Carry the three KNOWN_GAPS items until a real trigger appears.

---

## 2026-05-12 — Session 5: Dashboard end-to-end + coordinator built

### Morning: failure-scenario probes and Verifier build

Ran the three probe questions through the Researcher to populate the DB
with realistic rows before building the Verifier:

| Q | Country | Answer | Conf | Notable |
|---|---|---|---|---|
| P1 | FR | yes | 0.75 | Researcher cited a data.gouv.fr blog post, not the actual law |
| I1 | FR | yes | 0.65 | Quote literally says *"Il n'existe pas de définition stricte"* — the model still answered yes |
| Q1 | FR | other | 0.20 | Correctly bailed with low confidence |
| P10-a | FR | no | 0.45 | Same Etalab URL as P10-b — citation drift |
| P10-b | FR | no | 0.35 | Same Etalab URL as P10-a — citation drift |

Built the Verifier (`agents/verifier.py` + `agents/prompts/verifier.py`)
with four strategy prompts: disprove, negation, steelman, blind. Smoke
tested with the default `disprove` strategy:

- **P1/FR**: Verifier failed, found the actual transposition ordonnance
  (`Ordonnance 2021-442` on Légifrance) and suggested it as the correct
  query. System worked as designed — Researcher's weak source was
  rejected, real legal text surfaced.
- **I1/FR**: Verifier failed and explicitly cited that the quoted text
  contradicts the yes answer. Pointed to the Code des relations entre
  le public et l'administration as the right place to look for a formal
  definition.

This established Phase 2 (Verifier) as functionally working before
moving to the dashboard.

### Afternoon: dashboard design and build

**Brainstorming and spec.** Worked through dashboard scope via the
visual companion. Settled on Streamlit + subprocess pool over
FastAPI+React (robustness vs build chain, the spec calls this a YAGNI
win). User added three requirements mid-design: per-model logging and
analytics, multi-country / multi-question selection through a browsable
Questions page, and Claude credit-fallback handling. Spec written to
`docs/superpowers/specs/2026-05-12-dashboard-design.md` and passed two
rounds of spec review (one round of fixes for: Adjudicator file did
not yet exist, RateLimitedShutdown contract undefined, model_defaults
included a query_gen role with no surface, pre-flight cost arithmetic
underspecified across model conditions, three minor enum mismatches).

**Phase 1 — agent infrastructure built.**
- `agents/errors.py`: `RateLimitedShutdown` exception and
  `EXIT_CODE_RATE_LIMITED = 42` constant. One source of truth for the
  rate-limit contract used by `llm.py`, the Coordinator, and the
  dispatcher.
- `agents/adjudicator.py` + `agents/prompts/adjudicator.py`: tiebreaker
  for retries-exhausted cases. Single LLM call, no web search. Auto-
  promotes to `escalate_human` if confidence drops below 0.6 (per
  AGENT_DESIGN §5.11.5).
- `scripts/run_coordinator.py`: per-pair state machine. Researcher →
  Verifier → (Adjudicator on retry exhaustion). Writes
  `subtrio_status` at every stage transition. **Plain Python rather
  than LangGraph** (deviation from AGENT_DESIGN §5 noted in the file
  header — the retry loop is linear; the graph runtime adds debugging
  overhead with no behavioural benefit at this scale).
- `scripts/dispatch_subtrios.py`: parallel pool. Pre-flight cost check
  with a three-level fallback (model-tuple → triple → pair → cold-start
  default of $0.10), live budget enforcement at the 5% low-water mark,
  and clean shutdown on exit code 42 from any child.
- `scripts/cleanup_subtrios.py`: orphan reaper. Finds
  `subtrio_status` rows stale > 10 minutes in active stages and marks
  them `orphaned`.
- `scripts/migrate_dashboard_tables.py`: idempotent ALTER for the
  three new tables (`subtrio_status`, `claude_usage_log`,
  `model_defaults`) so the existing DB didn't have to be wiped.
- `agents/tools/llm.py` instrumented: every LLM call now writes one
  `claude_usage_log` row, and `anthropic.RateLimitError` is caught and
  re-raised as `RateLimitedShutdown`. Added `usage_context` and
  `subtrio_id` kwargs to `call_for_structured` and threaded them
  through Researcher and Verifier so every usage log row carries the
  originating subtrio.

**Phase 2 — Streamlit dashboard built.** Nine pages plus the pinned
Claude-session widget in the sidebar.

- Home: KPI tiles + recent runs feed + hand-mark lock status + human
  queue snapshot. Live refresh every 2 seconds.
- Run Console: launcher (multi-country chips, multi-question chips
  from the Questions page, per-agent model dropdowns, strategy,
  parallel limit) with the pre-flight credit banner. Below: live
  subtrio cards showing the three-stage pipeline (Researcher → Verifier
  → Final) with stage-specific colour-coding.
- Results: three tabs (Researcher / Verifier / Final) with column
  filters and a JSON drawer for row inspection.
- Strategy Lab: pick a Researcher row, run all four Verifier
  strategies, see verdicts side by side (the D15 comparison).
- Hand-marks: read-only mirror of the CSV workspace. Reminds the user
  that editing happens in CSV + git.
- Questions: full filterable table of all 143 questions with
  hand-mark status badge and a "Send N → Run Console" hand-off.
- Prompts: versioned prompt browser with full prompt text.
- Models: defaults editor + per-model analytics + the D18 R×V
  pass-rate cross-product heatmap.
- Costs: rolling-window KPI tiles, daily cost chart, dimension/country
  breakdown, recent usage log.

### Evening: testing

**End-to-end coordinator smoke (P1/FR, max-retries=0):**
Researcher answered yes(0.72) → Verifier rejected → Adjudicator picked
researcher_correct (0.72) → `phase2_final` row written with
`terminal_status=accepted_by_adjudicator`. All six LLM calls wrote
`claude_usage_log` rows carrying the subtrio_id and a `context` label
identifying which agent made the call.

**Front-end tests (Playwright headless on Streamlit at :8520):**
9/9 pages clean. Found two real bugs during the run: pandas 3.0
rejected writing strings into a float column in the Models heatmap
(fixed by building it as `dtype=object` from the start); and
`st.data_editor` checkboxes can't be driven from Playwright in headless
mode (replaced with `st.multiselect` which is both more reliable for
the user and trivially testable).

**Streamlit AppTest cases:** 4/4 (Questions → Run Console hand-off via
session_state, Models / Costs / Strategy Lab page loads).

**Release smoke test:** opened the Run Console via AppTest, clicked
the Release button. A real `dispatch_subtrios.py` subprocess was
spawned (PID captured), the `subtrio_status` row was inserted, and
the log file was written under `dashboard/logs/`. SIGTERM cleanup
confirmed the subprocess responds.

### Contract audit

User flagged 32 questions about the contracts between
`run_coordinator.py` and the other agents. Audited the actual code
against each item. Most were correctly aligned; one real gap found and
fixed (subtrio_id wasn't being threaded through from Researcher /
Verifier to the LLM wrapper, so usage rows from those agents had NULL
subtrio_id). Five non-blocking deferrals identified:

- D22-D25 (resume semantics): no auto-resume from interrupted state.
  A rate-limited subtrio sits with `stage=interrupted_rate_limit` until
  manually re-released. Acceptable v1 because pre-flight is conservative.
- A7 (CAPTCHA detection): the Researcher does not detect CAPTCHA / 403
  pages and so the coordinator can't route them to a human queue.
- B10 (human queue CSV): `terminal_status=escalated_*` writes to
  `phase2_final` but no CSV at `data/human_queue/<batch_id>.csv` is
  produced.
- E26 / E27 (`run_coordinator.py` `--dry-run` / `--walkthrough`):
  runner is silent-mode only. The older `run_researcher.py` has
  `--walkthrough` for in-line stage inspection.
- Question-bank → SQLite import is empty. The Questions page falls
  back to the JSON file.

### Open at end of session

- D19 (Streamlit + subprocess pool), D20 (rolling-window credit
  enforcement), D21 (three new schema tables) need formal entries in
  `docs/SPEC.md` change log.
- User has not yet driven the live dashboard at scale (only single-pair
  smoke tests have run through it). A multi-pair batch through the UI
  is the next confidence-building step.
- Hand-marks are still in the Word document, not the CSV format. D9
  cannot be enforced until the migration happens. Until then, swarm
  rows are valid as exploratory output but not as evidence.

### Next session

1. Drive a real multi-question batch through the dashboard (suggest:
   Q1-Q5 for France, sonnet on all three roles, parallel=3) and watch
   the live cards. Confirm KPIs update in real time. Confirm Costs
   page reflects the new spend.
2. Migrate hand-marks from `data/ODMI_2025_Questions.docx` to
   `data/hand_marks/france_handmarks.csv` and commit (locks the lock).
3. Decide whether to tackle the five deferred items now (resume,
   CAPTCHA, human-queue CSV, --dry-run, questions DB import) or carry
   them as known gaps until a real workflow hits one.

---

## 2026-05-11 — Session 3: Reset and re-foundation

**What happened.** Five-week dormancy ended with an audit. The previous
`ODMI_Project_Knowledge.md` and `ODMI_Project_Setup.md` had drifted out of
sync with the repo (still claiming Supabase, Opus, and a built Phase 1
classifier). Both files removed by Benjy before this session.

**What got reverse-engineered.** The repo has the original scaffolding from
late March. SQLite schema present, zero rows. `agents/classifier.py` with
Pydantic models but no LLM call. `scripts/run_phase1.py` has the API call
plumbing but was never invoked. Two hand-marked France questions sit in the
Word document `data/ODMI_2025_Questions.docx` (P1 and PT4, both 9/9). No
LangGraph code anywhere.

**Decision made.** Option 3 confirmed (see D8 in SPEC.md). The rubric becomes
an analytical lens for stratifying swarm results, not a runtime classifier.
This removes the validation burden that was the main defensibility risk in
the original two-phase design.

**What was set up.**
- `CLAUDE.md` rewritten with audit-trail rules and the hand-mark lock policy.
- `docs/SPEC.md` rewritten. D8 (analytical-lens rubric), D9 (lock hand-marks
  before swarm runs), D10 (sample size and stratification), D11 (writing
  pipeline in the repo) added.
- `docs/METHODOLOGY.md` written. The rubric is now defined precisely with
  dimension-by-dimension scoring guidance. The hand-marking protocol is
  written so another evaluator could reproduce it.
- `data/hand_marks/` created with `PROTOCOL.md` and an empty CSV template
  for France.
- `docs/REPORT_PRELIM.md` scaffolded against the brief structure
  (Introduction, Background, Schedule).
- `docs/references.bib` skeleton.
- First git commit on `main`.

**Open at end of session.**
- Q5 (cycle for evaluation: 2024 vs 2025 vs both) still unresolved.
- Supervisor identity and meeting cadence still unset.
- 10-question pilot hand-mark set not yet selected.
- Notion master page still says Supabase + Opus. Needs sync.

**Next session.**
- Select the 10-question pilot sample for France hand-marking.
- Start the Introduction section of the preliminary report.
- Begin literature review for the Background section. Suggested seeds:
  ODMI methodology papers, agentic LLM evaluation benchmarks
  (GAIA, ToolBench, AgentBench), automated policy analysis (CivicBench,
  AI4Gov), hallucination mitigation in retrieval-augmented agents.

---

## 2026-04-01 — Session 2: Living spec set up, repo relocated

(Inferred from previous SPEC.md, now superseded.)

- Created the first version of SPEC.md.
- Confirmed CLIProxyAPI over the Anthropic API (D1).
- Confirmed SQLite over Supabase (D2).
- Moved repo from `~/Projects/odmi-agent-swarm` to `~/Desktop/Msc Project`.
- Identified that the LLM call in `run_phase1.py` is unwired and that
  Questions.xlsx had not yet been parsed into the workspace.

---

## 2026-03-27 — Session 1: Initial scaffolding

(Inferred from the original PROJECT_LOG.md, now superseded.)

- Created the repo structure: `agents/`, `data/`, `evaluation/`, `scripts/`,
  `docs/`, `tests/`.
- Wrote `pyproject.toml` with the Phase 1 dependency set.
- Wrote `scripts/setup_supabase.sql` (never applied, since dropped in D2).
- Wrote `agents/classifier.py` with the v1 rubric prompt and Pydantic models.
- Wrote `scripts/run_phase1.py` with dry-run support.
- Wrote `tests/test_classifier.py` unit tests for the Pydantic models.
- Identified that the Questions.xlsx needed to be obtained from
  data.europa.eu.
- Decided on dual tracking: markdown in repo (technical) plus Notion
  (research narrative).
