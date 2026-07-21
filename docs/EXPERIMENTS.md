# Experiments

The status board for swarm experiments: what is planned, queued, running, and
done, with results once they land. Decisions and rationale live in `SPEC.md`;
the machine registry is the `experiments` SQLite table (D27). This file is the
human-readable view, updated whenever an experiment changes state.

**Status values:** `planned` (designed, not scheduled) · `queued` (next to
run) · `running` · `done`.

## Config-freeze gate (critical path to EXP-36 headline)

> **Superseded 2026-07-13 (D64):** all seven items below are now DONE or
> disclosed-and-accepted (freeze tag is the one deliberate exception, applied as
> the last step before dispatch). This resolves the 2026-07-12 audit note that
> stood here previously, which had confirmed the D62 transport fix (EXP-34
> pilot 20/20) but flagged the retrieval-strategy verdict and the full
> EXP-34/29 result as not yet queryable outside their own worktree; both landed
> since (see gate item 3 and EXP-29's row below). EXP-31 (`exp31_frozen_headline_v2`)
> is discarded: it pinned the cut Sonnet 5 model and pre-dated the EXP-34
> verdict and the B1-B4 coordinator fixes. The headline is re-minted as
> **EXP-36** (`exp36_frozen_headline`), fresh pre-registration in
> `docs/EXPERIMENTS_EXP36_PREREG.md`. EXP-31's row below is marked discarded
> and kept as history; see the new EXP-36 row for current state.

The work that must land before the production config is frozen and the held-out
headline run (EXP-36) is dispatched. Everything not on this list is post-freeze
or cut.

| # | Item | Type | Spend | Blocks freeze? | Status |
|---|---|---|---|---|---|
| 1 | EXP-19 verifier counter-search | analyse (275 finals exist) | 0 tokens | yes | DONE (2026-07-10): keep `always` (no config change). Pooled rule mechanically favours `never`, but the arms are unbalanced (never under-finalised on AL: 5 vs 26) so the pooled marginal is composition-confounded; within-country never wins NL (acc 0.71 vs 0.60) but loses MT (0.40 vs 0.70) and is untested on AL; paired McNemar null (n=38, p=1.00). Verdict: inconclusive on the multi-country question, keep `always`, consistent with EXP-14. Does not flip the config. |
| 2 | EXP-20 retry chaining | analyse (212 finals exist) | 0 tokens | yes | DONE (2026-07-10): keep `baseline` (chaining not promoted). Against EXP-20's 4-part rule: bal_acc up (0.355 vs 0.320) but FPR NOT flat (0.387 vs 0.346, +0.041) and McNemar not significant (n=48, p=0.500); calls/resolved +7.5% (within +10%). Two of four conditions fail. `chaining_analysis.py`'s looser EXP-7 non-inferiority framing reports "passes" but EXP-20's stricter promotion rule governs. Does not flip the config. Result JSON `evaluation/results/chaining_exp20_chaining_committing.json`. |
| 3 | EXP-34 retrieval strategy | run, 2 arms (baseline_narrow_then_wide vs wide_only), NL+MT+AL, `claude-sonnet-4-6` | 156-pair dev battery, `exp34_retrieval_strategy_s46` | yes (prime NL-FP suspect) | DONE (2026-07-13): **adopt `wide_only`**. NL adoption rule met (neg-gold FP 17->14 paired, commit-acc 0.62->0.67). Pooled across NL+MT+AL: commit-acc 0.679->0.733, no country regresses, so adopted on accuracy grounds. FP-reduction does NOT generalise at full power (pooled McNemar p=0.727; MT no signal, AL small reverse) — disclosed, no general FP claim. Code default flipped `narrow_then_wide`->`wide_only` across dispatcher/coordinator/researcher (D64). Inert on the held-out 8 either way (no trusted-domain lists there). |
| 4 | EXP-18 retrieval breadth | decide, no run | 0 | yes | DONE (2026-07-10): keep r5. r10 rested on one NL run at +17% system cost; no multi-country confirmation exists, so the cheaper r5 default stands (adopt-r10 rule never met, never run). |
| 5 | EXP-C / D50 neg-evidence licence | run, powered on-config dev confirm | NL52+MT45/arm | yes | DONE (2026-07-13): keep full, neg_licence REJECTED. The powered on-config confirm (`d50_neg_licence_confirm`, Sonnet 4.6, picker on, verifier_search always, narrow_then_wide) closes the D50 gap: pooled TN recall +0.05 (0.24->0.29) but neg-gold FPR +0.09 (0.29->0.38) and commit_acc -0.06 (0.71->0.65); McNemar n=46 p=1.00. Per-country: NL TN +0.11 / FPR +0.07; MT TN +0.00 / FPR +0.11 plus 2 wrong-`no`-on-yes. Adoption rule (TN up, neg-FPR flat) NOT met on any cut. Overturns the prior "favoured" (that rested on underpowered off-config NL + excluded held-out). Full prompt stays for the freeze, not just deferred. |
| 6 | Housekeeping: ARCHITECTURE.md freeze tag · SE catalogue route · deny-list audit clean · resume behaviour verified | gates | 0 | yes | PARTIAL (2026-07-13): SE catalogue route configured + verified (sparql on dataportal.se, 2026-06-10, D24-compliant); deny-list/leakage audit clean (244 committed pairs, 1 benign bundesregierung strategy-page candidate at >=8 shared words, matches prior baseline); resume behaviour verified (38 dispatch/resume tests pass). Transport is D62 (user-turn folding, cloak on; D61's `system`-param revert did not hold, see SPEC). ARCHITECTURE.md freeze tag STILL PENDING (deliberately held until dispatch DB hygiene + audits re-run clean on the canonical DB). |
| 7 | Coordinator data-integrity fixes (B1-B4) | fix + test | 0 tokens | yes | DONE (2026-07-13, independently fixed and reconciled from two branches on merge — see the 2026-07-13/2026-07-12 SPEC.md change-log entries for which branch originated which fix): B1 `invalid_answer_shape` now retries instead of committing junk; B2 a final-attempt Verifier `schema_invalid` now adjudicates on the answer in hand instead of dropping the pair as `agent_failure`; B3 an empty catalogue denominator now abstains/falls back to web instead of reporting "<10%"; B4 the dashboard drops the cut Sonnet 5 from both `1_Run_Console.py` and `6_Models.py` (the latter had been deliberately kept in this branch's own prereg as a labelled D59 comparison; the other branch's fully-cut version was kept on merge — flagged to Benjy, not decided unilaterally). New tests `tests/test_coordinator_bug_fixes.py`; full suite re-verified after merge. EXP-18/19/20/34 verdicts were measured pre-fix; the fixes touch only malformed-output edge cases, not the tested knobs, so the verdicts carry (disclosed in the EXP-36 prereg). |

**Not on the gate (post-freeze or cut):** EXP-28 researcher_only arm (~90 pairs
left, stalled on D58 auth bug) is characterisation for the report's ablation
table, not a config decision: the production trio stays regardless, so it does
not block the freeze or EXP-36. Finish it before write-up, not before dispatch.
EXP-29 (Sonnet-4.6 contrast) ran and closed (D63; underlying rows subsequently
lost to operator error, see EXP-29 row). EXP-32/33 (Haiku, tiered) run after
EXP-36; their specs do not exist yet and, when written, must explicitly pin
`search_strategy: narrow_then_wide` in `baseline_knobs` to match their EXP-28
`trio_s46` control, which ran before the D64 default flip (EXP-35's spec was
patched with this pin 2026-07-13 for the same reason). EXP-35 (self-critique)
post-freeze characterisation. EXP-36 is the headline the freeze unlocks, not a
gate item.

| ID | Experiment | Status | Scope | Result (short) |
|---|---|---|---|---|
| EXP-1 | DIY vs Tavily, adjudicated (refreshed) | done | FR, 90 pairs | DIY wins 89% of 55 decided pairs (49/6/1), Wilson CI [78,95], p<1e-4; 42/45 = 93% [82,98] under strict both-orientation exclusion; leads all 3 dimensions |
| EXP-2a | Search-knob cost vs quality | queued | FR subset | pending |
| EXP-2b | Search-knob cost vs quality | planned | low-resource countries | pending |
| EXP-3 | DIY vs Tavily, multilingual | planned | RO / EE / HU and other thin-web countries | pending |
| EXP-4 | Brave head-to-head | planned | FR first | pending |
| EXP-5 | Five-provider search A/B | planned | TBD (the parked June plan) | pending |
| EXP-6 | Verifier strategy discrimination (4-arm signal detection) | dropped (this round, 2026-06-09) | primary Malta natural errors, NL secondary, FR + injected robustness | parked by decision; the four-arm verifier-strategy comparison is not a priority for the current pass. Apparatus and the partial run stay in the repo so it can be revived. Not run. |
| EXP-7 | Retry chaining: accumulate evidence across the loop | done (2026-06-11) | Malta primary, 40 pairs/arm | chained beats baseline directionally: balanced accuracy 0.217 vs 0.167, recoveries 9 vs 6, false-positive rate 0.18 vs 0.25 (not raised, the co-primary), abstention 0.725 vs 0.80. Recovery McNemar p=0.375 (not significant; underpowered by Malta's 72-80% abstention ceiling). Per-pair call median delta 0 (Wilcoxon p=0.83). Pre-registered joint non-inferiority claim passes. Verdict: promising, not proven; adopt as the optimisation baseline. Result: `evaluation/results/chaining_retry_chaining_mt_v1.json`. |
| EXP-8 | Cost-side optimisations (Family 1) | planned | baseline + prompt-compressed / retrieval-tight / cache-hot / model-fallback; MT primary, NL secondary | unblocked; Malta baseline done (60/60), condition-tagged runs over the same pair list are runnable |
| EXP-9 | Model variants (Family 3) | closed as stalled (D57, 2026-07-02): 21 of ~300 finals, Sonnet 4.6 era, old Malta pairs, pre-D55 transport; superseded by EXP-32/33 | Haiku / Sonnet / Opus / tiered / Mistral; MT primary, NL secondary | dispatching all five arms over the Malta 60 via `scripts/run_exp9_model_variants.sh`, knobs pinned (provider diy, cold cache, disprove, 5 results, 3 retries, full prompt, unchained), only the model varies. Mistral-large-latest added as a cross-family arm. Caveat: overlaps the Norway dev sweep, so the latency endpoint may be contention-inflated; token-cost and accuracy unaffected. |
| EXP-10 | Malta failure-mode audit + confidence-floor recovery | done (2026-06-23, free replay): keep the 0.65 floor; non-matches are 61% fixable, 0% structural | MT finalised pairs vs ground truth; Phase A taxonomy, Phase B floor sweep | floor sweep validates 0.65 by the pre-registered rule (lowering to 0.50 recovers 6 correct but at 0.75 precision, below the 0.80 bar; negative-class FPR flat at 0.13 across floors). Phase A: of 28 non-matches, 17 fixable (7 fetch 4xx/5xx, 6 below-floor, 4 other), 11 genuine wrong, 0 structural. Biggest fixable bucket is retrieval-side |
| EXP-11 | Verifier redesign: tristate verdict, gated extremes, absence policy | stage 0 done (2026-06-10); stage 1 done (2026-06-11), redesign NOT adopted (null); stage 2 not triggered | stage 0 free replays (knobs frozen); stage 1 classifier ladder, MT+NO dev / NL confirmatory / FR-augmented robustness; stage 2 end-to-end paired dispatch on SE | stage 0 shipped matcher v2 (P4), dropped the absence ceiling and parked the receipts check; stage 1 dev ladder (150 candidates) is a clean NULL: incumbent disprove J=0.41 beats tristate (J=0.03) and the deterministic gate (J=0.02), which collapse the adversarial catch. Key reframing: disprove discriminates well on clean frozen evidence, so the Malta "no discrimination" was the production evidence/loop, not the prompt. Redesign not adopted; NL confirmatory not triggered. Runbook `EXPERIMENTS_VERIFIER_REDESIGN.md`; diagnosis `VERIFIER_REDESIGN.md`. Successor questions pre-registered as EXP-12/EXP-13 |
| EXP-12 | Verifier evidence: premise diagnostic + evidence ladder | done (2026-06-11). 12a H1 supported; 12b H2 REFUTED; 12c shape-conditional lead closed | 12a free matched-pair production-vs-frozen on stored MT/NO; 12b evidence ladder E5/E0/E1 (+E2/E3) on the 150 dev candidates, J primary | follows the EXP-11 reframing; 12a tests whether the discrimination gap is an evidence effect (H1) before money is spent; 12b holds disprove fixed and varies only the evidence block, phase 1 reuses the stage 1 freeze (zero new searches). `EXPERIMENTS_VERIFIER_EVIDENCE.md` |
| EXP-13 | Verifier verdict wiring + evidence confirmatory | 13a done (NULL, W-gate stands); 13b MOOT (champion = status quo, not dispatched) | 13a free deterministic replay over MT 60 + NO 143 stored trails (simulator must reproduce production on >=95% of pairs); 13b two-arm end-to-end on Sweden bundling the EXP-12b evidence champion | tests H3 (a fail that advises rather than hard-blocks); W-none is a reference column quantifying the Verifier's contribution, not a candidate; lexicographic rule: committed-wrong first, then match, then abstention. `EXPERIMENTS_VERIFIER_EVIDENCE.md` |
| EXP-14 | Verifier search policy: never / elective / always counter-search | done (partial, 2026-06-23): never vs always on NL; elective stubbed | NL (dev) + AL hard regime; held-out confirmation deferred to the frozen headline run | the "never" arm is the live confirmation of the verifier programme's biggest result (production J 0.10 vs clean 0.42); the "elective" arm gives the Verifier counter-search as a tool it chooses after reading the Researcher's evidence, motivated by the EXP-12b direction split (counter-search helps `no`-claims J 0.35->0.50, hurts `yes`-claims 0.37->0.29) which a fixed routing rule could not exploit (EXP-12c +0.02, dropped). Endpoint J by claim direction + FRR; cost is the tool-call rate on the elective arm. NL not MT: Malta's half-Maltese estate is a language confound (see programme note) |
| EXP-15 | Adjudicator standalone ablation, under the winning EXP-14 verifier | planned | NL/NO stored trails (replay); no held-out run pre-freeze | isolates the Adjudicator's own contribution (abstain at retry exhaustion vs adjudicate), the cleanest open question in the architecture; re-run under the no-/elective-search verifier so the result reflects the new evidence channel, not the noisy live-search one. Free replay machinery shared with EXP-13a W-none |
| EXP-16 | Adjudicator free candidate selection | done (2026-06-23, NULL): standard vs free on NL; keep standard | NL primary (balanced), FR easy-tail check | attacks the 74% oracle / 44% observed selection ceiling. Revise the verdict taxonomy so the Adjudicator can commit any of the up-to-4 Researcher attempts' answers explicitly, not just the final-researcher / verifier / neither framing. Endpoint: recovery against the oracle headroom at a held false-positive bound. Confidence ranking already failed here (rec 3, withdrawn), so the selector must reason over evidence |
| EXP-17 | Search-funnel optimisation family | partial: breadth done (NL, r10 wins); picker fidelity done (NL, 2026-06-23, keep picker); truncation pending | FR non-Quality 90 (web-answerable), candidate-recall endpoint | the retrieval gate. Three arms over the lossy DIY funnel: (a) snippet-picker fidelity (current <=3x500-char LLM pick + drop-on-no-pick vs raw trafilatura chunks vs higher cap); (b) breadth / rank-depth (EXP-2a, results/query 5->8/10, queries 3->4); (c) prompt-truncation sweep (`max_chars_per_snippet` 600->1200->full). Measured on candidate recall (gold answer present in any Researcher attempt) to decouple retrieval from selection. FR not MT: the funnel only bites where answers are on the open web, and Malta's abstention ceiling is structural |
| EXP-18 | Retrieval breadth, multi-country confirmation (broadens EXP-17 breadth) | designed (2026-06-23), not run | FR + AL + NL, candidate-recall endpoint, DIY-only | confirms r5 vs r10 beyond one NL run before a +17% system-wide cost switch. Adopt r10 only if pooled recall +>=0.05 and no reversal on thin-web AL. Needs clean FR + AL pair-sets. `docs/EXPERIMENTS_NEXT.md` |
| EXP-19 | Verifier counter-search, multi-country (broadens EXP-14) | done (2026-07-10): keep `always`, inconclusive on the multi-country flip | NL+MT+AL (~78 negative golds), DIY-only | re-tests never vs always beyond NL n=51 where the deciding FP margin (0.62 vs 0.58) was inside noise. Pooled: always acc 0.63 / FPR 0.41, never acc 0.67 / FPR 0.30 at lower cost -> pooled rule fires for `never`, BUT the never arm under-finalised on AL (5 vs 26 pairs), so the pooled marginal is composition-confounded (survivorship on the hard thin-web country). Within-country: never wins NL (0.71 vs 0.60) but loses MT (0.40 vs 0.70, FPR 0.67 vs 0.50) and is untested on AL; paired McNemar null (n=38, p=1.00). Verdict: keep `always` (status quo, consistent with EXP-14); config not flipped. `evaluation/specs/exp19_verifier_search_multicountry.json` |
| EXP-20 | Retry chaining on committing countries (broadens EXP-7) | done (2026-07-10): keep `baseline`, chaining not promoted | NL+AL (commit more than Malta), DIY-only | re-tests baseline vs chained where recoveries are observable (Malta was 72-80% abstention, p=0.375). Promotion rule (all four required): bal_acc up, FPR flat, calls/resolved <=+10%, McNemar p<0.05. Result: bal_acc up 0.355 vs 0.320, FPR ROSE 0.387 vs 0.346 (+0.041, fails flat), calls/resolved +7.5% (ok), McNemar n=48 p=0.500 (fails significance). Two of four fail -> keep baseline. `chaining_analysis.py`'s looser EXP-7 non-inferiority claim reports "passes" but does not govern here. Result: `evaluation/results/chaining_exp20_chaining_committing.json`. |
| EXP-21 | Frozen headline whole-system evaluation | superseded by EXP-31 (D57, 2026-07-02): the ID is contaminated by a 2026-06-24 partial dispatch (301 finals, FI/HR/SE, pre-freeze config); all rows voided for reporting | D47 held-out 8 (BA MK ME BG / FI HR SE BE), ~1,144 pairs, DIY-only | the whole-system end-to-end test: production architecture on unseen countries, balance-aware + three-outcome, stratified by dimension and resource. No adoption rule (it is the reported headline). Runs after EXP-18/19/20 land or are deferred, after the ARCHITECTURE.md freeze. `docs/EXPERIMENTS_NEXT.md` |
| EXP-23 | Trusted-domain narrow-then-widen retrieval, multi-country (SRCH-5/6/7) | **stale/no verdict — flagged 2026-07-12.** Board previously said "running (dispatched 2026-06-24), Opus 4.6, NL+MT+AL"; the DB (`experiment_id='exp23_narrow_then_widen_nl'`) actually holds 167 `phase2_researcher_runs` rows, all `claude-sonnet-5`, NL only, dated 2026-07-02 14:09-16:36 — a different run than described, no MT/AL, no narrow_only arm. Whichever record is right, there is no usable verdict; superseded by the EXP-34 re-pin (`exp34_retrieval_strategy_s46`), which now has a landed verdict (see EXP-34's row below). | NL only (per DB), 167 researcher-run rows, `claude-sonnet-5` | tests whether trusted-domain narrowing is the cause of the NL false-positive rate on negative golds and/or suppresses recall on thin-web AL. Three arms as designed: baseline_narrow_then_wide (production) vs wide_only (treatment) vs narrow_only (attribution control). Promote wide_only only if FP cuts >=5pp on NL AND commit-acc non-inferior (delta >=-0.02). Analysis: `evaluation/analyze_exp23.py`, manipulation check: `evaluation/manipulation_check_exp23.py`, spec: `evaluation/specs/exp23_narrow_then_widen.json` |
| EXP-28 | Architecture ablation ladder: trio / no_adjudicator / researcher_only | **incomplete, flagged 2026-07-12: board said "running", DB shows only 1 of 3 arms has any data.** `phase2_researcher_runs` for `exp28_arch_ablation` has 311 rows, all `condition_label='trio_s5'` (99 finalised pairs); `no_adjudicator_s5` and `researcher_only_s5` have zero rows (researcher_only stalled on the D58 auth_unavailable bug). Per D59, `trio_s5` itself is a collapsed-coverage artefact (balanced accuracy vs June 4.6 dropped hard), not a valid baseline point. The ladder needs a full 4.6 re-run before it answers anything; EXP-15 (Adjudicator isolated contribution) remains open. Separately, D63's zero-cost replay of a DIFFERENT 156-pair 4.6 battery (`trio_s46`, not this `trio_s5` row) filled in `no_adjudicator`/`researcher_only` comparisons before that dataset was lost — see EXP-29's row, which is the 4.6-era run this ladder should really be read against. | MT60+NL52+AL44 design; only `trio_s5` (99 pairs) has data, on the now-superseded Sonnet 5 | one knob (`pipeline_mode`). Isolates the Adjudicator (trio vs no_adjudicator, the owed EXP-15 design run live), the Verifier loop (no_adjudicator vs researcher_only), and the whole verification layer (trio vs researcher_only, the live counterpart of EXP-13a's replay: -27 correct / +16 wrong avoided / net -11). Characterisation, not optimisation: production trio stays regardless. Pre-reg `docs/EXPERIMENTS_ARCH_ABLATION.md`; spec `evaluation/specs/exp28_architecture_ablation.json` (still pins `claude-sonnet-5`, needs a 4.6 spec before re-running) |
| EXP-29 | Sonnet 5 vs Sonnet 4.6 whole-stack model contrast | **Two different registrations, reconciled 2026-07-13; do not read as contradictory.** The original single-shot ID (`exp29_sonnet5_model`, dispatched 2026-07-01) stalled near-empty (audited 2026-07-12: effectively zero usable rows for this experiment_id) and is moot in its original form — D59 already reverted the default to 4.6 without waiting for it, and the model-vs-transport disambiguation it was meant to do is now served by the EXP-34 4.6 pilot (D62). Separately, the SAME underlying question was re-run under an incremental naming scheme (`evaluation/specs/exp29_s46_10pct_pilot.json` through `exp29_s46_100pct_final.json`) as the `trio_s46` battery, which **did complete**, 156 pairs, 2026-07-10..12, on the D62 transport (**closed, D63**) — then had its underlying data lost to an accidental `git checkout -- data/odmi.db` in the source worktree, so its numbers are transcribed history, not re-queryable. Neither registration blocks EXP-36 (model family per D59, pipeline per D54 were already settled independently of this gate). | Original ID: near-zero rows. Renamed battery: 156 pairs, single arm trio_s46, D62 transport; control was EXP-28/trio_s5 | was to be the first Sonnet 5 vs 4.6 contrast under a shared transport (adoption rule pre-registered: default switches to claude-sonnet-5 only if trio_s5 non-inferior on balanced accuracy AND no-gold FP rise <=2pt); superseded by D59's revert before the gate was needed. The renamed `trio_s46` battery instead became the first clean 4.6 whole-stack data point on the D62 transport, matched June s46 like-for-like (no transport regression, see the 2026-07-12 "comparator artefact" SPEC.md change-log entry), before the data loss. |
| EXP-31 | Frozen headline run v2, all eight held-out countries | **DISCARDED (2026-07-13, D64)**, never dispatched (0 rows in any DB) | D47 held-out 8 (BA MK ME BG / FI HR SE BE), ~1,144 pairs, eight per-country sub-batches, DIY-only | registered 2026-07-02 (D57) as the exp21 replacement, but pinned the cut `claude-sonnet-5` model (D59 reverted it 2026-07-09) and pre-dated the EXP-34 verdict and the B1-B4 coordinator fixes. Replaced by **EXP-36** below under a fresh pre-registration. Registry row kept as inert history, mirroring how EXP-21's rows stayed after D57. |
| EXP-32 | All-Haiku whole-stack cost point | registered (2026-07-02), runs after EXP-36 | 156-pair dev battery (MT60+NL52+AL44), single arm haiku_h45, all roles + picker + query-gen on claude-haiku-4-5 | lower anchor of the RQ5 cost-quality frontier; control is EXP-28 trio_s46 (same pairs, same knobs, only model family differs, EXP-29 encoding pattern) — see EXP-29's row above for which `trio_s46` registration this refers to. Spec not yet written; when it is, pin `search_strategy: narrow_then_wide` explicitly to match the control (D64 flipped the code default to `wide_only`). Supersedes stalled EXP-9. Adoption rule declared but expected to fail (balanced-acc delta >= -0.02 AND neg-FP rise <= 2pt). `docs/EXPERIMENTS_FINAL_PROGRAMME.md` |
| EXP-33 | Tiered models: Haiku researcher-side, Sonnet checker-side (D18) | registered (2026-07-02), runs after EXP-32 | 156-pair dev battery, single arm tiered: researcher + query-gen + picker on Haiku, verifier + adjudicator on the production Sonnet | tests "cheap generator, expensive checker"; the picker rides the cheap side because it is the largest single spend line and is researcher-side. Spec not yet written; pin `search_strategy: narrow_then_wide` explicitly for the same reason as EXP-32. Adopt only if cost per committed-correct <= 0.6x baseline AND balanced-acc delta >= -0.02 AND neg-FP rise <= 2pt; otherwise a frontier point. `docs/EXPERIMENTS_FINAL_PROGRAMME.md` |
| EXP-34 | Trusted-domain narrow-then-widen verdict (EXP-23 redo) | **DONE (2026-07-13)**: adopt `wide_only` | NL+MT+AL, 156-pair dev battery, 2 arms (baseline_narrow_then_wide vs wide_only), all roles + picker on `claude-sonnet-4-6`, `exp34_retrieval_strategy_s46` | NL adoption rule met (neg-gold FP 17->14 paired, commit-acc 0.62->0.67, McNemar p=0.375 not significant). Pooled NL+MT+AL: commit-acc 0.679->0.733, no country regresses -> adopted on accuracy grounds. FP-reduction is NL-specific, not a general property: pooled McNemar p=0.727 (worse than NL-alone), MT zero discordant pairs, AL a small reverse effect (+1 FP, tiny n). Code default flipped `narrow_then_wide`->`wide_only` (D64); `evaluation/runs/exp34_pooled_result.json` and `exp34_full_result.json` (in the `beef-ai-lesswrong-feedback-f15c91` worktree) hold the source numbers. `docs/EXPERIMENTS_FINAL_PROGRAMME.md` |
| EXP-35 | Single-agent self-critique arm (completes the EXP-28 ladder) | registered (2026-07-02), planned; engineering precondition (new pipeline_mode) | 156-pair dev battery, single arm self_verify_s46; controls EXP-28 trio_s46 and researcher_only_s46 | answers "why three agents rather than one self-critiquing agent": same model critiques its own answer under the disprove framing, D35/D37 honesty layer held. If EXP-28 finds researcher_only within noise of trio, this becomes the central exhibit; if trio dominates, it quantifies what adversarial separation buys over self-critique. Characterisation only. Spec (`evaluation/specs/exp35_self_critique.json`) re-pinned to `claude-sonnet-4-6` for all four roles (was stale at `claude-sonnet-5`, fixed independently on the other branch, condition_label corrected to `self_verify_s46`) and pinned `search_strategy: narrow_then_wide` (this branch, 2026-07-13) to match its EXP-28 control across the D64 default flip. Both fixes reconciled on merge. `docs/EXPERIMENTS_FINAL_PROGRAMME.md` |
| EXP-38 | Corroborative vs adversarial verifier framing (frozen-ladder replay) | **DONE (2026-07-16)**: hypothesis supported on the primary endpoint | 150 frozen EXP-11 candidates, 2 arms (disprove re-baseline vs new verifier-corroborate), claude-sonnet-4-6, search-free replay | disprove J 0.41 (sens 0.72, FRR 0.31) vs corroborate J 0.16 (sens 0.32, FRR 0.16): the confirmation-seeking framing collapses the adversarial catch exactly as section 2.5 predicts, in both claim directions. Fresh disprove reproduces the June J=0.41 to two decimals on the D62 transport. Caveats: raw correctness favours corroborate on the 121/29 pass-heavy set (McNemar p=0.20, the R4 trap; J was pre-registered primary), and adversarialism costs 2x the false-rejection rate (0.31 vs 0.16), reported as the trade. 1 candidate excluded (persistent schema failure). Prereg + result `docs/EXPERIMENTS_CORROBORATE.md`; receipts `evaluation/results/exp38_corroborate_ladder.jsonl`. |
| EXP-39 | Language-comprehension probes without DeepL (swap replay + evidence-language contrast) | **Part A DONE (2026-07-16): null after the quality gate**; Part B main-rows pass done, headline pass waits on EXP-36 | Part A: English-evidence subset of the frozen 150, argostranslate en->fr (control) / bg / sq, frozen disprove re-scored per language. Part B: within-country english vs non-english evidence contrast, dashboard match CASE verbatim, dev now + EXP-36 stratum A/B later | replaces DeepL (budget) and dodges the Claude-translates-for-Claude circularity: local OPUS-MT models, versioned, translations frozen to JSONL before any LLM call. Part B on main rows: only NO has mass on both sides so far (english 0.93 vs non-english 0.83 commit-acc, MH OR 2.29, CIs overlap); the powered read comes from the EXP-36 rows post-run. Part A swap replay (n=69): fr control harmless (J 0.38 vs en 0.35, p=1.0); bg within margin; sq fired both pre-registered criteria (beyond-control J drop 0.15, flip McNemar p=0.049) but FAILED the mandated 10-sample quality gate - 3/10 translations degraded, and the clean-English-source split (n=23) shows sq/bg beyond-control +0.07 (under margin) with the whole effect in the mixed-language subset (+0.14). Verdict: no comprehension penalty demonstrated, third independent null (EXP-22, 127-case replay, this); method note - language-ID per snippet part, not concatenated surface. Prereg `docs/EXPERIMENTS_LANGUAGE_PROBE.md`. |
| EXP-36 | Frozen headline run (fresh pre-registration, discards EXP-31) | **DONE (2026-07-16; numbers recomputed 2026-07-20 against the completed run): 1,144/1,144, all 8 countries at 143. Coverage 0.556, commit-acc 0.701 [0.664,0.736], neg-gold FPR 0.255, ECE 0.063. RQ3 stratum A vs B: abstention +0.16 / commit-acc -0.16 / neg-FPR -0.11 (low-resource drives abstention not error). FM-14 committed-evidence audit CLEAN (0 committed pairs cite a blocked source); 7 verifier counter-search hits disclosed as a pre-existing deny-list gap, non-invalidating. Analysis `evaluation/results/exp36_headline.json`, audit `docs/EXP36_LEAKAGE_AUDIT.md`.** | D47 held-out 8 (BA MK ME BG / FI HR SE BE), ~1,144 pairs, eight per-country sub-batches, DIY-only, `claude-sonnet-4-6` all roles + picker (D59), `search_strategy=wide_only` (EXP-34) | replaces `exp31_frozen_headline_v2`. Single configuration, no arms, no adoption rule: the reported headline. Prior held-out exposure (exp21 partial + expC_held_neg_licence) voided and disclosed per D57; EXP-31 itself never dispatched, so it adds no further exposure. All 7 config-freeze gate items DONE except the freeze tag (deliberately last). Coordinator B1-B4 fixed and tested (independently on two branches, reconciled on merge; see gate item 7). Spec `evaluation/specs/exp36_frozen_headline.json`, dry-run clean (8 arms, 1,144 pairs, every knob confirmed in the built command). Resume rule: pair-granularity across interruptions, one frozen config, one run_id. Endpoints balance-aware + three-outcome, stratified by dimension / stratum / assessor decision / shape, D22 staleness band, FM-14 fingerprint audit post-run. Remaining before dispatch: freeze tag, canonical-DB registry row + hygiene, leakage + held-out cache audits. `docs/EXPERIMENTS_EXP36_PREREG.md` |

---

## EXP-1: DIY vs Tavily, adjudicated (done)

**Refreshed 2026-06-02 (diy_vs_tavily_fr_v2), per the pre-registered protocol
(`EXPERIMENTS_PROTOCOL.md`).** Harness: `evaluation/diy_vs_tavily.py`. Results:
`evaluation/results/diy_vs_tavily_20260602_175403.jsonl` (git 533284b). The full
FR non-Quality web-answerable stratum, 90 pairs, judged blind and
position-swapped by Opus, with the deny-list applied pre-fetch to every arm and
evidence normalised to equal passage count and registrable-domain URLs.

Result: DIY 49 wins, 1 tie, 6 Tavily wins, 34 both_fail. On the 55 decided pairs
the DIY win share is 89% (Wilson 95% CI [78%, 95%]), exact sign test p < 1e-4
against parity. DIY leads every dimension (Impact 13/2, Policy 12/2, Portal
24/2). This supersedes the n=18 pilot below and clears the pre-registered
non-inferiority margin decisively.

"Decided" here means the combined two-orientation verdict is diy or tavily (a
non-zero DIY-signed score over the two position-swapped judgements). A
single-orientation `both_fail` scores zero and so is overridden when the other
orientation is decisive; it is not excluded. This affects 10 of the 55 decided
pairs. As a pre-registered sensitivity check, requiring both orientations to be
decisive (dropping those 10) gives 42/45 = 93% (Wilson [82%, 98%]): the
direction and significance are unchanged, so the disclosure is for
completeness, not because the result is fragile.

Caveats (honest): position consistency 81%; the answer-blind robustness check
agrees with the answer-given verdict on only 67% of the 27-pair subsample (9
flips), so the judge is somewhat sensitive to seeing the gold answer. France
only, Tavily basic tier.

Cross-family reliability (done 2026-06-03). The planned Gemini re-judge stayed
dead (zero quota), and Groq's free tier caps tokens per organisation not per
key, so all available Groq keys shared one exhausted daily pool. Mistral Large,
a third independent family, re-judged the same frozen 27-pair subsample
(answer-given, position-swapped, byte-identical evidence; only the judge
changed). Harness: `evaluation/cross_family_backfill.py --judge mistral`;
result: `evaluation/results/cross_family_exp1_mistral.jsonl`. All 27 pairs
judged: raw agreement 78% (21/27), Krippendorff alpha 0.648 (nominal, four
categories). All six disagreements turn on Opus calling `both_fail` (five of
six) where Mistral committed to a provider or a tie; where both judges committed
to a provider they never disagreed (DIY 13, Tavily 3). This rebuts the
same-family self-preference concern, that the Claude judge favours
Claude-extracted DIY evidence. Mistral was position-inconsistent on 6 of 27
pairs, more than Opus, which is reported alongside.

---

Pilot (superseded, n=18 decisive), SPEC D29. Run:
`evaluation/results/diy_vs_tavily_20260601_220315.jsonl`. A blind,
position-swapped Opus judge on 36 dimension-stratified French pairs: DIY 12 wins,
2 ties, 4 losses, 18 both_fail; not worse 78% on the 18 decisive, wins 3:1.
Caveats then: n=18, France only, Tavily basic tier, position consistency 67%.

## EXP-2: Search-knob cost vs quality

SPEC: D31. DIY costs five to eight times the Claude calls of Tavily per pair,
because it runs extraction on our own model (up to five snippet-picks per
search). This tests whether cutting the knobs keeps the quality.

Conditions (hold provider=diy, models, strategy, and the pair set fixed; vary
only the knobs):

| condition_label | queries | results/query |
|---|---|---|
| `diy_full` | 3 | 5 |
| `diy_lean` | 2 | 3 |
| `diy_q3r3` | 3 | 3 |

`diy_q3r3` isolates which knob carries the cost. Metrics per condition:
accuracy against ODMI ground truth (`_MATCH_STATUS_SQL`), and Claude calls /
tokens / cost / mean retry count per pair from `claude_usage_log`.

The confound to watch is retries. A leaner search that fails more often
triggers another full Researcher+Verifier round, so a cheaper per-search
config can cost more per pair. Judge on total calls per pair, not per search.

**EXP-2a (FR subset) — queued.** Run now on a web-answerable French subset.
The agent prompt for this run is in `docs/prompts/run_knob_experiment_fr.md`.

**EXP-2b (low-resource countries) — planned.** Repeat on less well-resourced
countries (see EXP-3 candidates) once the FR result is in. The interesting
question is whether the knob trade-off shifts when web sources are thinner: lean
knobs may hurt more where the answer is hard to find.

Result: pending.

## EXP-3: DIY vs Tavily, multilingual / low-resource (planned)

EXP-1 was France only. France is data-rich and the sources are mostly French
and English. The harder test is countries with thinner open-data webs and
lower-resource languages: Romania, Estonia, Hungary, and similar. This repeats
the adjudicated comparison there.

Blocker: the DB has very few finalised pairs outside France (DE 3, NL 3, RO 2),
so this needs a fresh dispatch for the target countries first. Plan the pairs,
dispatch them, then run the EXP-1 harness on the new set.

Result: pending.

## EXP-4: Brave head-to-head (planned)

Brave is the credit-exhaustion fallback but has never been in an adjudicated
comparison. Add Brave as a third arm so the paradigm is fully characterised
(DIY vs Tavily vs Brave on the same pairs, same judge).

Result: pending.

## EXP-5: Five-provider search A/B (planned)

The parked plan: a paired A/B across five providers, agreed as the June
starting point. Scope and provider list to be confirmed before running.

Result: pending.

## EXP-6: Verifier strategy discrimination (retargeted to Malta)

Pre-registered in `docs/EXPERIMENTS_VERIFIER.md`. Treats each of the four D15
verifier strategies (disprove / negation / steelman / blind) as a binary
classifier over a Researcher candidate answer (pass = accept, fail = reject) and
measures how well each tells a wrong answer from a correct one, per unit of token
cost. Paired design on frozen evidence, so the only between-arm variable is the
system prompt. Primary endpoint Youden's J; secondary MCC, balanced accuracy, the
two error rates with Wilson CIs, per-dimension splits, paired McNemar (Holm), and
a Wilcoxon token-cost comparison.

**Retargeted 2026-06-03 under the new base-rate rule (R4,
`EXPERIMENTS_PROTOCOL.md` section 0).** The first design built its should_fail
class almost entirely from France (20 of 21 natural errors), where the binary gold
is 99% `yes` and a false positive can barely occur. The primary should_fail source
is now Malta (~30 `no`-gold binary questions; the "English official" framing is
oversold per D47, ~half Maltese and in-sample dev), with Netherlands
secondary and the France-dominated natural errors plus the injected label-flips
kept as a robustness arm, reported separately. The earlier partial run on the
France/injected set (committed at 3 of 89, extended to ~40 of 89 in working state)
is superseded as the primary and retained only as robustness data.

Harness: `evaluation/verifier_strategies.py` (resumable; sleeps through Anthropic
rate-limit cooldowns). The strata are now role-based (primary MT, secondary NL,
robustness FR/EE + injection). The primary Youden's J needs the Malta dispatch,
which is now done.

Malta dispatch (done 2026-06-03): the canonical pair set is frozen and committed at
`data/questions/malta_eval_pairs.json` (60 pairs, 30 `no` / 30 `yes`, seed
20260603). The baseline dispatch (provider auto, `condition_label` baseline, no
`experiment_id`, batches `exp6_malta` then `malta_baseline`) finalised all 60:
43 committed yes/no plus 17 honest `inconclusive` abstentions (D37). The last two,
I8-d and PT12, had failed on `search_empty` because their evidence URLs were on
Cloudflare-protected data.gov.mt; they recovered to `inconclusive` once `head_ok`
gained a Playwright fallback for WAF 403s. Balance-aware quality (R4): exact match 32/60 raw, 32/43 on
committed answers; no-gold minority recall (TNR) 0.87 with 3 false positives of 23
committed (I7, I8-b, PT29); yes-gold recall (TPR) 0.60; Youden's J 0.47; mean
commit confidence 0.58. Zero data-leakage in any finalised row. Batch cost ~$4.98.
The natural-error pool for the should_fail arm is now populated.

Three faults surfaced and fixed during the dispatch, none of them quota: a missing
worktree `.env` plus an empty `ANTHROPIC_AUTH_TOKEN` injected by the desktop app
made every LLM call fail with a misleading `APIConnectionError` (fixed in
`agents/tools/llm.py`); the resume path reused failed/`inconclusive` Researcher
rows, stranding 11 pairs at stage 'researching' with no `phase2_final` (fixed in
`scripts/run_coordinator.py` `_find_resumable_researcher`); and `head_ok` marked
Cloudflare-protected data.gov.mt as `url_unreachable`, killing answers grounded
there, which it now clears with a Playwright render on a WAF 403/429/503 (fixed in
`agents/tools/fetch.py`), recovering the final two pairs.

Result: pending (apparatus and Malta natural-error set both ready; the four-arm
judge run has not been executed).

## EXP-8: Cost-side optimisations, Family 1 (planned)

Pre-registered in `EXPERIMENTS_PROTOCOL.md` (section 7). Holds the country, pair
set, and models fixed and varies one cost knob at a time: `baseline`,
`prompt-compressed`, `retrieval-tight`, `cache-hot`, `model-fallback`. Endpoints:
balance-aware accuracy against the Malta majority baseline (R4) and cost per pair
with retries counted (R9). Run on Malta primary, Netherlands secondary.

Prerequisite: the Malta dispatch is done (not quota-gated; 20x plan), so what
remains is a committed `prompt-compressed` prompt version and the
`model-fallback` escalation path. EXP-8 is not in the current pass (EXP-9 is the
running model experiment). The apparatus is built (2026-06-03): the compressed Researcher prompt
(`--prompt-variant compressed`, its own `prompt_versions` row, baseline
untouched), the `model-fallback` escalation (`--researcher-escalation-model` /
`--verifier-escalation-model`), and the cold-cache switch (`--no-cache`) for the
lean-vs-`cache-hot` split. The Malta baseline dispatch is now done (60/60 over the
committed pair list), so the condition-tagged runs can proceed over the same set.

Result: pending.

## EXP-9: Model variants, Family 3 (running)

Pre-registered in `EXPERIMENTS_PROTOCOL.md` (section 7). Compares `model-haiku`,
`model-sonnet` (baseline), `model-opus`, `model-tiered` (Haiku draft, Sonnet
verify, Opus adjudicate), and `model-mistral` on the same Malta pairs. The
confirmatory comparison is tiered vs all-Sonnet on accuracy and cost; the
accuracy-cost surface is the headline figure. Run on Malta primary, Netherlands
secondary.

**Mistral arm (added 2026-06-09).** A fifth, cross-family arm runs the whole
swarm on `mistral-large-latest`. It tests how much of the accuracy is the
pipeline versus Claude specifically: if Mistral lands near Sonnet, the design
carries the result, not the model family. Enabled by a lean provider branch in
`call_for_structured` (structured output is prompt-based JSON, so no separate
agent stack was needed). The DIY snippet-picker stays on Claude for every arm,
so it is a pinned constant, not part of the variant. Mistral is off the Claude
budget; its cost is a real-money figure. Watch for a Mistral monthly-quota stop
on this arm (it runs last, so the four Claude arms complete regardless).

**Model ids.** Haiku `claude-haiku-4-5-20251001`, Sonnet `claude-sonnet-4-6`,
Opus `claude-opus-4-6` (confirmed served by the proxy, matches the
pre-registration; `claude-opus-4-8` is not served). Mistral
`mistral-large-latest`.

**Dispatch.** `scripts/run_exp9_model_variants.sh`, the five arms sequentially
over the canonical Malta 60. One variable (the model); provider diy, cold cache,
disprove, 5 results, 3 retries, full prompt, unchained all pinned. Each arm
tagged `experiment_id=model_variants_mt` and a per-arm `condition_label`; the
fresh dispatch writes new rows alongside the baseline (canonical-row dedup keeps
the analysis honest).

**Caveat (contention).** This run overlaps the Norway development sweep, so the
wall-clock latency endpoint may be inflated by machine contention. The headline
token-cost endpoint is token-based and unaffected; arms run sequentially under
roughly constant background load, so the relative accuracy comparison holds.

Result: pending (running 2026-06-09).

## EXP-10: Malta failure-mode audit + confidence-floor recovery (planned)

Pre-registered in `docs/EXPERIMENTS_MALTA_FAILURES.md`. Looks at why Malta swarm
answers diverge from ODMI ground truth, to find the fixable bottleneck. The full
baseline set is now available (60 of 60 finalised, batches `exp6_malta` +
`malta_baseline`). The pattern from the earlier 13-pair pilot holds: losses are
dominated by recall, not precision. Across all 60, 17 pairs abstain (`inconclusive`)
and 27 of 60 commit below the D37 0.65 floor; yes-gold recall is 0.60 against
no-gold recall 0.87, so the swarm is far more willing to confirm a `no` than a
`yes` on sparse Malta evidence. False positives are rare but present: 3 of 23
committed no-gold answers (I7, I8-b, PT29), the visible-error class Malta exists to
expose. The retrieval ceiling (exhausted Tavily, DIY-only, self-report / deny-list
questions) is the single largest driver; the `data.gov.mt` Cloudflare 403 part of
it is now mitigated by the `head_ok` Playwright fallback, leaving the self-report
and thin-SERP cases as the residual bottleneck.

Phase A codes every Malta non-match to one cause from a pre-specified taxonomy
(fetch 4xx/5xx, no source, substring-gate failure, below-floor abstention, wrong
answer, near-miss band, self-report/deny-list ceiling, stale ground truth),
deterministically where the DB signal is unambiguous and with an Opus judge over
frozen evidence only for the genuine-error vs stale-gold residual. Phase B is a
free confidence-floor sweep (0.65 / 0.55 / 0.50) replayed on the stored Researcher
confidences, reporting the recovery-precision trade-off and adopting a lower floor
only under a pre-set precision and false-positive bound. Malta being base-rate
balanced (R4) is what makes the false-positive check meaningful.

Harness: `evaluation/malta_failure_audit.py` (built). Phase A runs incrementally
on whatever Malta pairs exist; the floor sweep needs no quota. Tavily-independent.

Result (2026-06-23, MT n=60, free replay; `evaluation/results/malta_failure_audit_MT.jsonl`).
Match status 32 match / 17 abstain / 11 differ.

Phase A taxonomy of the 28 non-match pairs:

| cause | class | n | share [95% CI] |
|---|---|---|---|
| wrong_answer | error | 11 | 0.18 [0.11, 0.30] |
| fetch_4xx_5xx | fixable | 7 | 0.12 [0.06, 0.22] |
| below_floor | fixable | 6 | 0.10 [0.05, 0.20] |
| substring_gate | fixable | 2 | 0.03 [0.01, 0.11] |
| abstain_other | fixable | 2 | 0.03 [0.01, 0.11] |

17 fixable, 11 genuine error, **0 structural**. The largest fixable bucket is
retrieval-side (fetch 4xx/5xx), reinforcing that the open gains are in
retrieval, not reasoning wiring.

Phase B confidence-floor sweep:

| floor | committed | correct | recovered | rec-correct | rec-FP | rec-precision | neg-FPR |
|---|---|---|---|---|---|---|---|
| 0.65 | 44 | 32 | 0 | 0 | 0 | n/a | 0.13 |
| 0.55 | 47 | 34 | 3 | 2 | 1 | 0.67 | 0.13 |
| 0.50 | 52 | 38 | 8 | 6 | 2 | 0.75 | 0.13 |

**Verdict: keep the 0.65 floor.** The pre-registered rule (adopt a lower floor
only if recovered-answer precision >= 0.80 and negative-class FPR rises by no
more than 0.05) rejects both lower settings: lowering to 0.50 recovers 6 correct
answers but admits 2 wrong (0.75 precision, under the 0.80 bar). One honest
nuance: the negative-class false-positive rate is flat at 0.13 across all three
floors, so the floor is not what drives false positives, and the 0.50 case
(6 correct for 2 wrong, no FPR rise) is closer than the binary verdict suggests.
The pre-registered bar holds it at 0.65; a future run could revisit the 0.80
precision threshold itself. Replay faithfulness note: 1 abstained pair carries a
candidate at or above baseline, flagged in the harness output for a later look.
MT only (base-rate balanced, the point of choosing it); single stored set.

All-country extension (2026-06-23, free replay; `evaluation/floor_sweep_all.py`,
`evaluation/results/floor_sweep_all.jsonl`). n=60 on one country is too thin to
gate every commit, so the sweep was pooled over every country with stored data:
production rows (`experiment_id IS NULL`) for MT, NO, FR, EE, DE, RO, plus NL's
production-config baseline (the EXP-16 `standard` arm) for its 26 negative golds.
Pooled n = 360 across 7 countries, 67 negative golds (6x the Malta sample).

| floor | committed | correct | recovered | rec-correct | rec-FP | rec-precision | neg-FPR |
|---|---|---|---|---|---|---|---|
| 0.65 | 295 | 248 | 0 | 0 | 0 | n/a | 0.37 |
| 0.55 | 314 | 261 | 19 | 13 | 6 | 0.68 | 0.39 |
| 0.50 | 324 | 270 | 29 | 22 | 7 | 0.76 | 0.39 |

**Verdict holds: keep 0.65.** Recovered-answer precision at 0.50 is 0.76 pooled,
almost identical to Malta's 0.75, so the result is consistent across a much
larger sample, not a Malta artefact; it sits just under the pre-registered 0.80
bar. The negative-class false-positive rate barely moves on lowering (0.37 ->
0.39, inside the 0.05 bound), confirming the floor is a recall dial, not the
false-positive control. Per-country recommended floors: the three balanced
countries MT / NO / NL all return 0.65; only the yes-skewed FR and EE lean to
0.55, where lowering recovers only correct answers because they carry almost no
negative golds to get wrong (a base-rate artefact, not evidence for a lower
production floor). Honest scope: NL enters via a production-config experiment
baseline rather than a true `experiment_id IS NULL` run, and the negative-gold
mass is still MT + NL + NO; FR / EE / DE / RO add recovery-precision evidence but
little negative-class signal. The decision is now supported at n=360, not n=60.

## EXP-11: Verifier redesign evaluation (planned)

Pre-registered and operationalised in `docs/EXPERIMENTS_VERIFIER_REDESIGN.md`,
which is written so a fresh agent can run the whole programme from that file
alone. The proposals under test (tristate verdict with deterministically gated
extremes, symmetric burden via confirmation probes, absence commit policy,
quote-integrity matcher v2, band recompute, confidence demotion) and the Malta
diagnosis behind them are in `docs/VERIFIER_REDESIGN.md`.

Three gated stages: stage 0 is free offline replays that ship the matcher fix
and freeze the policy knobs; stage 1 is a frozen-evidence classifier ladder
(arms: disprove incumbent, tristate, tristate+probes, blind; gating applied as
analysis columns) selecting on MT+NO dev strata and confirming once on NL,
with the FR augmented flips as robustness; stage 2 is an end-to-end paired
dispatch on Sweden (untouched, no-share 0.22) deciding D45. Primary endpoint
Youden's J (refute binarised as fail); McNemar exact, Holm over the dev
ladder; adoption rules fixed before any run.

Interaction note: EXP-10 Phase B sweeps the D37 floor on the same stored
confidences that EXP-11 stage 0 uses to freeze the absence ceiling. Whichever
runs second inherits the other's adopted value; do not run the two knob
decisions independently.

Result: pending.

## EXP-12 / EXP-13: verifier evidence and verdict wiring (planned)

Pre-registered together in `docs/EXPERIMENTS_VERIFIER_EVIDENCE.md` (2026-06-11),
the successor programme to EXP-11's null. EXP-11 left two questions: the
evidence (the same disprove prompt scores J=0.41 on clean frozen evidence but
discriminated barely at all in the Malta production trail) and the wiring (what
a `fail` should be allowed to do).

EXP-12: (a) a free matched-pair diagnostic on stored data testing whether the
production-vs-frozen gap is an evidence effect on identical items (H1, gates
the rest); (b) an evidence ladder over the 150 frozen dev candidates, prompt
pinned to disprove v3, varying only the evidence block: researcher-snippets-only
floor, the frozen adversarial block, plus probes, plus the cited source page,
plus search breadth. Phase 1 reuses the stage 1 freeze verbatim, so it costs
450 main calls and no new searches.

EXP-13: (a) a free deterministic replay over the stored MT+NO trails comparing
four wirings (gate, veto-hard on the substring check only, confidence-shaded,
advisory) with a simulator-fidelity gate (must reproduce production outcomes on
at least 95% of pairs) and a no-verifier reference column that quantifies the
Verifier's contribution without proposing its removal; (b) the programme's only
dispatch, a two-arm paired end-to-end on Sweden, production vs the bundled
champion. Adoption rule fixed in the pre-registration; floor held at 0.65
(coordinate with EXP-10 Phase B).

Result: pending.

## EXP-7: Retry chaining / evidence accumulation (code built, pre-registered)

Pre-registered in `docs/EXPERIMENTS_CHAINING.md` under the universal rules
(`EXPERIMENTS_PROTOCOL.md` section 0). The chained code path is **built and
committed**, gated behind `--chained` (default off), so production and the
EXP-8/9 baseline are byte-identical to the independent-retry loop.

Up to eight calls run per pair (four Researcher, four Verifier across the retry
budget), but today they are independent shots. The Verifier searches the web
every round and often finds real evidence, then the loop keeps only its verdict
and bins the evidence. The Researcher on retry 3 does not know what the Verifier
turned up on rounds 1 and 2. The calls are spent, the findings are thrown away.
SPEC D33 carries queries and the rejection reason forward, D34 persists snippets,
D37 applies the commit floor, but no round sees what the earlier rounds gathered.

What the `--chained` arm now does (all flag-gated, default off):
- Feeds the Verifier's counter-evidence (its `counter_evidence_quote` /
  `counter_source_url`) back into the `ResearcherInput` on retry, not just the
  verdict and a suggested query (`VerifierFeedback` extended).
- Accumulates an evidence corpus across rounds (the Researcher's and Verifier's
  snippets, already persisted under D34; new `EvidenceItem` model) and carries it
  forward via `ResearcherInput.prior_evidence`, so each round sees everything
  found so far. The coordinator merges with de-dup and a 40-item cap.
- Has the Adjudicator synthesise over the whole corpus
  (`AdjudicatorInput.evidence_corpus`), committing only above the D37 floor and
  abstaining honestly otherwise. The floor and abstention rules are unchanged
  across both arms; the treatment only changes what each call sees.

Carried evidence and its using-instruction travel in the per-call user message,
not the system prompt, so `prompt_versions` rows are identical across arms and an
empty corpus renders byte-for-byte as the pre-EXP-7 prompt. Offline tests in
`tests/test_chained_evidence.py` pin all three: the chained path carries evidence
forward, the baseline path is byte-identical, and the flag defaults off.

Hypothesis: chaining recovers more correct answers per call than independent
retries, without raising the false-positive rate.

Conditions: `baseline` (current independent retries, D33 / D37) vs `chained`.
Endpoints, read balance-aware per R4: recovery (balanced accuracy + per-class
rates against ground truth), false-positive rate (committed but wrong, the
co-primary), abstention rate, and calls per resolved pair. Paired McNemar (×2)
and Wilcoxon; one confirmatory joint claim (balanced-accuracy non-decrease at a
non-increased false-positive rate). Full design in `EXPERIMENTS_CHAINING.md`.

Where to run: Malta primary (~30 `no`-gold binary questions so a false `yes` is
visible; "English official" is oversold per D47, ~half Maltese, in-sample dev),
Netherlands secondary. France is barred (99% `yes`,
recovery indistinguishable from majority-class guessing, the D35 / D37 / R4
lesson). The lower-resource `no`-heavy countries (BA, MK, ME, BG, IS) are deferred
to a follow-on so a poor result there is not blamed on language.

Prerequisite: the Malta dispatch is done (60/60, shared with EXP-6/8/9), so the
`no`-gold candidates now exist and the run is no longer quota-gated (20x plan).
The code and pre-registration are done.

Status: code built and committed (flag-gated, default off), pre-registered. Run
not started, pending the Malta dispatch and quota.

Result: pending.

---

# Pipeline optimisation programme (2026-06-22)

The verifier programme (EXP-11/12/13) and the stack-attribution pass closed with
a clear picture: the verdict logic is not the lever, the evidence channel and the
decision step are. Brave and Tavily are retired (D43, DIY-only), so the remaining
work is optimising the search and reasoning pipelines, not provider selection.
EXP-14 to EXP-17 below operationalise that. None has been run; each needs a full
pre-registration (endpoints, adoption rule, strata, held-out country) before any
dispatch, under the universal rules in `EXPERIMENTS_PROTOCOL.md` section 0.

**Datasets (per SPEC D47).** The evaluation redesign (D47, supersedes the D42
matrix) fixes a five-country in-sample development set and an eight-country
pre-registered held-out eval set; these experiments draw from the development
side. The development workhorse is the **Netherlands** (`nl_eval_pairs.json`,
binary 93 yes / 26 no, 22% no-share, finalised with stored trails), not Malta:
Malta's better paper no-share (31%) sits behind a half-Maltese (low-resource)
estate, so a miss there can be the language channel rather than the pipeline.
**Norway** stored trails serve the free replays, **Malta** trails too but
caveated (in-sample under D47, language confound). **France non-Quality 90**
(web-answerable, the EXP-1 set) is the retrieval-funnel set, because the funnel
only bites where the answer is on the open web and Malta's abstention ceiling is
structural. **Albania** (added to the dev set in D47) is the thin-web
low-resource regime for tuning the hard case. Every arm of every experiment
develops and confirms on the dev set only; the eight held-out countries
(BA / MK / ME / BG / FI / HR / SE / BE) are frozen and touched exactly once, at
the final headline run, on a committed pipeline (D47 freeze protocol, the strict
"never touch" rule decided 2026-06-22).

## EXP-14: Verifier search policy (never / elective / always)

The verifier programme's largest measured effect is that the Verifier's *own live
counter-search poisons its evidence*: the same `disprove` prompt scores Youden's
J = 0.10 on production (live-search) evidence and J = 0.42 with no search at all
(EXP-12a/b). The production recipe was never tested end-to-end against a
no-search verifier. EXP-14 does that, and adds the elective middle.

Three arms, one variable (what the Verifier is allowed to search):

| arm | the Verifier ... |
|---|---|
| `never` | reasons over the Researcher's evidence only; no counter-search (the EXP-12b E5 floor, live) |
| `elective` | is given counter-search as a tool it may call after reading the Researcher's evidence, with a stated reason; it chooses per pair |
| `always` | the current production behaviour (D36/D43 clean DIY counter-search every round) |

Rationale for the elective arm. EXP-12b found a direction split that a fixed rule
could not bank: counter-search and probes help absence (`no`) claims (no-claims J
E5 0.35 -> E0 0.45 -> E1 0.50) and hurt presence (`yes`) claims (yes-claims 0.37
-> E1 0.29). The shape-conditional routing rule (EXP-12c) only reached +0.02
in-sample because the routing decision was made before the evidence was read. An
agent that *decides to search after reading* can condition on the actual evidence
state (is this a presence claim the Researcher already grounded, or an absence
claim that needs disconfirmation), which the fixed rule cannot. This is a
different mechanism, not a re-run of EXP-12c.

Endpoints: in-loop verdict J split by claim direction (absence vs presence),
false-rejection rate (must not exceed the `always` arm), recovery and
false-positive rate end-to-end, and on the `elective` arm the tool-call rate (how
often the Verifier elects to search, and whether it elects correctly by
direction). Where to run: Netherlands for development (Dutch is well-resourced,
so a miss is the pipeline's doing, not the language channel, which is the point
Malta could not honour; 26 negative golds carry the absence-claim direction), with
Albania as the thin-web low-resource cross-check. No held-out country is touched;
the winning policy is confirmed only at the final frozen headline run (D47). The
`never` arm doubles as the live confirmation owed from verifier open question 4.

Result (2026-06-23, NL, never vs always; the elective arm was stubbed, not run).
Canonical rows per pair, binary yes/no gold, n = 51. Harness
`evaluation/analyze_phase1.py exp14_verifier_search_nl`.

| arm | commit acc [95% CI] | coverage | yes-rec | no-rec | FP (no-gold) | GBP/pair |
|---|---|---|---|---|---|---|
| `always` (production) | 0.59 [0.43, 0.72] | 0.80 | 0.84 | 0.12 | 15 | 0.057 |
| `never` | 0.61 [0.47, 0.74] | 0.86 | 0.88 | 0.19 | 16 | 0.045 |

Paired McNemar on the 38 pairs both arms committed: 0 always-only-right, 2
never-only-right, exact p = 0.50, so no end-to-end accuracy difference. `never`
is cheaper and commits more, but its no-gold false-positive rate is higher
(0.62 vs 0.58), which fails the pre-registered rule (never may not raise the
false-positive rate). **Verdict: keep `always`.**

This is the live end-to-end null behind the EXP-12 in-loop finding, and it
reconciles cleanly. EXP-12 scored the Verifier's verdict as a classifier on
frozen evidence, where live counter-search hurt (J 0.10 vs 0.42). End to end on
balanced NL, removing that search does not lift commit accuracy: the
counter-search's working contribution is the abstention it triggers on thin
evidence, which suppresses a few false positives on `no`-gold pairs. The
clean-evidence J advantage does not translate into an end-to-end win, and the
live search earns its keep on the false-positive margin, barely. Honest limits:
small n, single dev run, CIs wide and overlapping; the `always` arm mixes prior
and re-run pairs (idempotent resume kept the prior finalisations) while `never`
is prior-session data; descriptive, not powered. The elective arm (the new
mechanism, decide-to-search-after-reading) is still owed.

## EXP-15: Adjudicator standalone ablation, under the EXP-14 verifier

EXP-13a measured removing the *whole* verify-plus-adjudicate layer (cost 27
correct, saved 16 wrong). The Adjudicator on its own has never been isolated:
verifier open question 1, flagged there as the cleanest unanswered question in
the architecture. EXP-15 keeps the production loop but abstains at retry
exhaustion instead of adjudicating, so the delta is the Adjudicator's own
contribution.

The twist that makes this worth doing now rather than as a footnote to EXP-13a:
once EXP-14 changes what the Verifier feeds forward (no live-search noise, or
elective), the Adjudicator is reasoning over a different, cleaner corpus. The
question "does the Adjudicator still earn its keep if the Verifier brings no new
evidence" (raised directly in this session) is only answerable under the new
regime. Run the ablation under whichever EXP-14 arm wins, not under the retired
always-search verifier.

Free replay first (same machinery as EXP-13a `W-none`, over stored NL and NO
trails; Malta trails usable but caveated for the language confound), promoted to a
live dispatch on a dev country (NL/AL) only if the replay shows a non-trivial
Adjudicator contribution that the replay cannot settle. No held-out country is run
pre-freeze. Endpoint: match / wrong / abstain
attributable to the Adjudicator alone, balance-aware (R4).

Result: pending (design only). **Superseded 2026-07-01: the EXP-28
`no_adjudicator_s5` arm runs this design live** (production verifier regime,
since EXP-14 retained `always`), as part of the architecture ablation ladder.
See EXP-28 below.

## EXP-16: Adjudicator free candidate selection

The single biggest lever found in the stack-attribution pass is candidate
selection: an oracle that committed the gold-correct candidate the Researcher
already generated would score 74% on Malta against the observed 44%. The answer
is usually in hand and the pipeline abstains on it. Confidence ranking does not
reach it (rec 3, tested, strictly worse on the balanced set: the correct Malta
answers are low-confidence). So the selector has to reason over evidence, not read
a number.

Today the Adjudicator's verdict taxonomy (`researcher_correct` / `verifier_correct`
/ `neither` / `escalate_human`) defines `researcher_correct` as the Researcher's
*final* answer, and only reaches an earlier attempt's answer through the `neither`
escape hatch. EXP-16 revises the taxonomy and prompt so the Adjudicator can
explicitly commit any of the up-to-four Researcher attempts' answers, choosing on
the evidence each attempt gathered. This is the evidence-based selector rec 3
pointed to (the Adjudicator already approximates it; this lets it select cleanly).

Endpoint: recovery against the oracle headroom (how much of the 74-44 gap closes)
at a held false-positive bound, Netherlands primary because its binary gold is
balanced enough (22% no) for a wrong commit to be visible without Malta's
language confound; FR as the easy high-confidence tail check (confidence ranking
gained +10 there, so the new selector must not regress it). Free replay over
stored multi-attempt trails is possible for a first read before any dispatch. The
oracle 74/44 headroom figure is from the Malta stored data; re-derive it on NL
before adopting any number as the target.

Result (2026-06-23, NL, standard vs free). Canonical rows per pair, binary
yes/no gold, n = 51. Harness `evaluation/analyze_phase1.py
exp16_adjudicator_selection_nl`.

| arm | commit acc [95% CI] | coverage | yes-rec | no-rec | FP (no-gold) | GBP/pair |
|---|---|---|---|---|---|---|
| `standard` (production) | 0.58 [0.43, 0.71] | 0.88 | 0.84 | 0.19 | 18 | 0.051 |
| `free` (may commit any attempt) | 0.57 [0.42, 0.70] | 0.86 | 0.88 | 0.12 | 17 | 0.054 |

Paired McNemar on the 40 pairs both committed: 1 vs 1, exact p = 1.00.
**Verdict: keep `standard`** (NULL). `free` did exercise the new capability,
committing a non-final attempt via `attempt_correct` on 16 of its 52 pairs, so
the arm was live, not inert. But the picks bought nothing: commit accuracy is a
hair lower (0.57 vs 0.58), false positives and cost essentially unchanged.

The reading matters for the programme. The selection headroom is real (on NL
candidate recall 0.63-0.67 sits above commit accuracy ~0.58, a ~10-point
ceiling; on Malta the oracle gap was 74/44). But giving the Adjudicator free
choice does not bank it: handed the freedom, it cannot reliably tell which
earlier attempt holds the correct answer from the evidence as presented. This
echoes the rec-3 confidence-ranking failure (the correct earlier answers are not
the high-confidence ones). The ceiling is not closable by widening the
Adjudicator's choice set alone; it needs a better per-attempt signal than the
evidence already carries. Honest limits: small n, single dev run, overlapping
CIs, NL only (the FR high-confidence tail check is still owed).

## EXP-17: Search-funnel optimisation family

The DIY retrieval funnel is lossy at three points, and 24% of useful citations sit
at rank >= 5 while runs average only 5.1 snippets, so the tail does real work and
the funnel may be discarding the answer:

- cleaned page text capped at 16,000 chars before the LLM snippet-picker
  (`snippet_picker.py`);
- the picker keeps at most 3 chunks of <= 500 chars and drops any URL it picks
  nothing from (`search_diy.py`);
- the prompt formatter truncates each surviving snippet to 600 chars
  (`search.py::format_for_prompt`).

Three arms, each measured on candidate recall (does a gold-correct answer appear
in any Researcher attempt) so retrieval is judged clean of the selection ceiling
EXP-16 attacks:

| arm | varies |
|---|---|
| (a) picker fidelity | current picker vs raw trafilatura chunks (no LLM pick) vs a higher chunk count / cap |
| (b) breadth + rank depth (folds in EXP-2a) | results/query 5 -> 8/10, queries 3 -> 4, vs the lean 2x3 |
| (c) truncation sweep | `max_chars_per_snippet` 600 -> 1200 -> full |

The stack-attribution pass pre-registered the prediction that the lean arm of (b)
loses accuracy on hard countries (rec 5: do not cut breadth, widen it). Cost per
pair with retries counted (R9) is the secondary endpoint, since a leaner search
that fails more often triggers another full round (the EXP-2 confound). France
non-Quality 90 primary (web-answerable, so candidate recall actually responds to
funnel changes; Malta's abstention ceiling is structural and would mask the
effect); repeat on a thin-web country once the FR read is in.

Result, arm (a) picker fidelity (2026-06-23, NL not FR, picker_on vs picker_off).
Canonical rows per pair, binary yes/no gold, n = 50. Harness
`evaluation/analyze_phase1.py exp17_picker_nl`.

| arm | cand recall | commit acc [95% CI] | coverage | FP (no-gold) | GBP/pair |
|---|---|---|---|---|---|
| `picker_on` (production) | 0.70 | 0.59 [0.44, 0.72] | 0.92 | 18 | 0.049 |
| `picker_off` (raw page-text head) | 0.72 | 0.66 [0.49, 0.79] | 0.70 | 12 | 0.077 |

Paired McNemar on the 34 pairs both committed: 1 vs 1, exact p = 1.00.
**Verdict: keep `picker_on`** (the rule needed `picker_off` non-inferior at
*lower* cost; it is not cheaper). But the two hypotheses behind cutting the
picker are both refuted:

- **It does not bin the answer.** Candidate recall is the same with and without
  it (0.70 vs 0.72), so the gold answer reaches the Researcher equally either
  way. The 16% selection headroom is not the picker discarding the
  answer-bearing chunk.
- **It is not a wasteful LLM call.** Removing it *raised* cost by ~57% (GBP
  0.049 to 0.077). Feeding raw page-text heads instead of LLM-selected snippets
  enlarges the Researcher's context and, because coverage drops sharply (0.70 vs
  0.92, the arm abstains far more), triggers more retries. The picker pays for
  itself by compressing context and lifting coverage.

The real shape is a coverage / precision trade, not a free win: `picker_off`
commits less often but is more accurate and lower-FP when it does (0.66 acc, 12
FP), `picker_on` commits almost everything at lower precision. Neither dominates,
and at n = 50 the accuracy gap sits inside overlapping CIs. Single dev run, NL
only (the design's FR candidate-recall read is still owed); descriptive.

## EXP-25 / EXP-27: entailment and argue-the-opposite commit gates (done, NULL/harmful)

The confidence deep dive (`docs/CONFIDENCE_FRAMEWORK_DEEPDIVE.md`) showed
`answer_confidence` is a near-chance correctness ranker (AUROC 0.55) whose signal
flips sign within the negative class (within-negative AUROC 0.17): the swarm's
most confident `no`-gold commits are its most often wrong. EXP-25 and EXP-27 test
the two pre-registered gates meant to fix that by conditioning on evidence rather
than the label. Pre-registered in the `experiments` table as
`exp25_entailment_gate` / `exp27_argue_opposite`; design in the deep dive
section 6.

Both are frozen-evidence replays over one shared scoring pass: for each NL
committed binary pair, a single production-Sonnet (`claude-sonnet-4-6`)
Verifier-side call scores how strongly the cited evidence establishes the
proposed label (`entailment_for`) and the opposite (`entailment_against`). The
two experiments are decision rules on those scores, each compared against the
production commit (the 0.65 floor). Both can only turn a commit into an
abstention, never flip a label. Deviation from the deep dive's pre-registration,
recorded per R1: the scorer is production Sonnet, not the Opus named when Sonnet
quota was exhausted; this removes a model confound and matches the production
Verifier. `evaluation/confidence_gates.py`.

Result (2026-06-25, NL, n = 50 committed pairs, 25 committed negative golds).

| arm | commit acc | abstain | neg-gold FP rate [95% CI] | Youden J | adopt |
|---|---|---|---|---|---|
| baseline (`answer_confidence` >= 0.65) | 0.62 | 0% | 0.76 [0.57, 0.88] (19/25) | +0.24 | — |
| EXP-25 `entailment_for` >= 0.70 | 0.54 | 30% | **1.00** [0.81, 1.00] (16/16) | +0.00 | no |
| EXP-27 margin (for - against) >= 0.25 | 0.60 | 14% | 0.85 [0.64, 0.95] (17/20) | +0.15 | no |

**Verdict: both NULL, and in fact harmful.** Neither gate clears the adoption bar
(FP rate drop >= 15pp, no balanced-accuracy loss, abstention rise <= 10pp); both
move every term the wrong way. The entailment gate *raises* the negative-gold FP
rate from 0.76 to 1.00 and halves Youden's J, because the correct `no` commits
are the low-entailment ones (thin / absence evidence) and abstain first, while the
confident false positives carry high entailment and sail through. Paired McNemar
on the negative golds: EXP-25 caught 3 of 19 FPs (p = 0.25), EXP-27 caught 2
(p = 0.50), 0 of them the high-confidence (>= 0.80) FPs the check was designed for.

This is the within-negative sign-flip made operational and confirmed on the
production model. The mechanism is the one the NL false-positive audit found
(`evaluation/nl_fp_audit.py` + `nl_fp_audit_adversarial.py`): the NL FPs are
well-evidenced loose-`yes` answers in which the open-web evidence genuinely
supports a `yes` reading (scored FP `entailment_for` 0.74 vs correct 0.68; margin
+0.69 vs +0.59 — the FPs look *more* like supported `yes` answers than the correct
commits do). A charitable audit pass calls only 1-2 of 22 a genuine swarm error;
an adversarial advocate pass (told to argue ODMI is wrong) vindicates the swarm on
0 of 22 but rates 11 clear over-reads and 11 ambiguous, so the genuine-error rate
brackets ~5% to ~50% by framing. Either way the disagreement is a strict-vs-loose
question reading against a self-report gold, which no evidence-grounded gate can
arbitrate. No
evidence-grounded gate can separate a well-evidenced `yes` from a gold `no` that
encodes the country's unpublished self-report. The correct response is the
`decision`-stratified reporting (D22; Analytics page self-report split) and the
D22 staleness adjudication of `confirm`-gold disagreements, not a better commit
gate.

Honest limits: underpowered by construction — deduped to one row per question, NL
holds only 25 committed negative golds (the deep dive's 266 were non-independent
pooled-across-arms rows), so the McNemar tests are not powered for a small true
effect; the direction and the mechanism, not the p-values, carry the result.
EXP-26 (self-consistency, 5x cost) and EXP-30 (decomposed score, renumbered from
EXP-28 on 2026-07-01; spends the frozen held-out measurement) are held: same
target, same null mechanism, and EXP-30 must wait for a config lock.


## EXP-28 / EXP-29: architecture ablation ladder + model contrast (running, 2026-07-01 overnight)

Full pre-registration in `docs/EXPERIMENTS_ARCH_ABLATION.md`; design summary on
the board above. Dispatched via the orchestrator
(`evaluation/runs/exp28_arch_ablation_20260701/`), arms sequential:
trio_s5 -> no_adjudicator_s5 -> researcher_only_s5 -> trio_s46.

Run notes (R12):
- CLIProxyAPI was restarted before dispatch to expose `claude-sonnet-5`; the
  restarted proxy drops the API `system` param, so agent instructions moved to
  the user turn for every arm (D55). All within-night comparisons share the
  new transport.
- Four early trio_s5 pairs failed with total Verifier schema collapse before
  the adaptive max_tokens retry landed (Claude 5 thinking blocks exhausting
  the Verifier's 200/240-token budgets); their `phase2_final` rows were
  deleted so the resume re-runs them on fixed code.

Result: pending (analysis morning of 2026-07-02).

## EXP-41: run-to-run stability, and the repair of the §4.2 ablation ladder (queued, pre-registered 2026-07-21)

Full pre-registration in `docs/EXPERIMENTS_RUN_STABILITY.md`; decision D65.
Registry ids `exp41_cooperative_rerun`, `exp41_stability_rep1/2/3`. Specs from
`scripts/gen_exp41_specs.py`. **Not dispatched: awaiting Benjy's review.**

**Why.** Two problems on one battery, so one campaign.

1. The EXP-40 cooperative arm has no row-level record in any of the 46
   `odmi.db` copies on disk, and no `experiments` registry row anywhere. The
   only artefact is an aggregate JSON.
   `evaluation/exp40_analysis.py --db data/odmi.db` returns n=0 for all four
   arms and prints `McNemar p=1.000`, the same p-value the dissertation
   reports, so the documented reproduction path yields a plausible null from
   an empty database. §4.2's primary contrast sits entirely in that arm. The
   other three arms reproduce the published table exactly, but only from
   `data/odmi.exp36-dispatch.db`.
2. §4.7 leaves the second Reproducibility condition of §2.2 open (evidence
   that a repeat run returns the same answers), and Table 3.1 has no
   Reproducibility row.

**Design.** 624 live pairs over the 156-pair dev battery (MT 60 + NL 52 + AL
44, 78 negative golds). Three fresh replicates of the incumbent trio plus one
live cooperative arm. Replicate 1 doubles as the live trio arm of the §4.2
ladder, so every arm in that table comes from one campaign under one frozen
configuration instead of one replayed and one exported. `no_adjudicator` and
`researcher_only` stay decision-layer replays off replicate 1 and cost nothing.

**Endpoints.** Three-way outcome unanimity with Fleiss' kappa; per-run marginal
commit rate and spread; label agreement restricted to unanimously committed
pairs; both decomposed by gold class; and the share of unanimously committed
pairs citing more than one distinct source URL across the runs. The last is the
result the campaign is for: high URL divergence with high answer agreement is
direct evidence for the §2.2 claim about independent evidence paths, and the
converse is reportable.

**Pre-registered bars.** Outcome unanimity ≥ 0.80 and κ ≥ 0.60 (predicted to
miss); commit-rate range ≤ 0.10; label agreement ≥ 0.90 and κ ≥ 0.70 (predicted
to clear). The predicted miss follows from the pile-up at the D37 floor: of 81
committed exp34 `wide_only` pairs, 19 sit at exactly 0.65.

**Order.** Import exp34 into canonical (free) → cooperative arm → replicate 1 →
replicates 2 and 3. If the calendar cuts it short, the repair goes first. If
cost bites, cut the sample to ~100 pairs before cutting a replicate.

**Tooling added.** `scripts/purge_search_cache.py` (archive-then-purge, run
before every dispatch: `--no-cache` disables cache reads but not writes, so a
single purge does not survive run 1, and the existing `purge_heldout_cache.py`
clears only the held-out eight), `scripts/gen_exp41_specs.py`,
`scripts/register_exp41.py`, `tests/test_exp41_prereg.py` (14 pass).

**Result:** pending.
