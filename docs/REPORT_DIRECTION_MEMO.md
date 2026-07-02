# Report direction memo: engineering and adversarial-verification reframe

2026-07-01 overnight session. Raw material, not prose. Every number below is
verifiable in the repo or DB; sources in brackets. Write it in your own words.

## The core diagnosis

- The current report reads as "a system to automate the ODMI, evaluated on the
  ODMI". An Advanced Computing examiner marks the engineering and the
  empirical method, not the policy domain.
- Your own comment block (p.10, "Comments") already says it: the interesting
  findings sit with the adversarial verifier, with-and-without ablations,
  tweaks and trade-offs, failure modes, explicit added value.
- The strongest reframe: the ODMI is the *testbed*; the contribution is (1) an
  adversarial verification architecture for open-web research agents, (2) an
  evaluation harness that measures it honestly, (3) a failure-mode and
  abstention characterisation of where such systems break.
- The report already contains most of the raw evidence for this framing. It is
  a re-weighting job, not a rewrite: shrink ODMI exposition, expand
  verification design space, experiments, and the evaluation harness.

## What is missing that the repo already has (biggest wins, cheapest)

- **The experiment harness as a contribution.** The report never mentions the
  orchestrator (D48): pre-registration enforced by construction (unregistered
  experiment_id is a hard preflight error), one-variable-per-arm check, D47
  held-out freeze as a hard block, budget ceilings, idempotent resume,
  arm-level health checks (`scripts/run_experiments.py`, R1-R12 in
  `docs/EXPERIMENTS_PROTOCOL.md`). This is AI-evals methodology an examiner
  will reward. Frame: LLM experiments are cheap to contaminate (shared caches,
  drifting knobs, held-out leakage); the harness makes the contamination
  paths structurally impossible rather than remembered.
- **The null results as a narrative.** EXP-11 (verifier redesign, J 0.41 vs
  0.03), EXP-13a (verdict wiring, all >= 95% fidelity, none better), EXP-16
  (free adjudicator selection, 0.57 vs 0.58), EXP-25/27 (entailment and
  margin commit gates, null and harmful: entailment gate pushed negative-gold
  FP rate 0.76 -> 1.00). Pattern: reasoning-side interventions do not move
  precision; the binding controls are the 0.65 floor and retrieval quality.
  This is a finding about where the leverage is in agentic pipelines, and it
  is publishable-grade honesty (`docs/EXPERIMENTS.md`).
- **The receipts infrastructure.** Every LLM call writes model, prompt
  version, tokens, latency, cost (`claude_usage_log`); every prompt is
  versioned (`prompt_versions`); every evaluation replays from the SQLite
  file alone. One line in the report ("every LLM call records...") undersells
  a reproducibility property most agent papers lack.
- **Five-layer leakage defence detail.** The report describes the layers but
  not the adversarial framing: each layer fails differently, and per-layer
  catch rates are reportable (`agents/tools/blocked_domains.py`, D24; 8
  deny-listed / MQA abstentions already logged, code C in your abstention
  table).

## New evidence generated tonight (2026-07-01/02, cite the repo state)

- **EXP-28 architecture ablation ladder, live, Sonnet 5, pre-registered
  before dispatch** (`docs/EXPERIMENTS_ARCH_ABLATION.md`, experiments table
  rows `exp28_arch_ablation`, `exp29_sonnet5_model`):
  - Arms: full trio (control) / no_adjudicator (the owed EXP-15 design) /
    researcher_only (no verification layer). One knob (`pipeline_mode`),
    everything else pinned.
  - Sample: the three canonical dev pair sets, 156 pairs per arm (MT 60 +
    NL 52 + AL 44), 78 negative golds per arm, balanced by construction.
  - Ladder logic: trio vs no_adjudicator isolates the Adjudicator;
    no_adjudicator vs researcher_only isolates the Verifier; trio vs
    researcher_only is the whole layer, the live counterpart of EXP-13a's
    replay estimate (which found removing the layer costs 27 correct, saves
    16 wrong, net -11).
  - Results land in `phase2_final` under experiment_id `exp28_arch_ablation`;
    analysis morning of 2026-07-02.
- **EXP-29 model contrast**: identical trio + pairs on claude-sonnet-4-6 vs
  claude-sonnet-5 (whole stack pinned per arm). First Sonnet 5 data in the
  project; adoption rule pre-registered (non-inferior balanced accuracy,
  FP rise <= 2 points).
- **Engineering: `pipeline_mode` knob** in the coordinator, dispatcher, and
  orchestrator flag_map, with schema migration for three new terminal
  statuses and 8 new unit tests (commit 04ef8ee).
- **Engineering: Claude 5 transport compatibility** (commit d2b61de). Three
  live-discovered faults: Sonnet 5 rejects the temperature param; responses
  can lead with a thinking block; and CLIProxyAPI 7.2.45 replaces the API
  system param with the Claude Code system prompt, silently discarding agent
  instructions. Fix: instructions travel in the user turn. Worth a paragraph
  in the report as an infrastructure-fragility case study: the entire swarm's
  instruction channel broke on a proxy restart, and only structured-output
  validation caught it. Connects to FM-level thinking about silent
  dependencies.

## Restructure suggestion (section-level moves, your call)

- Intro: lead with the verification problem (over-answering under
  uncertainty, agents in low-oversight settings), land the ODMI as testbed in
  paragraph 2, not paragraph 1. Your line 17 already gestures at this; commit
  to it.
- RQs: your instinct at the "I think this is wrong" note (Aims section) is
  right. Candidate set aligned to the evidence you actually have:
  - RQ1 what does adversarial verification buy (ablation: EXP-28 + EXP-13a).
  - RQ2 can the system answer-or-abstain honestly (selective prediction:
    floor sweep EXP-10, abstention taxonomy, risk-coverage).
  - RQ3 where does it fail structurally and why (FM-01..34 taxonomy,
    C1-C6 root causes).
  - RQ4 what does it cost (D12 cost-per-correct, model tiers EXP-9/29).
  - Keep the ODMI match-rate as the applied validation, not as RQ1.
- Background: split "Agentic LLM Systems" from a new "Verification and
  selective prediction" subsection (lit below). Shrink the two ODMI history
  paragraphs by half; the assessor-decision table (63/27/10) carries the
  needed weight on its own.
- Method: add "Evaluation harness" as a first-class subsection beside System
  Architecture (orchestrator, pre-registration, held-out freeze, leakage
  layers, receipts).
- Results-to-be: the ablation table (EXP-28) becomes the headline exhibit,
  ahead of country match rates.

## Facts for the empty "Multilingual Evidence Retrieval" section

- EXP-22 (AL, n=48 stratified): bilingual arm pulled Albanian-language
  evidence into 17% of attempts vs 1% English-only; candidate recall 46% vs
  48%; abstention +8 points. Manipulation worked, outcome unchanged
  (`docs/EXPERIMENTS_FOREIGN_LANG.md`).
- Verifier translation replay (n=127 stored rejections, DeepL): 1 verdict
  flipped toward gold, net 0.8%. Translation before judgment does not help.
- Conclusion you can defend: language is not the binding constraint;
  thin web presence is. Opposite of the project's prior.
- DeepL's 2025 expansion covers Albanian, Croatian, Maltese, Macedonian,
  Bosnian, Serbian, so a translation layer was available and still did not
  help. Rules out tooling as the gap.
- Literature pointers (verify citations before use):
  - Cross-lingual IR (CLIR) surveys; mMARCO (multilingual MS MARCO) for
    multilingual retrieval benchmarks.
  - Work on English-pivot vs native-language queries for low-resource web
    search; multilingual dense retrievers (mDPR, mContriever).
  - LLM multilingual capability gaps on low-resource European languages
    (Albanian, Maltese are standard examples).
  - Bilingual query generation already ships in production (the D43 DIY
    pipeline); frame the section as an ablation finding, not a feature
    proposal.

## Facts for the empty "Automated Policy and Document Analysis" section

- Fumega & Gao (Global Data Barometer): three commercial deep-research
  agents; 61.76% average match with expert answers; foundational questions
  85.55% vs advanced 31%; documented cases where the AI was right and the
  expert wrong. Already cited elsewhere in your draft; this is its proper
  home.
- Heseltine (and the AI Pluralism paper you reference): human-verified LLM
  coding of political/policy text; both keep a human in the loop, which is
  the gap your system attacks.
- Capgemini's own role in ODMI (confirm 63% / complement 27% / change 10%,
  5,148 rows, `ground_truth.decision`) is itself a verification workflow;
  your swarm mirrors the complement/change decisions computationally. That
  parallel is worth one bullet in the section.
- Candidate additions (verify before citing): LLMs for regulatory-compliance
  checking, automated e-government benchmarking, LLM-assisted survey/index
  construction. Keep short; this section supports, it does not carry.

## Verification / selective-prediction literature the draft lacks

- The draft's "Hallucination and Self-Verification" section has three empty
  citation brackets. Candidates that map cleanly onto the architecture
  (verify each before use):
  - Self-consistency (Wang et al.): sampling agreement as verification; your
    Verifier is the counter-position (external counter-evidence beats
    self-agreement); FM-21 (correlated error) is the empirical reason.
  - Chain-of-Verification (Dhuliawala et al.): model-internal verification
    questions; contrast with your external adversarial search.
  - SelfCheckGPT (Manakul et al.): sampling-based hallucination detection
    without external evidence; the "sandbox" limitation your line 106
    already gestures at.
  - FacTool / SAFE (search-augmented factuality evaluation): closest prior
    art to the Verifier's counter-search; differentiate on the adversarial
    framing (instructed to refute, not to score) and on the abstention
    pathway.
  - Selective prediction / answer-or-abstain QA (Kamath et al. 2020 and
    successors); calibration of LLM confidence. Your 0.65 floor result
    (gates more wrong answers than Verifier and Adjudicator combined,
    abstention table code G, 146/580) is a selective-prediction finding and
    should be framed in that vocabulary.
  - LLM-as-judge self-preference bias: motivates the cross-family Mistral
    judge (EXP-1 reliability: raw agreement 78%, Krippendorff alpha 0.648).
- Risk-coverage curve: EXP-10's floor sweep (0.65/0.55/0.50, pooled n=360,
  recovered-precision 0.76 at 0.50 vs the pre-registered 0.80 bar) is
  exactly the data for a precision-vs-coverage plot. One figure, standard in
  the selective-prediction literature, currently absent from the report.

## Angles an examiner will probe that the draft does not yet cover

- Why three agents and not one agent self-critiquing? Cheap-alternative
  baseline. EXP-28's researcher_only arm answers half of this; a self-verify
  single-agent arm is the remaining half (buildable: same knob, new value).
- Correlated failure: Researcher and Verifier share one model family, so
  agreement is not independence (FM-21, FM-23). Defences: adversarial
  framing, independent counter-search, cross-family judging (EXP-1). Say it
  before the examiner does.
- Ground-truth contamination: the model may have seen ODMI 2025 publications
  in pretraining. The deny-list stops retrieval leakage, not parametric
  leakage. Mitigations you can claim: evidence-grounding requirement (quote
  must appear in a fetched snippet, D34), and the 2026 cycle as a true forward
  test (answers not yet published). State the residual risk honestly.
- External validity: one index, one cycle. The 2024 held-back cycle (D13)
  and the WHO speech-writer reuse are your two generalisation cards.
- Concurrency/systems engineering: WAF handling (Playwright fallback on
  403/429/503), fetch-stall breakers, rate-limit shutdown semantics
  (`RateLimitedShutdown`, exit 42), idempotent resume. Currently invisible
  in the report; one subsection makes the systems contribution legible.

## Numbers in the draft I could not verify tonight (check before submission)

- "confirming their answer 63% ... 27% ... 10%": matches `ground_truth`
  decision counts (3,249 / 1,385 / 514 of 5,148). Verified.
- "124 of 143 questions require simple, binary answers": the answer-shape
  table says 124 binary. Verified against `questions` table shape counts.
- "68.7% of these 28 questions ... answered yes": not re-verified tonight;
  re-run before submission.
- The FP-by-decision table (n=507, FPs 55) is from the June swarm state;
  EXP-28 will supersede it with cleaner per-arm numbers. Flag which run each
  table reads from when you finalise.
- "BLABH BLAH" placeholder (Evaluation Design section) and "Capgemini only
  changes the answer of 11%": the decision table says 10% change; pick one
  figure and source it.

These are your raw materials. I can pull any number against the DB before you
use it, and the EXP-28/29 results will be analysed and appended by morning.
