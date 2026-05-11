# Methodology

Locked methodological choices for the ODMI Agent Swarm dissertation. This is
the document an examiner reads to understand what was done and why. Changes
to anything here require a new numbered decision in `docs/SPEC.md`.

Last reviewed: 2026-05-11.

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

**RQ2.** How does answer quality vary along three a priori axes of question
difficulty — Evidence Accessibility, Answer Determinism, and Source
Complexity?

**RQ3.** How does answer quality vary across language and portal-maturity
regimes when the same system is run on a stratified six-country sample?

**RQ4.** What categories of ODMI question are systematically beyond the reach
of agentic LLMs as currently constituted, and what reformulations would bring
them in scope?

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

### Stage 1: retrospective benchmark

Run the finalised swarm on the (question, country) pairs from the most
recent ODMI cycle with full ground-truth answers (2024 or 2025, to be
finalised). Compute:

- Accuracy stratified by rubric tier.
- Accuracy stratified by ODMI dimension (Policy / Portal / Quality / Impact).
- Accuracy stratified by country and by language.
- Categorical failure mode analysis: wrong source, outdated evidence,
  hallucinated source, irretrievable source, ambiguous question.

### Stage 2: live deployment (2026 cycle)

Run the validated pipeline on the 2026 ODMI indicators. No ground truth
exists. Answers go to human review. Acceptance rate is the headline metric.
The qualitative discussion focuses on which question types resisted
automation and how those questions might be reformulated.

### Contribution

The failure mode taxonomy is the principal research output. The pipeline is
the vehicle for producing it.

---

## 7. Confounds and mitigations

| Confound | Mitigation |
|---|---|
| Evaluator bias (same researcher hand-marks and analyses). | Hand-marks locked to git before swarm runs (D9). Commit SHA stored alongside each mark. |
| Hallucination by the Researcher agent. | Adversarial Verifier with independent retrieval. Dual confidence scoring. |
| Prompt drift across iterations. | Prompt versioning (D5). Every score links to the exact prompt version that produced it. |
| Selection bias in hand-mark sample. | Stratification design (D10). Sample composition locked before marking begins. |
| Language quality variance. | Static language confidence table populated by an early pilot. Native / DeepL / human routing per language. |
| Cycle ambiguity (2024 vs 2025 vs 2026). | Decide and document before Stage 1 begins (Q5 in SPEC.md). |

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
