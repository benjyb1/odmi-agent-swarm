# Preliminary Project Report

**Title:** AI Frameworks for Assessment of Data and Digital Technologies: An
Agent Swarm for the EU Open Data Maturity Index

**Author:** Benjamin Bream

**Programme:** MSc Advanced Computing, King's College London

**Supervisor:** TBC

**Submission date:** 2026-05-22

**Self-imposed cut-off:** 2026-05-16

---

## Format compliance (KEATS brief)

- 10 pages A4 body, cover and references outside the count.
- 11pt minimum font size.
- Single line spacing minimum.
- 1.5cm minimum margins on all sides.

Body budget (rough):

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

(TODO. Establish ODMI in two paragraphs. What it is, who runs it (Capgemini for
the European Commission), what it measures, how it is currently collected
(manually), and why this matters: the index informs policy benchmarking and
funding allocation across 36 countries. Note constraints of the manual
process — labour, inconsistency, slow refresh cycles, weaker coverage for
smaller countries.)

### 1.2 Problem statement

(TODO. The current methodology is a bottleneck. Frame the research opportunity:
recent agentic LLMs combined with retrieval can in principle automate the
evidence-gathering and answering steps. The open question is which questions
they can answer reliably and which they cannot.)

### 1.3 Aims and research questions

The project pursues four research questions:

- **RQ1.** Can a multi-agent LLM system, with adversarial verification, answer
  ODMI questionnaire items at a quality level that approximates the existing
  human process for a controlled baseline country?
- **RQ2.** How does answer quality vary along three a priori axes of question
  difficulty — Evidence Accessibility, Answer Determinism, and Source
  Complexity?
- **RQ3.** How does answer quality vary across language and portal-maturity
  regimes when the same system is run on a stratified six-country sample?
- **RQ4.** What categories of ODMI question are systematically beyond the reach
  of agentic LLMs as currently constituted, and what reformulations would bring
  them in scope?

### 1.4 Objectives

(TODO. Concrete deliverables:
1. An end-to-end agent pipeline (Coordinator, Researcher, Adversarial Verifier)
   running on LangGraph against a baseline country.
2. A locked, hand-marked dataset of 30-50 questions stratified by the three
   rubric dimensions for use as analytical strata.
3. A retrospective benchmark of the pipeline against the most recent ODMI
   cycle with full ground truth.
4. A stratified six-country evaluation (the Phase B 2×3 matrix).
5. A failure-mode taxonomy with proposed question reformulations for the
   "Very Unlikely" tier.)

### 1.5 Dataset

(TODO. The 2025 ODMI questionnaire (143 questions, 4 dimensions, 17
indicators) sourced from data.europa.eu. France's 2024 official response
sheet (with the EU-collected 2024 answers and the 2025 confirmation column)
already in the repo. The full 36-country response set will be sourced from
the 2024 published cycle for the retrospective benchmark.)

### 1.6 Methodology in brief

(TODO, half a page. Two operational pieces: a hand-marked rubric for
analytical stratification, and an agent swarm for answering. Per D8 in
SPEC.md, the rubric is not a runtime classifier. Per D9, hand-marks are
locked to git before any related swarm run. Full methodology in
`docs/METHODOLOGY.md`.)

---

## 2. Background

### 2.1 Open data maturity assessment

(TODO. The ODMI's place in the European open data policy stack. Reference the
2024 ODMI report, the data.europa.eu portal, the Open Data Directive
(2019/1024) and the implementing regulation (EU) 2023/138 on high-value
datasets. Briefly note other digital index methodologies (UN E-Government
Survey, OECD Going Digital, World Bank Statistical Performance Indicators)
to establish the wider context.)

### 2.2 Agentic LLM systems

(TODO. Define agentic LLM systems and where they sit on the spectrum between
zero-shot chat and full autonomous agents. Cover the now-standard
architectures: tool-augmented chains, multi-agent systems with role
specialisation, retrieval-augmented generation, and adversarial / red-team
verification patterns. Key references: ReAct, AutoGen, LangGraph design
notes, recent multi-agent papers from 2024-2025.)

### 2.3 LLM evaluation on real-world tasks

(TODO. Benchmarks that approximate this problem: GAIA, ToolBench, AgentBench,
WebArena, MMLU-Pro. The literature gap: these test general competence on
synthetic tasks. ODMI is a real-world, multilingual, policy-evaluation task
with ground truth — a different evaluation regime.)

### 2.4 Hallucination, faithfulness, and adversarial verification

(TODO. The faithfulness problem in retrieval-augmented systems. Survey
mitigations: source citation, dual-confidence scoring, adversarial verifiers,
chain-of-verification. The argument for an Adversarial Verifier prompted to
disprove rather than confirm.)

### 2.5 Multilingual evidence and policy text

(TODO. LLM performance on low-resource European languages (Maltese, Estonian,
Latvian, Lithuanian, Slovenian). Document-level translation versus native
multilingual reading. The case for an adaptive translation layer.)

### 2.6 Automated policy and benchmark analysis

(TODO. Closer related work: AI for civic and policy analysis (CivicBench,
recent work on automated regulatory analysis), AI for academic benchmark
production (LiveBench), and any prior attempts at automating
index-style benchmarks. The novelty of this project: applying multi-agent
verified retrieval to a policy index that is currently manually collected.)

### 2.7 Gap statement

(TODO, half a page. Synthesise: (i) ODMI is a substantively important index
with a manual bottleneck; (ii) agentic LLM systems are now capable of the
component tasks (web search, document reading, structured output, native
multilingual reading for most EU languages); (iii) no prior work has applied
verified multi-agent retrieval to a real policy index of this scale with
empirical evaluation against ground truth; (iv) the failure-mode taxonomy
that emerges is itself a contribution to the agentic-AI evaluation
literature.)

---

## 3. Project schedule

### 3.1 Phasing

(TODO. Summarise the four phases:
- Phase 0 (now to mid-May): foundation. Repo housekeeping, locked methodology,
  preliminary report.
- Phase A (mid-May to mid-June): France baseline. Hand-mark 30-50 questions,
  build the minimal LangGraph swarm, run against France, analyse.
- Phase B (mid-June to mid-July): six-country stratification. Re-mark the
  same questions for five more countries, extend the swarm, run, analyse.
- Phase C (mid-July to early August): write-up. Final dissertation drafting,
  retrospective benchmark, failure-mode taxonomy, viva preparation.)

### 3.2 Milestones

| Milestone | Target date |
|---|---|
| Preliminary report submitted | 2026-05-22 |
| Phase A pilot hand-marks (10 questions) locked | 2026-05-25 |
| Phase A full hand-marks (30-50 questions) locked | 2026-06-08 |
| Minimal LangGraph swarm: one (question, country) end-to-end | 2026-06-08 |
| Phase A full run against France complete | 2026-06-22 |
| Phase B hand-marks locked for all six countries | 2026-07-06 |
| Phase B full run complete | 2026-07-20 |
| Retrospective benchmark complete with metrics | 2026-07-27 |
| Final dissertation submitted | 2026-08-02 |

### 3.3 Gantt chart

(TODO. Figure 1. Eleven-week Gantt covering the milestones above, with parallel
tracks for hand-marking, code, and write-up. Export from a tool that produces
SVG (Mermaid Gantt, or hand-drawn in draw.io / Excalidraw exported to SVG).
Place under `docs/figures/gantt.svg`.)

### 3.4 Risks and contingencies

(TODO, half a page table. Top risks:
- Swarm fails to terminate on some questions: bounded retries (D-coordinator
  termination).
- CAPTCHA / scraping blocks on government portals: human-in-the-loop pause
  and notify.
- Low-resource language failure: DeepL fallback, human-only routing on the
  language confidence table.
- Time slip on hand-marking: pilot first, lock the sample design only after
  the pilot reveals the time per question.
- Single-supervisor unavailability: log meetings to Notion, async feedback
  acceptable.)

---

## References

(Citations are managed in `docs/references.bib`. Build the references list
in the final PDF from that file. Suggested seed entries are already there.)

---

## Drafting notes (not part of the submitted report)

**Writing approach.** Draft in flat prose paragraphs in this file, then style
to KEATS format only at the end. Do not lay out for two-column or fancy
typography. Just hit the page count.

**Voice.** Plain academic register. UK English. No em dashes. No AI tells.
Active voice. Concrete claims. Run paragraphs through the humaniser skill
before treating any as final.

**Citation density.** Background section needs roughly 20-30 references for
a 10-page prelim. Aim for one citation per substantive claim. Use BibTeX in
`docs/references.bib`.

**Use of figures.** Two figures should suffice: a system architecture
diagram in the Introduction (or Methodology), and the Gantt in Schedule.
SVG sources stored under `docs/figures/`.

**Section length discipline.** If you write past the budget for a section,
cut before continuing. Margins, font, and spacing are minimums in the brief;
do not abuse them to fit content that is overlong.
