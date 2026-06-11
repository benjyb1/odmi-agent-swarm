# EXP-12 / EXP-13: verifier evidence and verdict wiring (pre-registration)

Drafted 2026-06-11, immediately after the EXP-11 stage 1 null
(`docs/EXPERIMENTS_VERIFIER_REDESIGN.md`, change log 2026-06-11). EXP-11
rejected the verdict-vocabulary redesign and produced one reframing finding:
the incumbent disprove verifier discriminates well on clean frozen evidence
(Youden's J = 0.41 on the 150-candidate dev set; Malta alone 0.50) while the
same prompt barely discriminated in the Malta production trail
(P(pass | correct) 0.571 vs P(pass | wrong) 0.432, p = 0.23). The two open
questions are therefore not about the prompt:

1. **Evidence**: what information should the Verifier receive?
2. **Wiring**: what should its verdict be allowed to do?

This file pre-registers two experiments, each with a free phase on stored
data and a paid phase. It follows `docs/EXPERIMENTS_PROTOCOL.md` section 0
(R1 to R12). The commit adding this file predates every run it governs (R1).
The Verifier is present in every arm of every experiment below; nothing here
tests removing it. The no-verifier replay column in EXP-13a is a reference
quantity (what does the Verifier currently buy), not a candidate policy.

Read first: `docs/VERIFIER_REDESIGN.md` (diagnosis),
`docs/EXPERIMENTS_VERIFIER_REDESIGN.md` (EXP-11 design and null),
`evaluation/verifier_redesign.py` (the stage 1 harness this reuses),
`evaluation/results/verifier_redesign_verifier_tristate_v1.jsonl` (the frozen
dev evidence, reused heavily below).

---

## 1. Hypotheses

- **H1 (premise).** The production-vs-frozen discrimination gap is caused by
  the evidence the Verifier received, not by item selection. Test: on the
  SAME (question, country, researcher run) items, the stage 1 frozen-evidence
  verdicts are more often correct than the stored production verdicts.
- **H2 (evidence ladder).** Verifier discrimination (J) rises with richer
  evidence, holding the prompt fixed at disprove v3. Sub-hypotheses, each an
  arm: H2a confirmation-probe results help; H2b reading the cited source page
  helps; H2c more results per query helps; H2d (optional) rendering
  WAF/JS pages helps.
- **H3 (wiring).** Letting a Verifier `fail` advise rather than hard-block
  raises match rate at equal or lower committed-wrong, because the fail
  branch currently converts correct answers into abstentions more often than
  it catches wrong ones (the EXP-11 brief's claim, never yet tested at pair
  level on balanced data).
- **H4 (parked).** The tristate collapse was partly prompt design; a
  refute-biased tristate might recover catch. Parked: EXP-11 closed the
  vocabulary question, and reopening it now would be hypothesis-shopping.
  Recorded so the decision not to chase it is explicit.

---

## 2. EXP-12a: premise diagnostic (free, stored data only)

**Question.** H1: is the discrimination gap an evidence effect?

**Design.** Matched-pair comparison. For each stage 1 dev candidate
(`(country, question)` with its researcher run id, reconstructable as the
latest definite-answer researcher run with snippets), find the stored
production disprove verifier row on the SAME `researcher_run_id` (latest such
row if several). Both verdicts judged the identical researcher output, quote,
confidences, and snippets, under the same prompt (production rows are all
prompt_version_id 14, disprove v3) and the same model family. The remaining
differences are the independent-search evidence (live production search vs
the pinned frozen diy block) and the substring path (production v1 history vs
the stage 1 arm A v1, which match). Feasibility checked 2026-06-11: 58 MT +
134 NO production rows attach to those runs before dedup.

**Endpoints.**
- Primary: paired verdict-correctness, exact McNemar, production vs frozen,
  on the matched set (n about 150; power is modest and reported, R8).
- Secondary: P(pass | correct) and P(pass | wrong) per setting; the
  claim-direction gap (P(pass | yes) vs P(pass | no)) per setting, since the
  production pathology was direction-sorting; per-country splits.
- Mechanism audit: for discordant pairs, a deterministic diff of the evidence
  (snippet counts, empty-search flags, URL overlap) plus a 10-case hand read,
  classifying what differed.

**Decision rule.** H1 supported if frozen beats production on the paired
test at p < 0.05, or, failing significance at this n, if the frozen J exceeds
the production J by more than 0.15 with the direction gap also shrinking.
H1 refuted if matched-set discrimination is similar, which would mean the
stage 1 J = 0.41 was a selection artefact; that result would redirect the
programme away from evidence work, so this diagnostic runs first.

**Cost.** None. SQL plus the stage 1 JSONL. Harness:
`evaluation/exp12a_premise.py` (to build, read-only).

---

## 3. EXP-12b: the evidence ladder (calls, no dispatch)

**Question.** H2: which information raises J, prompt held fixed?

**Design.** The stage 1 harness rerun with one change: the assembly of the
evidence block varies per arm; the strategy is pinned to `verifier-disprove`
v3, substring v2 (production truth post-P4), same 150 dev candidates (frozen
candidate set, R2/R3), temperature 0, model default.

Phase 1 arms reuse the stage 1 freeze verbatim (zero new searches; the
adversarial and probe snippets are already stored per candidate):

| Arm | Evidence shown to disprove | New cost |
|---|---|---|
| E5 floor | Researcher snippets only, no independent search block | 150 calls |
| E0 baseline | E5 + frozen adversarial results (stage 1 block) | 150 calls |
| E1 probes | E0 + frozen confirmation-probe results | 150 calls |

Phase 2 arms (run only if phase 1 leaves the question open or finds a
gradient worth extending; gate recorded in the change log before running):

| Arm | Evidence | New cost |
|---|---|---|
| E2 source page | E1 + trafilatura full text of the cited source URL (httpx only, capped 4,000 chars; WAF pages recorded as unavailable) | ~150 fetches + 150 calls |
| E3 breadth | E0 with 10 results per query instead of 5, same frozen queries | ~450 diy searches + 150 calls |
| E4 render (optional) | E0 with Playwright enabled under a hard launch guard | risky; last |

**Endpoints.** J per arm (primary), false-rejection rate with Wilson CIs
(the recall guard: an arm must not buy catch with false rejections),
per-direction J, cost per arm. Planned ladder comparisons, exact McNemar on
verdict-correctness, Holm over three: E5 vs E0 (does the independent search
matter at all, the D15 "cognitive value" claim made measurable), E0 vs E1
(probes), E1 vs E2 (source page). E3/E4 exploratory.

**Decision rule.** Champion evidence configuration = highest J subject to
false-rejection rate no higher than E0's and a non-degenerate verdict mix.
The champion is a dev-set selection only; its confirmatory test is EXP-13b,
at system level. MT and NO stay burned for any classifier-level confirmatory
claim.

**Harness change.** `evaluation/verifier_redesign.py` gains an
`--evidence-arm` switch that re-assembles the user message from the existing
freeze records; only E2/E3 extend `freeze_evidence`. Carry the EXP-11
lessons: `--no-render` semantics for E0/E1/E5, BlockerShutdown caught, per
query rather than per channel.

---

## 4. EXP-13a: verdict-wiring replay (free, stored trails)

**Question.** H3: what should a `fail` be allowed to do?

**Design.** Deterministic replay over the stored full trails (Malta 60 and
Norway 143 finalised pairs, every attempt's researcher and verifier rows),
computing each pair's terminal outcome under each wiring. Every wiring
commits earlier than or equal to production (they only relax blocking), so
the stored attempts cover every simulated path; no missing-data
extrapolation. The method is the D44 receipt's.

| Wiring | A Verifier `fail` does | Commit rule at attempt k |
|---|---|---|
| W-gate (production) | blocks; retry, then adjudicate | pass AND conf >= 0.65 |
| W-veto-hard | blocks only on the deterministic substring hard-fail; LLM-judgement fails advise | (pass OR soft fail) AND conf >= 0.65 |
| W-adv2 shaded | raises the bar | conf >= 0.65 + 0.10 if fail, else 0.65 |
| W-adv1 floor-only | nothing in-loop (history still reaches the Adjudicator) | conf >= 0.65 |
| W-none (reference only) | not a candidate policy; quantifies what the Verifier buys | conf >= 0.65, no verifier |

Pairs not committed in-loop follow their stored adjudication and the
D32/D37/D44 finalisation rules, replayed as pure functions.

**Simulator fidelity check (gates everything).** W-gate replayed must
reproduce the actual `phase2_final` outcomes on at least 95% of pairs;
disagreements are audited before any variant number is read. A simulator
that cannot reproduce reality forfeits the experiment.

**Endpoints.** Per wiring on pooled golded MT+NO pairs: match, abstention,
committed-wrong, plus the W-none column as the Verifier's measured
contribution. Paired McNemar, production vs the best variant, on pair-level
match-vs-not and committed-wrong-vs-not.

**Decision rule (lexicographic, mirroring the project goal).** Provisional
winner = the wiring with (1) committed-wrong no higher than production, then
(2) highest match, then (3) lowest abstention. If no variant beats W-gate,
the wiring question closes with a null and production stands.

**Known limit (stated, R12).** The replay cannot model retry divergence
(a variant that commits at attempt 1 never sees the retries reality took, by
design; that is the policy's point). The confounder this leaves is that
production retries occasionally improve the answer; EXP-13b measures the
live loop and settles it.

**Cost.** None. Harness: `evaluation/exp13a_wiring_replay.py` (to build,
read-only). Coordinate with EXP-10 Phase B before changing any floor value;
the 0.65 floor is held fixed here.

---

## 5. EXP-13b: confirmatory end-to-end dispatch (the only paid dispatch)

**Question.** Do the EXP-12b evidence champion and the EXP-13a wiring winner,
bundled, beat production where it counts: live, in the loop, on an untouched
country?

**Design.** Two arms, paired on the identical pair list, on Sweden
(untouched, binary no-share 0.22, high-resource language; rule from EXP-11
section 7.2). Sample: all 27 no-gold binary + 27 seeded yes-gold
(dimension-stratified, seed 20260610) + all band questions with definite
gold, about 65 to 70 pairs; `scripts/build_se_eval_pairs.py` (to build),
list committed before dispatch (R3).

- Arm P: production coordinator at a named commit.
- Arm C (champion): identical except the EXP-12b evidence configuration and
  the EXP-13a wiring, both behind flags, defaults off.

Both arms inherit whatever the production chaining default is at run time
(EXP-7's question, not this one); only the two championed components vary.
Pinned `diy`, cold cache, same models, sequential arms, no concurrent
experiments (the EXP-9 lesson).

**Endpoints.** Per pair via `_MATCH_STATUS_SQL`: match, abstention,
committed-wrong; cost per pair with retries (R9); retry counts and
adjudicator involvement as mechanism telemetry.

**Decision rule (adoption, recorded as the next free D number).** Adopt the
champion iff committed-wrong(C) <= committed-wrong(P) AND match improves
with exact McNemar p < 0.05, or abstention falls by at least 10 points with
match within 2 points of production. Anything else: production stands, null
reported (R12).

**Prerequisites.** Swedish language code `sv` added to `run_coordinator.py`
(the D42 note lists SE as missing); the champion flags built and unit-tested;
EXP-12b and EXP-13a complete and their winners recorded in this file's
change log before the dispatch (R1).

**Cost.** ~130 to 140 pair-runs, roughly 600 to 1,100 LLM calls plus diy
searches. The single largest spend in the programme; gated on both free
phases and the ladder.

---

## 6. Execution order and gates

1. **EXP-12a** (free) and **EXP-13a** (free), in either order or parallel.
   Gate: if EXP-12a refutes H1, EXP-12b shrinks to E5/E0 only (the selection
   question still needs the anchor) and the programme re-plans before
   spending; if the EXP-13a simulator fails fidelity, EXP-13b's wiring arm
   reverts to W-gate.
2. **EXP-12b phase 1** (450 calls). Gate to phase 2 recorded in the change
   log with reasons.
3. **EXP-13b** once, bundling the recorded winners.

---

## 7. Threats and controls

| Threat | Control |
|---|---|
| Selection effect masquerading as an evidence effect | EXP-12a matches on the identical researcher run; the diff is only the evidence |
| Dev-set overfitting (MT/NO burned by EXP-11) | All selection on dev; the only confirmatory claim is EXP-13b on untouched Sweden |
| Degenerate always-pass flattering raw accuracy | J primary, false-rejection guard, verdict-mix reported (the EXP-11 lesson, kept) |
| Replay diverges from the live loop | Simulator fidelity gate (95%) plus EXP-13b as the live check |
| Provider/cache luck between arms | Frozen evidence reused verbatim in phase 1; pinned diy cold cache elsewhere (R2) |
| Slow-fetch blockers killing runs | BlockerShutdown caught per query; render off unless E4's guard is built |
| Floor interactions with EXP-10 Phase B | Floor held at 0.65 throughout; coordinate before any change |
| Multiple comparisons | Holm within each planned family; everything else labelled exploratory |

## 8. Compliance (R1 to R12)

R1 this commit precedes all runs; R2 paired arms on identical items
throughout; R3 seeded, committed candidate and pair lists; R4 Sweden
confirmatory is balance-viable (0.22 no-share), MT/NO dev only; R5/R6 not
applicable (no LLM judge; gold is ODMI); R7 evidence and wiring varied in
separate experiments before one bundled confirmatory; R8 statistics fixed
above, power stated where thin; R9 cost per item with retries in EXP-13b;
R10 deny-list untouched in every arm; R11 fixed samples, partials reported
as partials; R12 nulls are findings, drops logged, receipts in JSONL.

## Change log

- 2026-06-11 (close): **EXP-12c shape-conditional recipe, the last lead, closed.** `evaluation/exp12c_conditional.py`, an exact recombination of the stored E5/E1 verdicts (absence -> E1, presence -> E5; zero new calls). POST-HOC and in-sample by construction (the routing rule came from these 150 candidates), so it is a screen, not a confirmation. Result: EC J=0.39 vs E0 0.37 (gap +0.02 even in-sample), FRR 0.20 > E0's 0.18, McNemar p=0.73. The no-claims gain does not survive pooling (absence is 29/150). The lead does not clear the bar; no held-out dispatch justified. **The entire verifier programme (EXP-11/12/13) now closes**: no prompt, wiring, or evidence change beats the incumbent; the one shipped output is matcher v2 (EXP-11 P4).
- 2026-06-11 (later still): **EXP-12b phase 1 run (448/450 calls; 2 disprove
  schema failures, NO:I9-c and NO:P2 on E5, dropped). H2 refuted; 13b is moot.**
  `evaluation/exp12b_evidence_ladder.py`, results `exp12b_evidence_ladder.jsonl`.
  Prompt pinned to disprove v3, substring v2, only the evidence block varies.
  J (fail = positive): **E5 (no independent search) 0.42** (sens 0.64, spec 0.78,
  FRR 0.23 [0.16, 0.31]); **E0 (adversarial search, status quo) 0.37** (0.55,
  0.82, FRR 0.18 [0.12, 0.26]); **E1 (+ probes) 0.35** (0.55, 0.80, FRR 0.20).
  Richer evidence did not raise discrimination; the no-search floor is
  numerically the best. Ladder McNemar non-significant (E5 vs E0 b=5 c=8
  p=0.58; E0 vs E1 b=5 c=3 p=0.73; Holm 1.0). Champion by the pre-registered
  rule (max J subject to FRR <= E0's 0.18): **E0**, since E5's higher J is
  bought with more false rejections (0.23 > 0.18) the guard forbids.
  - **Direction split (the one live lead).** On absence claims, search and
    probes DO help: no-claims J E5 0.35 -> E0 0.45 -> E1 0.50; on presence
    claims search hurts: yes-claims E5 0.37 -> E1 0.29. The probes help exactly
    where designed; the pooled J is flat because yes-claims dominate (121/150).
    A shape-conditional recipe (probes for absence, minimal search for presence)
    is the lead, but it is not a pre-registered arm, so pursuing it needs its
    own pre-registration, not a post-hoc graft.
  - **Reconciliation with EXP-12a.** 12a found production J=0.10 vs frozen
    E0 J=0.41 on identical items; 12b shows even E5 (no search) reaches 0.42.
    So production's collapse was not a lack of evidence (none is needed); it is
    most consistent with production's live search of that era injecting noise
    (P(pass|wrong) 0.72 production vs 0.38 frozen). Production standardised on
    DIY-only after that era (D43/D36), so clean DIY search (= E0) is already
    the production recipe, which is exactly the champion. The verifier's value
    is cognitive (D15), now measured: it discriminates on the researcher's own
    evidence and its own search adds noise more than signal on the majority
    (presence) class.
  - **EXP-13b decision: not dispatched, moot.** The champion equals the current
    production recipe (E0 = clean DIY adversarial search), so there is no new
    component to bundle against production. Dispatching a production-vs-
    production run would burn the only paid step in the programme to confirm
    "no change". Per the pre-registered logic (mirroring the NL confirmatory
    after EXP-11: nothing beat the baseline on dev, so the confirmatory does not
    run), 13b is recorded as moot. The verifier-evidence thread closes here; its
    concrete shipped output is matcher v2 (EXP-11 P4). The shape-conditional
    probe recipe is logged as future work needing fresh pre-registration.
- 2026-06-11 (later): **EXP-12a and EXP-13a run (both free phases).**
  - **EXP-12a (H1): directionally supported, promoted to EXP-12b.** 149 of 150
    stage 1 candidates matched to a production disprove verdict on the same
    researcher run (`evaluation/exp12a_premise.py`, results
    `exp12a_premise.jsonl`). On identical items: production J = 0.10 vs frozen
    J = 0.41 (restricted to substring-pass-both-sides, where the hard-gate
    asymmetry cannot fire: 0.12 vs 0.45, n = 143). The gap is concentrated in
    catching wrong answers: P(pass | wrong) 0.72 production vs 0.38 frozen,
    with P(pass | correct) near-equal (0.82 vs 0.79), so the frozen evidence
    buys catch without false rejections. Paired McNemar not significant
    (b=6, c=12, p = 0.24 all; b=4, c=12, p = 0.077 restricted), so the
    pre-registered significance criterion fails while the J-gap criterion
    (+0.31 > 0.15) passes. The direction-gap criterion is vacuous on this
    slice: the matched set conditions on the LATEST researcher attempt
    (disproportionately committed answers), and production shows no direction
    gap there (pass|yes = pass|no = 0.85); among correct answers the frozen
    gap is small (0.81 vs 0.73), so frozen is not direction-sorting, it is
    catching wrong no-claims. Mechanism audit: production search was empty on
    0 of 18 discordants, so the difference is evidence content, not
    availability. Verdict: H1 holds directionally at modest power; EXP-12b
    proceeds in full.
  - **EXP-13a (H3): refuted, a clean null; the wiring question closes.**
    `evaluation/exp13a_wiring_replay.py` over 237 golded MT+NO pairs, results
    `exp13a_wiring_replay.jsonl`. Simulator fidelity 237/237 = 1.000 against
    actual finals (gate >= 0.95 passed). Outcomes (match / abstain / wrong):
    W-gate 137/69/31; W-veto-hard 140/63/34; W-adv2 137/68/32; W-adv1
    140/63/34. Every relaxation buys ~3 matches at ~3 extra committed-wrong
    (McNemar all non-significant); per the pre-registered lexicographic rule
    (committed-wrong first) no variant beats production, so **W-gate stands**.
    Mechanism: the verdict block binds on only 9 of 237 in-loop commits
    (116 vs 125); the D37 floor is the binding constraint, so re-wiring the
    verdict has little to act on. The W-none reference column (no verifier, no
    adjudication): 110/112/15, i.e. the verification scaffolding as built nets
    +27 matches and -43 abstentions at +16 committed-wrong versus a bare
    floor pipeline (McNemar p < 0.002 both ways), which quantifies the
    Verifier-plus-Adjudicator contribution and shows most of it is realised at
    the adjudication stage (W-adv1 vs W-none differ only by that fallback).
  - **Consequence for EXP-13b (pre-registered gate applied).** The wiring arm
    reverts to W-gate; EXP-13b becomes a single-component confirmatory test,
    production vs production-plus-EXP-12b-evidence-champion, on Sweden. Two
    arms, unchanged sample and adoption rule.
- 2026-06-11: created. Pre-registers EXP-12a/12b (evidence) and EXP-13a/13b
  (wiring) following the EXP-11 stage 1 null. No run yet at commit time.
