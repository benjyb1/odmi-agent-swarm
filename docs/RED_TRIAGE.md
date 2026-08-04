# Red block triage

Every coloured region in the master, grouped into blocks. Extracted
2026-08-04 for the LaTeX migration (phase 2).

C00000 is Claude, FF0000 and EE0000 are Benjy. Most of the volume is
appendix tables that were drafted in colour and never recoloured, so
the unit of decision is the block, not the passage.

One bucket per row before any conversion runs:

- **adopt** content that belongs in the dissertation. Where the words
  are Claude's, rewrite them as your own first. Then it goes black.
- **action** an instruction to yourself. Do it, then delete.
- **delete** stale or superseded.

A blanket red-to-black would promote every instruction into submitted
prose. A blanket delete would remove most of the appendices.

Blocks: 89. Coloured words: 13700.

| # | owner | chapter | section | in table | words | opening text | bucket |
|---|---|---|---|---|---|---|---|
| 1 | Claude | Appendix | G. The Full Question Bank | yes | 5887 | Question | |
| 2 | Benjy | Appendix | E. Prior Work Scored Against the S | yes | 1117 | Work | |
| 3 | Claude | Appendix | H. The Catalogue Recompute in Full | yes | 626 | Country | |
| 4 | Claude | Appendix | J. Figures Not Used in the Body | no | 534 | J. Figures Not Used in the Body | |
| 5 | Claude |  |  | no | 478 | Abstract | |
| 6 | Benjy | References |  | no | 402 | Anthropic (2024) The Claude 3 Model Family: Opus, Sonnet, Haiku. Model card. Ant | |
| 7 | Benjy | Discussion | Reformulating the ODMI | yes | 361 | Question group | |
| 8 | Claude | Appendix | B. Pipeline Detail: Abstention Rea | no | 357 | Three parts of the pipeline are set out in full here, each of which the body sta | |
| 9 | Claude | Results | Ablation | no | 288 | That gap closes once both are made to answer everything. Scoring every binary qu | |
| 10 | Claude | Appendix | I. Development-Set Results | no | 208 | I. Development-Set Results | |
| 11 | Benjy | Discussion | Reformulating the ODMI | no | 172 | Figure 5.5 makes plain | |
| 12 | Benjy | Discussion | Threats to Validity | no | 159 | Appendix A holds the full register of thirty-four modes by which the swarm can c | |
| 13 | Benjy | Approach and Methodology | Deterministic Tool for Catalogue Q | yes | 158 | Source | |
| 14 | Claude | Appendix | H. The Catalogue Recompute in Full | no | 156 | H. The Catalogue Recompute in Full | |
| 15 | Benjy | Appendix | C. Experiments | yes | 136 | Clean null: pooled false-positive McNemar p = 0.727, paired accuracy an exact ti | |
| 16 | Claude | Appendix | G. The Full Question Bank | no | 120 | G. The Full Question Bank | |
| 17 | Claude | Appendix | A. Full Failure-Mode Register (FM- | no | 115 | The register lists every way the project has identified for a wrong answer to re | |
| 18 | Benjy | Appendix | J. Figures Not Used in the Body | no | 115 | Recomputed from data/odmi.db over the three replicates, the 148 shared pairs spl | |
| 19 | Benjy | Approach and Methodology | Deterministic Tool for Catalogue Q | no | 107 | in Table 3.2 | |
| 20 | Claude | Appendix |  | no | 107 | This appendix carries the material the body points at but has no room for, and a | |
| 21 | Benjy | Discussion | Debate in an ODMI Environment | no | 106 | RQ2 asked what a swarm of distinct roles | |
| 22 | Benjy | Background and Related Wor | Methods towards Verification | no | 104 | Figure 2.3 traces the lineage between the past works, where no single work arriv | |
| 23 | Claude | Appendix | B. Pipeline Detail: Abstention Rea | yes | 104 | 202 of 208 | |
| 24 | Benjy | Appendix | F. Baselines | yes | 96 | Always-yes, all 36 countries | |
| 25 | Claude | Appendix | C. Experiments | no | 91 | Every experiment was registered before dispatch, in a design note fixing the que | |
| 26 | Benjy | Introduction | Domain | no | 90 | Countries tend to improve year on year, with average maturity rising from 46% in | |
| 27 | Benjy | Appendix | E. Prior Work Scored Against the S | no | 85 | E. Prior Work Scored Against the Six Criteria, with Justifications | |
| 28 | Benjy | Background and Related Wor | The ODMI as an Assessment | no | 84 | The four dimensions of the ODMI aim to measure | |
| 29 | Benjy | Appendix | C. Experiments | no | 73 | C. Experiments | |
| 30 | Benjy | Appendix | D. Out-of-Reach Questions | no | 73 | The 29 questions judged systematically out of reach of a web agent. The rule is  | |
| 31 | Benjy | Appendix | H. The Catalogue Recompute in Full | no | 72 | One snapshot per country, the most recent, read from catalogue_snapshots and cat | |
| 32 | Benjy | Appendix | B. Pipeline Detail: Abstention Rea | no | 65 | B. Pipeline Detail: Abstention Reasons, Evidence Gates and the False-Positive Au | |
| 33 | Claude | Appendix | I. Development-Set Results | yes | 62 | Country | |
| 34 | Benjy | Results | Operational Cost and Runtime | no | 56 | Table 4.8.1: What the assessment cost. | |
| 35 | Benjy | Results | Ablation | yes | 55 | Closed book (no retrieval) | |
| 36 | Benjy | Appendix | I. Development-Set Results | no | 50 | Computed from the wide_only arm of exp34_retrieval_strategy_s46 in data/odmi.db, | |
| 37 | Benjy | Results | Convergent Validity | no | 47 | Figure 4.1.1: Outcome makeup per country. | |
| 38 | Benjy | Results | Attributability | yes | 45 | The passage exists in the cited source | |
| 39 | Benjy | Background and Related Wor | Multi-Agent Debate for Verificatio | no | 44 | The claim under test is therefore narrower than “debate is unanimously better”.  | |
| 40 | Benjy | Results | Selectivity | no | 44 | [CC: this point does not reproduce. At 0.88 the yes class holds 82 committed ans | |
| 41 | Benjy | Discussion | The Scorecard | no | 44 | Figure 5.1 | |
| 42 | Claude | Background and Related Wor | Criteria for an Automated System | yes | 41 | Running end to end over the open web, Fumega and Gao (2026) report mismatch agai | |
| 43 | Benjy | Approach and Methodology | Ground Truth and Its Limits | no | 41 | Table 3.1 | |
| 44 | Benjy | Introduction | Research Questions | no | 39 | RQ1: Can an automated assessment meet the conditions that keep it legitimate? | |
| 45 | Benjy | Results | Operational Cost and Runtime | yes | 37 | Every pair attempted | |
| 46 | Benjy | Approach and Methodology | Evaluation Set | no | 32 | Figure 3.3: The evaluation eight by language resource class and negative-gold sh | |
| 47 | Benjy | Background and Related Wor | Limitations of LLMs in Truth-Seeki | no | 29 | Figure 2.1: Why the objective produces hallucination. | |
| 48 | Claude | Background and Related Wor | Methods towards Verification | no | 25 | ties back to the long-tail argument in §2.3 | |
| 49 | Claude | Approach and Methodology | Experiments | no | 25 | The analysis that produces the figures reported in §4 is itself under test, as a | |
| 50 | Benjy | Results | Reconstructing the Index | no | 23 | Figure 4.9.1: Reconstructed maturity band against the published score. | |
| 51 | Benjy | Appendix | B. Pipeline Detail: Abstention Rea | yes | 21 | 208 | |
| 52 | Claude | Appendix | F. Baselines | no | 19 | F. Baselines | |
| 53 | Claude | Background and Related Wor | Multi-Agent Debate for Verificatio | no | 18 | are among the first to shift away from | |
| 54 | Claude | Results | Generalisability | no | 18 | §2.3 set out why an agent constrained to reason from retrieved evidence would fa | |
| 55 | Claude | Background and Related Wor | Allowing for Abstention | no | 17 | §2.5 left the system with three outcomes | |
| 56 | Benjy | Introduction | The Open-World Problem | no | 16 | Figure 1.1: The assumption the questionnaire runs on. | |
| 57 | Benjy | Background and Related Wor | Criteria for an Automated System | no | 15 | Their framework was drafted for | |
| 58 | Benjy | Approach and Methodology | Data-Leakage Controls | no | 15 | Data-Leakage Controls | |
| 59 | Claude | Appendix | D. Out-of-Reach Questions | no | 13 | Table D.1: The 29 questions judged out of reach of a web agent. | |
| 60 | Claude | Background and Related Wor | Limitations of LLMs in Truth-Seeki | no | 12 | self-verification in §2.4, adversarial multi-agent debate in §2.5 and abstention | |
| 61 | Claude | Results | Attributability | no | 12 | one of the central risks of a generative assessor identified in §2.3 | |
| 62 | Benjy | Results | Attributability | no | 12 | Table 4.3.1: What each attributability condition caught, over the 1,144 evaluati | |
| 63 | Claude | Discussion | Debate in an ODMI Environment | no | 12 | §2.5 had already qualified this, noting that decorrelation is only partial | |
| 64 | Claude | Approach and Methodology | Evaluation Set | no | 10 | §4.7 | |
| 65 | Claude | Discussion | The Scorecard | no | 10 | this is the optimism bias §2.3 anticipated | |
| 66 | Claude | Results | Subgroup Equity | no | 9 | §2.7 set out three explanations for a poor score | |
| 67 | Benjy | Approach and Methodology | Retrieval | no | 8 | an LLM call generates three likely search queries | |
| 68 | Benjy | Results | Generalisability | no | 8 | Figure 4.5.2: Coverage and accuracy by answer shape. | |
| 69 | Benjy | Appendix | A. Full Failure-Mode Register (FM- | no | 8 | and form the attack list for future work | |
| 70 | Claude | Results | Convergent Validity | no | 7 | , split by country in Figure 4.1.1 | |
| 71 | Claude | Background and Related Wor | Criteria for an Automated System | no | 6 | , set out in Table 2.1, | |
| 72 | Benjy | Background and Related Wor | Research Gap | no | 6 | Table 2.2 | |
| 73 | Claude | Approach and Methodology | Metrics | no | 6 | , set out in Table 3.3, | |
| 74 | Claude | Appendix | E. Prior Work Scored Against the S | no | 5 | , Table E.1, | |
| 75 | Claude | Background and Related Wor | The ODMI as an Assessment | no | 4 | (Davis et al., 2012) | |
| 76 | Claude | Approach and Methodology | System Architecture | no | 4 | .6 | |
| 77 | Claude | Results | Reconstructing the Index | no | 4 | §4.2 | |
| 78 | Claude | Discussion | Reformulating the ODMI | no | 4 | in Table 5.2 | |
| 79 | Claude | Results | Operational Cost and Runtime | no | 3 | §4.2 | |
| 80 | Benjy | Background and Related Wor | Criteria for an Automated System | yes | 2 | §3.4 | |
| 81 | Claude | Background and Related Wor | Research Gap | no | 2 | §5.3 | |
| 82 | Claude | Discussion | Threats to Validity | no | 2 | §4.4 | |
| 83 | Claude | Introduction | Approach | no | 1 | §4.7 | |
| 84 | Benjy | Background and Related Wor | Allowing for Abstention | no | 1 | §3.9 | |
| 85 | Claude | Background and Related Wor | Multilingual Evidence Retrieval | no | 1 | §4.4 | |
| 86 | Benjy | Approach and Methodology | System Architecture | no | 1 | §3.5 | |
| 87 | Benjy | Approach and Methodology | The Agent Loop | no | 1 | §3.6 | |
| 88 | Claude | Approach and Methodology | Ground Truth and Its Limits | no | 1 | §4.1 | |
| 89 | Claude | Results | Selectivity | no | 1 | 94.3% | |
