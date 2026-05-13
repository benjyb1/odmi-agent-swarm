# Methodology

Locked methodological choices for the ODMI Agent Swarm dissertation. This is
the document an examiner reads to understand what was done and why. Changes
to anything here require a new numbered decision in `docs/SPEC.md`.

Last reviewed: 2026-05-13.

> **2026-05-13 update (per D22).** Sections 3 and 4 below — the
> three-dimension answerability rubric and the hand-marking protocol —
> are retained as historical record but are no longer operational.
> Evaluation now uses ODMI's own `merged_responses` answers as ground
> truth, stratified by the ODMI dimension (Policy / Portal / Quality /
> Impact) rather than a custom rubric tier. See Section 6 for the live
> evaluation methodology.

---

## 1. Domain and problem

The European Commission's Open Data Maturity Index (ODMI) assesses 36
European countries on their open data ecosystems each year. The 2025 cycle
contains 143 questions grouped under 17 indicators across four dimensions:
Policy, Portal, Quality, and Impact. Country experts (typically contracted to
Capgemini) collect evidence and answer the questionnaire manually. The full
collection runs for several months annually and is repeated in every cycle.
The methodology has well-known constraints: it is labour-intensive,
inconsistent across reviewers, and stretches the limited evaluation budget
available for smaller countries.

This project investigates whether an LLM-powered agent swarm can produce
ODMI-quality answers automatically and, more importantly, where such a system
succeeds and where it fails.

---

## 2. Research questions

**RQ1.** Can a multi-agent LLM system, with adversarial verification, answer
ODMI questionnaire items at a quality level that approximates the existing
human process for a controlled baseline country?

**RQ2.** How does answer quality vary across the four ODMI dimensions
(Policy, Portal, Quality, Impact) and across the indicators within
them? *(Reframed at D22 from the original rubric-tier formulation.)*

**RQ3.** How does answer quality vary across language and portal-maturity
regimes when the same system is run on a stratified six-country sample?

**RQ4.** What categories of ODMI question are systematically beyond the reach
of agentic LLMs as currently constituted, and what reformulations would bring
them in scope?

**RQ5.** What is the trade-off between answer quality and computational cost
(input tokens, output tokens, wall-clock latency) across ODMI dimension ×
country × optimisation condition? Are some classes of question
cheap-and-correct, others expensive-and-still-wrong, and where in this
surface does each regime sit?

---

## 3. The answerability rubric

Each (question, country) pair is scored on three dimensions, each on a 0-3
scale. The composite (0-9) maps to four tiers, but the dimensions are kept
separately so analyses can interrogate any one of them.

### Dimension 1: Evidence Accessibility (EA)

How findable is the evidence needed to answer this question through public
web sources for this country?

| Score | Meaning |
|---|---|
| 0 | No online evidence exists or is accessible. |
| 1 | Evidence exists but is hard to find: buried in PDFs, requires institutional access, or sits behind cookie walls / CAPTCHAs. |
| 2 | Evidence is findable with targeted search queries on the open web. |
| 3 | Evidence is prominently published on the national portal or other authoritative government domain. |

EA is country-dependent. A question may score EA=3 for France and EA=1 for
Latvia.

### Dimension 2: Answer Determinism (AD)

How objective is the answer? Could two independent evaluators reach the same
conclusion from the same evidence?

| Score | Meaning |
|---|---|
| 0 | Entirely subjective. Requires expert judgement or insider knowledge. |
| 1 | Mostly subjective. Reasonable evaluators would likely disagree. |
| 2 | Mostly objective. Clear criteria exist but interpretation is needed. |
| 3 | Fully objective. Binary yes/no, numeric, or directly verifiable from a single source. |

AD is largely country-independent. The rubric definition does not change
between countries, although evidence quality interacts with it.

### Dimension 3: Source Complexity (SC)

How many independent sources need to be consulted and cross-referenced to
construct a defensible answer?

| Score | Meaning |
|---|---|
| 0 | Requires synthesising 4+ sources across different domains. |
| 1 | Requires 2-3 sources that may conflict. |
| 2 | Requires 1-2 clearly authoritative sources. |
| 3 | A single authoritative source provides the complete answer. |

SC interacts with EA. A question may be answerable from one source (SC=3) but
that source may be hard to access (EA=1).

### Composite to tier

| Composite | Tier |
|---|---|
| 7-9 | Highly Likely |
| 5-6 | Likely |
| 3-4 | Unlikely |
| 0-2 | Very Unlikely |

### Role of the rubric (per D8)

The rubric is an analytical lens used to stratify swarm results. It is not a
runtime classifier. The dissertation's claims take the form "swarm accuracy
on (high EA, high AD) pairs is X%" rather than "the rubric predicts that
the swarm will succeed."

---

## 4. Hand-marking protocol

The audit trail behind the rubric is hand-marks, not LLM-produced scores.
The protocol is reproducible, time-stamped, and locked before any related
swarm run.

### Procedure

For each (question, country) pair:

1. Open the question text from `data/questions/odmi_2025_questions.json`.
2. Read the official 2024 ODMI answer for the country (where available, from
   `data/questions/2025_odm_questionnaire_france.xlsx` and equivalents).
3. Attempt to find evidence using ordinary web search (no LLM assistance,
   no agentic search). Record the queries used and the sources found.
4. Score each rubric dimension (EA, AD, SC) with a one-sentence justification
   per dimension.
5. Compute the composite and tier.
6. Record the result as a row in `data/hand_marks/<country>_handmarks.csv`
   with the columns defined in `data/hand_marks/PROTOCOL.md`.
7. Commit the file. The commit "locks" the hand-mark.

### Lock rule (per D9)

A hand-mark is "locked" when it has been committed to git. The SQLite mirror
`hand_marks` table stores the commit SHA in `locked_by_commit`. Any swarm
run that touches a (question, country) pair must verify that the
corresponding hand-mark was locked before the run started. Uncommitted
hand-marks are not eligible.

This rule exists to prevent the same researcher from drifting hand-marks
toward swarm outcomes after the fact.

### Sample size and stratification (per D10)

Pilot batch: 10 questions for France, deliberately chosen to span the
expected difficulty range. After the pilot, the full Phase A hand-mark set
of 30-50 questions is selected to:

- Cover the four ODMI dimensions in roughly their population proportions
  (Policy 22%, Portal 31%, Quality 20%, Impact 27%).
- Populate all four answerability tiers (aim for at least 5 hand-marks per
  tier).
- Include questions of known historical contention (where the 2024 cycle had
  unresolved answers across countries) and questions of known triviality
  (where every country answered the same).

For Phase B, the same questions are re-marked for the other five countries
(Germany, Netherlands, Romania, Hungary, Estonia), with EA expected to vary
and AD expected to remain constant. This gives a saturated 30-50 × 6
sub-design for the wealth × maturity matrix.

---

## 5. Agent swarm architecture (Phase 2, to be built)

Three agents on LangGraph (per D3):

- **Coordinator.** Dispatches (question, country) pairs. Manages retries (max
  3). Logs all parameters and outputs. Escalates CAPTCHA and access blocks to
  a human queue without halting parallel pairs.
- **Researcher.** Tavily web search, Playwright browser automation, and a
  source validator (domain authority check). Reads major EU languages
  natively. Falls back to DeepL for low-resource languages per the language
  confidence table. Returns answer, evidence quote, source URL, and a
  retrieval confidence score.
- **Adversarial Verifier.** Independent search. Prompted to disprove the
  Researcher's answer, not confirm it. Visits the cited URL, searches for
  counter-evidence, and returns pass/fail plus an answer confidence score.

Output per (question, country) pair:

- Yes / No / Other.
- Retrieval confidence (0-1): did the agent actually retrieve real page
  content?
- Answer confidence (0-1): does the evidence support the claim?
- Source URL.
- Vetted evidence quote.

Termination rule: max 3 Coordinator-mediated retries per pair. Anything
unresolved is flagged for human review.

---

## 6. Evaluation methodology

### Ground truth (per D13, D22)

The 2025 ODMI cycle's `merged_responses` sheet ships every country's
answer to every question with ODMI's accepted decision and explanation:
5,148 (question, country) rows across 36 countries × 143 questions.
This is the primary evaluation set. Loaded into the SQLite `ground_truth`
table by `scripts/load_ground_truth.py`.

The 2024 cycle is held back as an independent external-validity set
(extracted from the 2024 PDFs only after the pipeline is finalised
on 2025). Prompt and retrieval tuning never touch 2024 evidence.

### Stage 1: retrospective benchmark (2025)

Run the swarm on (question, country) pairs from the 2025 ODMI cycle for
the Phase B six-country set. Compare each swarm `final_answer` against
the `response` column on the corresponding `ground_truth` row. The match
SQL lives in `dashboard/lib/db.py:_MATCH_STATUS_SQL` and classifies each
pair as `match`, `differ`, `no_ground_truth`, or `no_swarm_answer`.
"Yes"-family multi-tier responses (`yes`, `yes, 3-5`, `yes, >9`, etc.)
all match a swarm `yes`.

Compute, separately:

- **Accuracy** stratified by ODMI dimension (Policy / Portal / Quality /
  Impact), indicator, country, and (Phase B) language. Single fraction
  per stratum: matches / (matches + differs).
- **Cost** stratified by the same axes: input tokens, output tokens,
  wall-clock latency. Mean and 95th-percentile per stratum.
- **Cost-per-correct-answer** as a joint metric.
- **Failure mode taxonomy** by post-hoc clustering of the differ-pairs:
  wrong source, outdated evidence (ODMI may be a cycle behind reality),
  hallucinated source, irretrievable source, ambiguous question,
  language-comprehension failure.

### Data-leakage mitigation

ODMI publishes the `merged_responses` answers on data.europa.eu, so a
Researcher's Tavily search could in principle surface ODMI's own answer
page mid-run. The mitigation is a deny-list on the evaluation-cycle's
data.europa.eu sub-domain enforced inside `agents/tools/search.py`, and
any swarm pair whose chosen source URL points there gets flagged for
manual review and excluded from accuracy aggregates. The flag column
on `phase2_final` is the tracking surface for this.

### Stage 2: external-validity test (2024)

Run the unchanged pipeline against the 2024 ODMI ground truth. No further
tuning. The expected accuracy delta between 2025 and 2024 is itself a
result; a small delta suggests the pipeline generalises, a large delta
suggests it overfits to the 2025 evidence patterns.

### Stage 3: live deployment (2026 cycle)

Run the pipeline on 2026 indicators. No ground truth exists. Answers go to
human review and acceptance rate is the headline metric. Qualitative
discussion focuses on which question types resisted automation and how
those questions might be reformulated.

### Efficiency measurement (per D12)

Every LLM call (classifier post-hoc experiment, Researcher, Verifier,
any optimisation variant) writes to the database with the columns added
in Q6 / SPEC.md:

- `input_tokens`, `output_tokens`: from the API usage block.
- `wall_clock_ms`: time from prompt dispatch to parsed structured output.
- `estimated_cost_usd`: nullable. Computed off the published Anthropic
  pricing for the model variant in use, or marked as zero under the
  CLIProxyAPI / Claude Max routing per D1 (with a footnote noting the
  arithmetic equivalent if the calls had been billed direct).

Reporting groups answers by (ODMI dimension × country × condition) and
reports both accuracy and cost. The cost surface across this space is
the primary RQ5 output.

### Optimisation experiments

Two families of experimental conditions. Each variant writes into the
same schema with a `condition_label` column.

**Family 1: cost-side optimisations.** Aimed at the cost axis of the
accuracy-cost surface.

| Condition | Description |
|---|---|
| `baseline` | Full prompt, full retrieval, no truncation. The reference accuracy and cost. |
| `prompt-compressed` | Same agent loop, prompts compressed (no examples, terser instructions). |
| `retrieval-tight` | Tavily search limited to top-3 hits; Playwright fetch capped at first 4k chars. |
| `cache-hot` | Identical query within an hour returns the cached evidence rather than re-fetching. |
| `model-fallback` | Cheaper model (e.g. Haiku) tried first; escalates to Sonnet only on Verifier reject. |

**Family 2: Verifier prompt strategies.** Aimed at the accuracy axis
through different framings of the Verifier's adversarial role. Four
strategies (full prompts in `docs/AGENT_DESIGN.md` Section 4.10):

| Condition | Description |
|---|---|
| `verifier-disprove` | Default. Verifier is told the Researcher's claim and asked to find disproof. |
| `verifier-negation` | Verifier is asked to answer the logical negation of the question. Affirmative for the negation rejects the Researcher. |
| `verifier-steelman` | Two-step: articulate the strongest case for the Researcher, then attack even the strongest. |
| `verifier-blind` | Verifier never sees the Researcher's answer label, only the source and quote. Forms its own answer, Python compares. |

For each strategy we report: hallucination catch rate (Verifier rejects
a Researcher answer that also differs from ODMI ground truth), false
rejection rate (Verifier rejects a Researcher answer that matches ODMI
ground truth), and tokens per Verifier run.

**Family 3: model variants.** Aimed at the joint accuracy-cost
surface through model selection. Anthropic's catalogue spans roughly
15x in price between Haiku and Opus; the same accuracy at a fraction
of the cost (or noticeably higher accuracy at the same cost) is
worth reporting either way.

| Condition | Researcher | Verifier | Adjudicator | Approx ratio vs `model-sonnet` |
|---|---|---|---|---|
| `model-haiku` | Haiku-4.5 | Haiku-4.5 | Haiku-4.5 | 0.3x |
| `model-sonnet` (baseline) | Sonnet-4.6 | Sonnet-4.6 | Sonnet-4.6 | 1.0x |
| `model-opus` | Opus-4.6 | Opus-4.6 | Opus-4.6 | 5.0x |
| `model-tiered` | Haiku-4.5 | Sonnet-4.6 | Opus-4.6 | ~0.7x (Adjudicator fires rarely) |

The tiered combination is the practical-deployment hypothesis: cheap
drafting, mid-tier adversarial verification, premium reasoning only
when the swarm fails to converge. If the tiered combination matches
all-Sonnet accuracy at noticeably lower cost, that is itself an
interesting deployment recommendation.

The contributions:
- Family 1: the shape of the cost surface across prompt and retrieval
  optimisations.
- Family 2: empirical evidence about which adversarial framings
  actually catch errors in agentic AI for policy QA.
- Family 3: how much of accuracy is model capability versus pipeline
  design. For some question regimes, the answer is "doesn't matter
  much" and Haiku is fine; for others, only Opus reaches
  human-equivalent.

All three feed the dissertation. The combined surface is the
headline figure: accuracy (matches / matches + differs vs ODMI) on
one axis, cumulative cost on the other, one marker per condition,
coloured by ODMI dimension.

### Contribution

The failure mode taxonomy and the accuracy-vs-cost surface are the two
principal research outputs. The pipeline is the vehicle for producing
them.

---

## 7. Confounds and mitigations

| Confound | Mitigation |
|---|---|
| Ground-truth contamination (Researcher could find ODMI's published answer mid-run). | Deny-list on the evaluation cycle's data.europa.eu sub-domain enforced inside `agents/tools/search.py`. Any pair whose source URL was from a denied domain is flagged on `phase2_final` and excluded from accuracy aggregates. |
| Ground-truth staleness (ODMI assessments are one cycle old; reality may have moved on). | Each swarm-vs-ODMI disagreement is reviewed by hand before being counted as a swarm error. Pairs where reality has moved are recorded as `evidence_disagreement_explained` rather than as failures. |
| Hallucination by the Researcher agent. | Adversarial Verifier with independent retrieval. Dual confidence scoring. Substring check on the Researcher's cited URL. |
| Prompt drift across iterations. | Prompt versioning (D5). Every score links to the exact prompt version that produced it. |
| Language quality variance. | Static language confidence table populated by an early pilot. Native / DeepL / human routing per language. |
| Cycle ambiguity (2024 vs 2025 vs 2026). | 2025 ground truth primary (per D13/D22); 2024 held back as external-validity test; 2026 is the live deployment. |
| Cost gaming via prompt or retrieval tuning. | Optimisation variants are reported separately with explicit `condition_label`. The accuracy-cost surface is the output, not "the optimised pipeline." Baseline is always reported alongside any optimised variant. |

---

## 8. Software stack and reproducibility

- Python 3.11+, `uv` for dependency management. Lockfile committed.
- LangGraph for orchestration. langchain-anthropic for the LLM interface.
- LLM via CLIProxyAPI on `localhost:8317` (D1). Model version captured in
  every row.
- SQLite (D2) as the single store. Schema in `scripts/setup_sqlite.py`.
- Tavily for search. Playwright for browser automation. DeepL for fallback
  translation.
- Tests under `pytest`. CI not currently set up.

Every run records: timestamp, git commit SHA, model version, prompt version,
inputs, raw outputs. An examiner with the repo and the SQLite file replays
the evaluation deterministically up to LLM stochasticity (which itself is
captured in the raw response column).
