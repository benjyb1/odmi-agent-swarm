# Final Dissertation — Draft Scaffold (was: Preliminary Report)

> **Status (2026-06-23):** This file is no longer the 22 May deliverable. Per
> decision D14 in `docs/SPEC.md`, the 22 May submission was a results slide
> deck (`docs/PROGRESS_SLIDES_*.pptx`). This document is the scaffold for the
> final dissertation (due 2026-08-02), the examined submission. The Introduction,
> Background and Schedule sections mirror the dissertation brief. Methodology and
> Results sections have been added as fact-level stubs as the work progressed.
>
> **What is captured here is the project state, not finished prose.** Sections
> below hold bulleted facts and current figures for drafting against. The
> literature-review subsections in Section 2 keep their drafting prompts. All
> numbers trace to `docs/SPEC.md`, `docs/METHODOLOGY.md` and `docs/EXPERIMENTS.md`;
> read those for provenance before quoting any figure.

**Title:** AI Frameworks for Assessment of Data and Digital Technologies: An
Agent Swarm for the EU Open Data Maturity Index

**Author:** Benjamin Bream

**Programme:** MSc Advanced Computing, King's College London

**Supervisor:** TBC

**Final dissertation submission:** 2026-08-02

---

## Format compliance (KEATS brief, preliminary report)

- 10 pages A4 body, cover and references outside the count.
- 11pt minimum font size.
- Single line spacing minimum.
- 1.5cm minimum margins on all sides.

Body budget for the 10-page preliminary report (the Methodology and Results
sections below are scaffold for the longer final dissertation, not the prelim):

| Section | Pages | Words (~550/page) |
|---|---|---|
| Introduction | 3 | 1,650 |
| Background | 5 | 2,750 |
| Project schedule | 2 | 1,100 (mostly Gantt) |
| Total | 10 | 5,500 |

Citations and figures sit inside the count for whichever page they appear on.

---

## 1. Introduction

### 1.1 Domain and motivation

(TODO, prose. Establish ODMI in two paragraphs. What it is, who runs it
(Capgemini Invent for the European Commission), what it measures, how it is
currently collected (national representatives answer a questionnaire, manually
assessed), and why this matters: the index informs policy benchmarking and
funding allocation across 36 participating countries. Note the constraints of
the manual process: labour, inconsistency between assessors, slow refresh
cycles, weaker coverage and engagement for smaller countries.)

### 1.2 Problem statement

(TODO, prose. The manual methodology is a bottleneck. Frame the research
opportunity: agentic LLMs combined with retrieval can in principle automate the
evidence-gathering and answering steps. The open question is which questions
they can answer reliably, which they cannot, and whether the system abstains
honestly rather than fabricating an answer when the evidence is absent.)

### 1.3 Aims and research questions

Five research questions, aligned to `docs/METHODOLOGY.md` Section 2:

- **RQ1.** Can a multi-agent LLM system, with adversarial verification, answer
  ODMI questionnaire items at a quality level that approximates the existing
  human process for a controlled baseline country?
- **RQ2.** How does answer quality vary across the four ODMI dimensions (Policy,
  Portal, Quality, Impact) and the indicators within them? (Reframed at D22 from
  the original three-axis answerability rubric.)
- **RQ3.** How does answer quality vary across language and portal-maturity
  regimes? Tested by the two-stratum language contrast in the held-out
  evaluation set (D47): negative-rich low/mid-resource languages (stratum A)
  against higher-resource languages (stratum B). A flat false-positive rate
  across the strata supports language driving abstention not error; a rise in
  stratum A is the headline negative result.
- **RQ4.** What categories of ODMI question are systematically beyond the reach
  of agentic LLMs as currently constituted, and what reformulations would bring
  them in scope?
- **RQ5.** What is the trade-off between answer quality and computational cost
  (input/output tokens, wall-clock latency) across dimension, country and
  optimisation condition?

### 1.4 Objectives (status as of 2026-06-23)

1. End-to-end agent pipeline (Coordinator state machine, Researcher,
   adversarial Verifier, Adjudicator) against a baseline country. **Done.**
   Running end-to-end; first P1/FR pass and the Malta 60-pair baseline both
   finalised.
2. A reproducible evaluation set: ODMI's published `merged_responses` as ground
   truth (5,148 rows), superseding the original hand-marked rubric (D22).
   **Done.**
3. A deterministic, leakage-free pathway for the catalogue-computable Quality
   questions, independent of the deny-listed MQA (D30), plus automated portal
   discovery (D46). **Done.** 19 verified portal routes; registry coverage 6 to
   21 countries.
4. A base-rate-stratified held-out evaluation across eight countries, reported
   balance-aware and three-outcome (D47). **Pending the config freeze and the
   headline run (EXP-21).**
5. A failure-mode taxonomy (`docs/FAILURE_MODES.md`, FM-01..FM-34) with proposed
   question reformulations for the categories beyond reach. **Drafted.**

### 1.5 Dataset

- 2025 ODMI questionnaire: 143 questions, 4 dimensions, 17 indicators, sourced
  from data.europa.eu.
- Ground truth: ODMI's own published answers for every (question, country) pair,
  loaded from the `merged_responses` sheet into the `ground_truth` SQLite table.
  5,148 rows = 36 countries x 143 questions (`scripts/load_ground_truth.py`).
- Answer shapes (D28): 124 binary / 12 percentage_band / 3 ordinal_magnitude /
  2 count_band / 2 categorical.
- Answerability split (per question, never used to exclude): 119 web / 9
  catalogue-computable / 15 self-report.
- Data-leakage control: ODMI publishes its own answers on data.europa.eu, so a
  deny-list bans ODMI publications and the EU Data Portal as evidence at five
  layers (D24).
- 2024 cycle held back as an external-validity test set (D13).

### 1.6 Methodology in brief

(Half a page when drafted. Two operational pieces.) The evaluation compares each
finalised swarm answer directly against ODMI's published answer (D22); the
original answerability rubric is retained as historical analytical context only
(D6/D8/D9/D10 superseded). The swarm itself is a Researcher to Verifier to
Adjudicator pipeline driven by a plain Python Coordinator state machine (D3
amended; not a graph framework). Full methodology in `docs/METHODOLOGY.md`.

---

## 2. Background

### 2.1 Open data maturity assessment

(TODO, prose. The ODMI's place in the European open data policy stack. Reference
the annual ODMI report, the data.europa.eu portal, the Open Data Directive
(2019/1024) and the implementing regulation (EU) 2023/138 on high-value
datasets. Briefly note other digital index methodologies (UN E-Government
Survey, OECD Going Digital, World Bank Statistical Performance Indicators) to
establish the wider context.)

### 2.2 Agentic LLM systems

(TODO, prose. Define agentic LLM systems and where they sit between zero-shot
chat and full autonomous agents. Cover the standard architectures: tool-augmented
chains, multi-agent systems with role specialisation, retrieval-augmented
generation, and adversarial / red-team verification. Key references: ReAct,
AutoGen, recent multi-agent papers from 2024-2025. Note for honesty: the project
uses a plain Python state machine, not a graph-orchestration framework (D3
amended); the related-work discussion of graph runtimes stays as context, but
the system does not depend on one.)

### 2.3 LLM evaluation on real-world tasks

(TODO, prose. Benchmarks that approximate this problem: GAIA, ToolBench,
AgentBench, WebArena, MMLU-Pro. The literature gap: these test general competence
on synthetic tasks. ODMI is a real-world, multilingual, policy-evaluation task
with published ground truth, a different evaluation regime.)

### 2.4 Hallucination, faithfulness, and adversarial verification

(TODO, prose. The faithfulness problem in retrieval-augmented systems. Survey
mitigations: source citation, dual-confidence scoring, adversarial verifiers,
chain-of-verification. The argument for a Verifier prompted to disprove rather
than confirm, and for honest abstention under a confidence floor rather than a
forced guess. Tie to the project's deterministic quote-grounding gate and the
0.65 commit-confidence floor.)

### 2.5 Multilingual evidence and policy text

(TODO, prose. LLM performance on low-resource European languages. Relevant to the
held-out evaluation's stratum A (Bosnian, Macedonian, Montenegrin, Bulgarian) and
the dev-set low-resource cases (Maltese, Albanian). Document-level translation
versus native multilingual reading. The case for treating multilingual recall as
a retrieval question inside the DIY pipeline, not a provider comparison.)

### 2.6 Automated policy and benchmark analysis

(TODO, prose. Closer related work: AI for civic and policy analysis, AI for
academic benchmark production, prior attempts at automating index-style
benchmarks. The novelty: applying verified multi-agent retrieval to a policy
index that is currently manually collected, with empirical evaluation against
published ground truth.)

### 2.7 Gap statement

(TODO, half a page prose. Synthesise: (i) ODMI is a substantively important index
with a manual bottleneck; (ii) agentic LLM systems are now capable of the
component tasks; (iii) no prior work has applied verified multi-agent retrieval
to a real policy index of this scale with empirical evaluation against ground
truth; (iv) the failure-mode taxonomy that emerges is itself a contribution to
the agentic-AI evaluation literature.)

---

## 3. Methodology (fact stubs)

### 3.1 System architecture

- Three-agent swarm: **Researcher** (web search + read, structured answer with a
  quoted source passage) to **Verifier** (adversarial, four strategies: disprove,
  negation, steelman, blind) to **Adjudicator** (resolves accept/reject/retry and
  commits the final answer).
- **Coordinator** is a plain Python state machine (`scripts/run_coordinator.py`),
  not a graph framework (D3 amended). Linear retry loop with bounded retries.
- LLM access via CLIProxyAPI on `localhost:8317` on a Claude Max subscription
  (Claude Sonnet currently); no direct Anthropic API billing (D1).
- Every LLM call writes a receipt row (model version, prompt version, raw
  response, timestamp, cost) to `claude_usage_log`. Every prompt is versioned in
  `prompt_versions` (D5).

### 3.2 Retrieval

- Search is **DIY only** (Serper SERP + trafilatura extraction), per D43. Tavily
  and Brave are retired; the provider question is closed. The earlier
  Tavily/DIY/Brave fallback (D36) is superseded.
- Extraction fix (D29): trafilatura runs on raw HTML before truncation; snippet
  quality rose from 31% to 58%. A snippet-picker funnel selects the passage.
- A 30s fetch-stage blocker stops a run that stalls in retrieval (D43).
- Deny-list (D24) drops ODMI publications and data.europa.eu before retrieval,
  not after.

### 3.3 Deterministic catalogue pathway

- For the 9 catalogue-computable Quality questions, a deterministic tool harvests
  national-portal metadata and computes the answer (DCAT-AP RDF preferred;
  CKAN/udata/custom JSON fallbacks; SHACL conformance via pyshacl), independent
  of the deny-listed MQA (D30).
- Portal discovery (D46) probes each country's national portal from a committed
  seed list, verifies a sample through real adapters, and emits a provenance-
  tagged registry. 19 verified routes; registry coverage 6 to 21 countries; mean
  +6.5 points of open-web accuracy ceiling per newly covered country.

### 3.4 Abstention and honesty controls

- `inconclusive` is an abstention literal that retries then adjudicates, not a
  terminal failure label (D35).
- A 0.65 commit-confidence floor (D37): a sub-floor commit is downgraded to an
  honest `inconclusive` rather than a forced (usually defensive `no`) guess.
- The verification gate checks the evidence quote against the snippets the
  Researcher actually read, not a live re-fetch (D34); per-snippet, ellipsis-aware
  matcher v2 closes the cross-snippet splice gap.
- Finalisation trusts the Adjudicator's own answer (D32); retry queries are forced
  to diverge (D33).

### 3.5 Evaluation design (D47, supersedes the D42 matrix)

- **The finding that sets the design.** A country's ODMI score is almost exactly
  its binary yes-share (Pearson r = 0.98 across 36 countries). So guessing `yes`
  everywhere scores the country's ODMI score, and naive accuracy on a mature
  country just reproduces the ODMI ranking. Discrimination (correctly answering
  `no`) is only measurable where negative golds exist, which is the low-maturity
  tail. Maturity and base-rate balance are one axis, not two.
- **Development set (in-sample, 5 countries, tuning only):** NL, MT, NO, FR, AL.
  MT reclassified from held-out to in-sample (already burned by the verifier and
  model-variant programmes; about half its estate is low-resource Maltese, so it
  is not a clean English testbed).
- **Held-out evaluation set (8 countries, frozen, pre-registered rule):**
  - Stratum A (negative-rich, low/mid-resource language): BA, MK, ME, BG.
  - Stratum B (higher-resource language, as balanced as available): FI, HR, SE, BE.
  - About 1,144 (question, country) pairs, about 368 binary negative golds (261 in
    A, 107 in B), all four dimensions, all five answer shapes.
- **Why stratified, not random.** The false-positive / true-negative rate is a
  rare-event quantity concentrated in a few countries; a random country draw would
  be dominated by all-`yes` countries and leave the false-positive estimate
  unmeasurable. Case-control style oversampling of the rare class, pre-registered,
  is the defensible design.
- **Freeze protocol.** The pipeline (prompt versions and knob settings) is
  committed before the held-out run; the commit SHA is the lock. The eight are read
  exactly once, from a frozen pipeline. Stricter than D42's between-condition
  permission.

### 3.6 Reporting

- No single accuracy number. Balance-aware: per-class true-positive and
  true-negative rates with Wilson intervals, balanced accuracy, Youden's J,
  against the majority-class baseline (D38 R4).
- Three-outcome risk-coverage triangle: commit-accuracy (of committed answers),
  coverage (committed vs abstained), and the false-positive rate among commits
  (the safety metric), with the curve traced as the D37 floor moves.
- Stratified by ODMI dimension (Quality's deny-list / self-report ceiling shown as
  honest abstention, not hidden) and by answer shape (`near_match` for adjacent
  bands).
- ODMI gold can be one cycle old (D22), so swarm-vs-ODMI disagreements get a blind
  adjudication over frozen evidence and are reported as a band (lower bound treats
  every disagreement as a swarm error, upper bound excludes confirmed-stale gold).
- France stays in the report as a labelled degenerate-baseline contrast, to show
  empirically why raw accuracy is the wrong metric.

---

## 4. Results so far (in-sample / dev set; fact stubs)

> The held-out eight are untouched until the frozen headline run (EXP-21). Every
> figure below is development-set or apparatus evidence. Detail and provenance in
> `docs/EXPERIMENTS.md`.

### 4.1 Malta baseline (n = 60, done)

- 43 committed yes/no plus 17 honest `inconclusive` abstentions (D37).
- Committed accuracy 32/43; no-gold recall (TNR) 0.87 with 3 false positives of 23
  committed; yes-gold recall (TPR) 0.60; Youden's J 0.47; mean commit confidence
  0.58. Zero data-leakage in any finalised row. Batch cost about $4.98.
- Answerability split is the point: web questions reach 79% committed accuracy
  (30/38), self-report only 40% (2/5) with most abstaining.

### 4.2 Self-report ceiling, made measurable (D30)

- France self-reported `>90%` on licence coverage and conformance; the independent
  catalogue recompute reads about 38% licence coverage and about 32% mandatory
  conformance. The self-report ceiling is now a measured gap, not an assumption.

### 4.3 Confidence floor holds across countries

- Floor sweep pooled over 7 countries with stored data (n = 360, 67 negative
  golds, 6x the Malta sample): the 0.65 floor holds. Recovered-answer precision at
  0.50 is 0.76, under the pre-registered 0.80 bar; negative-class FPR barely moves
  on lowering (0.37 to 0.39). The three balanced countries (MT/NO/NL) all return
  0.65; only yes-skewed FR/EE lean lower, a base-rate artefact.

### 4.4 Verifier programme (EXP-11/12/13), closed (D45)

- Four pre-registered attacks on the incumbent verifier all returned null; the
  incumbent design is retained. The verdict decides only 9 of 237 in-loop commits,
  so the 0.65 floor is the binding precision control and the verifier's value flows
  through the Adjudicator (removing the layer costs 27 matches, +43 abstentions,
  -16 wrong; p < 0.002). Matcher v2 shipped.

### 4.5 Dev-set ablations (all null, incumbent retained)

- **EXP-14** (verifier live counter-search never vs always, NL n=51): null, keep
  `always`; removing it raises the no-gold false-positive rate.
- **EXP-16** (Adjudicator standard vs free attempt selection, NL n=51): null, keep
  `standard`; the selection headroom is real but free choice cannot bank it.
- **EXP-17** (snippet picker on vs off, NL n=50): null, keep `picker_on`; removing
  it left candidate recall unchanged and raised cost about 57%.

### 4.6 Confirmatory re-tests and the headline run (pending, all DIY-only)

- **EXP-18** breadth r5/r10 on FR+AL+NL (re-test of a one-NL-run breadth decision).
- **EXP-19** verifier never/always on NL+MT+AL (re-test of EXP-14 at wider n).
- **EXP-20** chaining baseline/chained on NL+AL (re-test of underpowered EXP-7).
- **EXP-21** the whole-system headline: the frozen production architecture
  end-to-end on the D47 held-out 8, balance-aware and three-outcome, no adoption
  rule. Gated on a config freeze, run after the re-tests.

### 4.7 Provenance and reproducibility apparatus

- SQLite at `data/odmi.db` (12 tables) is the single data store (D2); an examiner
  can replay every evaluation from logs alone.
- Experiment orchestration (D48) enforces the methodology by construction:
  forced `--no-cache` on retrieval/cost arms, sequential arms at one in-flight cap,
  preflight hard-fail on a held-out country / missing budget / unloadable deny-list
  / more than one knob per arm. Manifest + JSONL log per run.
- Streamlit dashboard (9 pages), live locally and on Streamlit Cloud, read-only on
  the public deploy. Costs displayed in GBP (USD_TO_GBP = 0.79).

---

## 5. Project schedule

### 5.1 Phasing

- **Phase 0 (to mid-May):** foundation. Repo housekeeping, locked methodology,
  preliminary report. **Done.**
- **Phase A (mid-May to mid-June):** baseline and swarm build. France baseline,
  full three-agent swarm, dashboard, ground truth loaded, catalogue pathway,
  portal discovery, Malta baseline. **Done.**
- **Phase B (mid-June to mid-July):** evaluation. Dev-set ablations (the EXP
  programme), confirmatory re-tests (EXP-18/19/20), config freeze, then the
  held-out eight-country headline run (EXP-21). **Underway.**
- **Phase C (mid-July to early August):** write-up. Final dissertation drafting,
  external-validity test against the 2024 cycle, failure-mode taxonomy, viva prep.

### 5.2 Milestones (revised 2026-06-23)

| Milestone | Status / target |
|---|---|
| Preliminary report submitted | Done (2026-05-22) |
| Three-agent swarm end-to-end | Done |
| ODMI ground truth loaded (5,148 rows) | Done |
| Catalogue pathway + portal discovery | Done |
| Malta dev baseline (n=60) | Done |
| Dev-set ablations (EXP-10/14/16/17, verifier programme) | Done |
| Confirmatory re-tests (EXP-18/19/20) | In progress |
| Pipeline config freeze (commit SHA lock) | Target ~2026-07-13 |
| Held-out 8-country headline run (EXP-21) | Target ~2026-07-20 |
| External-validity test against 2024 cycle | Target ~2026-07-27 |
| Final dissertation submitted | 2026-08-02 |

### 5.3 Gantt chart

(TODO. Figure 1. Gantt covering the milestones above, with parallel tracks for
the experiment programme, code, and write-up. Export as SVG so it drops into the
manuscript without re-rendering. Place under `docs/figures/gantt.svg`; the
directory does not yet exist.)

### 5.4 Risks and contingencies

| Risk | Mitigation |
|---|---|
| Swarm fails to terminate on some questions | Bounded retries; runaway circuit breakers on the dispatcher (D41), not a budget. |
| WAF / CAPTCHA blocks on government portals | Playwright fallback on WAF 403/429/503 (mitigated for data.gov.mt); honest abstention if still blocked. |
| Low-resource language failure | Treated as a DIY-internal recall question; honest abstention under the floor rather than a forced guess. |
| Claude Max rate wall mid-batch | Clean resumable 429 shutdown; the Coordinator resumes cleanly from committed rows. |
| Held-out set contaminated by tuning | D47 freeze protocol: pipeline locked by commit SHA, the eight read exactly once. |
| Single-supervisor unavailability | Supervision and observations logged to Notion; async feedback acceptable. |

---

## References

(Citations managed in `docs/references.bib`, currently about 11 entries. Build
the references list in the final PDF from that file. Background needs roughly
20-30 references for the prelim; aim for one citation per substantive claim.)

---

## Drafting notes (not part of the submitted report)

**Writing approach.** Draft in flat prose paragraphs in this file, then style to
KEATS format only at the end. Just hit the page count.

**Voice.** Plain academic register. UK English. No em dashes. No AI tells. Active
voice. Concrete claims. Run any drafted paragraph through the humaniser skill
before treating it as final.

**Citation density.** Background needs roughly 20-30 references. One citation per
substantive claim.

**Use of figures.** Two figures should suffice: a system architecture diagram
(Section 1 or 3) and the Gantt (Section 5). SVG sources under `docs/figures/`.

**Section length discipline.** If a section runs past budget, cut before
continuing. Margins, font and spacing are minimums in the brief; do not abuse
them to fit overlong content.

**State stubs are not prose.** Sections 3, 4 and the objectives/dataset bullets
are fact scaffolding pulled from `docs/SPEC.md` and `docs/METHODOLOGY.md`. Write
the prose from them; do not paste the bullets into the dissertation.
