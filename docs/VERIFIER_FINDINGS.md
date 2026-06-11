# Verifier programme: consolidated findings

Closing record for the verifier investigation run 2026-06-10/11 on branch
`claude/loving-saha-67bbe8`. This is the synthesis; the detailed
pre-registrations, designs, and per-experiment numbers live in the documents
cited under each section. Every result traces to a committed JSONL.

## 1. The question we started from

The brief: the adversarial Verifier (Researcher -> Verifier -> Adjudicator
swarm) was suspected of costing accuracy. The evidence was a Malta production
trail where the default `disprove` verifier barely separated correct from wrong
answers (P(pass | correct) 0.571 vs P(pass | wrong) 0.432, Fisher p = 0.23) and
appeared to sort by claim direction rather than truth. The task was to make the
verifier useful in earnest: a verdict that discriminates by correctness, a
symmetric burden across yes/no claims, honest absence handling, quote integrity,
a defined role for `verifier_confidence`, shape-aware verdicts, and a
measurement design. Full diagnosis and the ranked proposals:
`docs/VERIFIER_REDESIGN.md`.

## 2. What we tested

A staged programme, free offline phases before any paid run, each
pre-registered before its data.

| Experiment | Question | Design | Cost |
|---|---|---|---|
| EXP-11 stage 0 | quote integrity, absence policy, confidence role | offline replays | free |
| EXP-11 stage 1 | does a redesigned verdict discriminate better | 150-candidate frozen-evidence classifier ladder (disprove / tristate / tristate+probes, gated columns) | ~1,300 calls |
| EXP-12a | is the production-vs-clean gap an evidence effect | matched-pair replay, same researcher run judged twice | free |
| EXP-12b | does richer evidence raise discrimination | evidence ladder E5/E0/E1, prompt pinned | ~450 calls |
| EXP-12c | does a shape-conditional evidence recipe help | exact recombination of E5/E1 verdicts | free |
| EXP-13a | what should a `fail` verdict be allowed to do | wiring replay over 237 trails (gate/veto/shaded/advisory/none) | free |
| EXP-13b | confirm the evidence champion live | end-to-end on Sweden | not run (moot) |

Designs: `docs/EXPERIMENTS_VERIFIER_REDESIGN.md` (EXP-11),
`docs/EXPERIMENTS_VERIFIER_EVIDENCE.md` (EXP-12/13). Harnesses:
`evaluation/verifier_redesign.py`, `evaluation/exp12{a,b,c}_*.py`,
`evaluation/exp13a_wiring_replay.py`, `evaluation/replay_*.py`.

## 3. Headline results (Youden's J, fail = positive, higher = better)

| Finding | Number |
|---|---|
| Incumbent disprove on clean frozen evidence | J = 0.41 |
| Tristate verdict (EXP-11) | J = 0.03 (refutes 1 of 150) |
| Deterministic quote-gate on disprove (EXP-11) | J = 0.02 (sens 0.62 -> 0.10) |
| Disprove with no counter-search (E5) | J = 0.42 |
| Disprove with its own counter-search, frozen (E0, status quo) | J = 0.37 |
| Disprove with its live counter-search (production, EXP-12a) | J = 0.10 |
| Shape-conditional evidence (EXP-12c, in-sample) | J = 0.39 (+0.02 over E0) |
| Verdict relaxation (EXP-13a, best variant) | +3 match / +3 committed-wrong, non-significant |
| Verification layer vs bare confidence floor (EXP-13a) | +27 match, -43 abstain, +16 wrong |

Result files in `evaluation/results/`:
`verifier_redesign_verifier_tristate_v1.jsonl`, `exp12a_premise.jsonl`,
`exp12b_evidence_ladder.jsonl`, `exp13a_wiring_replay.jsonl`,
`substring_v2_replay.jsonl`, `commit_policy_grid.jsonl`,
`absence_receipts_replay.jsonl`.

## 4. What we learnt, by component

**The verifier was never broken; it was fed noisy evidence.** The Malta
"no discrimination" reading was an artefact of the production evidence of that
era. On clean evidence the same disprove prompt discriminates (J ~ 0.40).
EXP-12a proved this on identical items: the same researcher answer judged with
production evidence scored J = 0.10, with clean frozen evidence J = 0.41, the
whole gap in catching wrong answers (P(pass | wrong) 0.72 -> 0.38) at no cost in
false rejections.

**The verifier's value is cognitive, not retrieval.** Measured, confirming D15.
It discriminates best reasoning over the researcher's own evidence (E5, no
search, J = 0.42); its own counter-search adds nothing detectable (E0 0.37, not
significantly different) and its live form was the worst condition tested
(0.10). Probes help absence claims specifically (no-claims J 0.35 -> 0.50) but
that washes out in the pool (absence is 29 of 150) and did not survive even an
in-sample shape-conditional recipe (EXP-12c, +0.02).

**Nothing we changed beat the incumbent.** Four redesigns, four nulls: the
tristate verdict collapses to always-confirm/abstain; the deterministic
quote-gate strips real (paraphrased) refutations; richer evidence does not
raise discrimination; relaxing the verdict wiring trades matches for wrong
commits one-for-one. The incumbent `disprove`, hard-gate, current DIY-search
recipe is at or above every alternative tested.

**The confidence floor, not the verdict, is the binding precision control.**
The verifier verdict was the deciding factor on only 9 of 237 in-loop commits
(EXP-13a); the D37 0.65 floor blocks weak answers first. The verifier is an
advisor, not the in-loop gatekeeper.

**The verifier's influence flows through the Adjudicator.** Removing the whole
verification-plus-adjudication layer costs 27 correct answers and adds 43
abstentions while saving 16 wrong commits (EXP-13a, p < 0.002). Since the
verdict binds only 9 in-loop, most of that recovery is the Adjudicator weighing
the verifier's counter-evidence on the hard tail, recovering roughly two correct
answers per wrong one. D44 (abstain rather than commit an unsupported "no") is
what disciplines that precision cost.

## 5. What shipped

One production change, on its own receipt: **matcher v2** (`agents/tools/
substring.py::contains_v2`, wired into `agents/verifier.py`). It matches an
evidence quote per snippet with ellipsis-aware fragments, so a counter-quote
stitched across two unrelated snippets can no longer pass the grounding gate and
a legitimate within-snippet elision no longer wrongly fails. Replay over 639
researcher quotes: catches cross-snippet splices, rescues real elisions, admits
zero quotes absent from every snippet (`substring_v2_replay.jsonl`). Closes
FM-11 and part of FM-02. Tests: `tests/test_substring_v2.py`.

Two knobs were evaluated and dropped before they could ship: the absence
confidence-ceiling (net-negative on dev, deferred correct `no`s to catch no
wrong) and the absence receipts check (near-inert, the search templates already
name the country). `verifier_confidence` was audited and confirmed to gate
nothing; it remains telemetry.

## 6. The architecture, as we now understand it

The drawn architecture is Researcher -> Verifier-gate -> Adjudicator. The
measured architecture is different:

- **Researcher** finds an answer and its evidence. Its independence is the
  asset the multi-agent split exists to protect.
- **Confidence floor (0.65)** decides most cases: it is the real bouncer on
  commits.
- **Verifier** supplies a skeptical second opinion and a deterministic
  fabrication gate. Its verdict rarely changes the in-loop outcome; its value is
  the counter-evidence it hands onward, and its skepticism is cognitive (it does
  not need its own search).
- **Adjudicator** makes the hard calls at retry exhaustion, and is
  where most non-floor commits are decided. It is the more load-bearing of the
  two critical agents.

Two architectural ideas fell out of this and are recorded as future work, not
acted on:
- A merged **critic-decider** (Verifier folded into the Adjudicator) is the
  defensible consolidation, since both are post-research critical evaluation and
  the verifier's verdict barely gates in-loop. Merging the Researcher into the
  Adjudicator is the wrong merge: it collapses the independence the architecture
  is built on (the author grading their own work).
- The remaining headroom is upstream, in the quality of evidence the agents
  read, not in the verdict logic.

## 7. Open questions (each needs its own pre-registration)

1. **Adjudicator ablation.** Keep the production loop but abstain at retry
   exhaustion instead of adjudicating; isolate the Adjudicator's own
   contribution (free replay, same machinery as EXP-13a). The cleanest
   unanswered question in the architecture.
2. **Shape-conditional evidence, held out.** The probes-for-absence lead was
   in-sample only; a fresh-country dev arm would test whether it generalises.
   Low priority given the small in-sample effect.
3. **Critic-decider prototype.** Test a single agent that critiques and rules
   against the current two-step, on the existing trails.
4. **Live no-search verifier.** EXP-12b is classifier-level; a coordinator-flag
   dispatch on a fresh country would confirm the no-search / clean-search result
   end-to-end.

## 8. Honest caveats

- The classifier experiments (EXP-11/12) are single-shot on frozen evidence,
  not the live loop; the pairwise J differences mostly miss significance at
  n = 150 with 29 wrong-answer cases. The robust claims are the large effects
  (production 0.10 vs clean 0.41) and the qualitative collapses (tristate
  refutes 1 of 150), not the marginal ones (E5 0.42 vs E0 0.37).
- MT and NO are burned development sets (used repeatedly); no confirmatory
  claim rests on them. The one confirmatory dispatch (EXP-13b on untouched
  Sweden) was not run because its champion equalled the status quo.
- EXP-12a's matched set conditions on the latest researcher attempt, so it
  under-represents the messy abstained cases production struggles with.
- The deny-list (D24) and the honest-abstention principle held in every arm.

## 9. Artefact index

- Diagnosis and proposals: `docs/VERIFIER_REDESIGN.md`
- EXP-11 design and null: `docs/EXPERIMENTS_VERIFIER_REDESIGN.md`
- EXP-12/13 design and results: `docs/EXPERIMENTS_VERIFIER_EVIDENCE.md`
- Status board: `docs/EXPERIMENTS.md` (EXP-11/12/13 rows)
- SPEC decision: D45 (this programme's conclusion)
- Harnesses: `evaluation/verifier_redesign.py`, `evaluation/exp12a_premise.py`,
  `evaluation/exp12b_evidence_ladder.py`, `evaluation/exp12c_conditional.py`,
  `evaluation/exp13a_wiring_replay.py`, `evaluation/replay_substring_v2.py`,
  `evaluation/replay_commit_policy.py`, `evaluation/replay_absence_receipts.py`,
  `evaluation/_replay_common.py`
- Production code: `agents/tools/substring.py` (matcher v2),
  `agents/verifier.py` (gate wiring, probe generator), additive tristate models
  and prompts in `agents/models.py` and `agents/prompts/verifier.py`
  (evaluation-only, not on any production path)
- Tests: `tests/test_substring_v2.py`, `tests/test_tristate_models.py`
- Commits: 5ee0c45, 209c376, 79488e0, 5a4dbf7, 840760a, 081ceff, d434a02,
  29e29fc, 1722bd2, 6547dbc (plus the D45 / findings commit)
