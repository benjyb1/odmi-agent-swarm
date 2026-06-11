# Stack attribution: how each element of Researcher / Verifier / Adjudicator affects accuracy

Created 2026-06-11. This file records (1) the attribution method that measures
each pipeline element's contribution from production logs, (2) the hypotheses
that fall out of the attribution, (3) one experiment per hypothesis with its
confound controls, and (4) results as they land. It follows the universal rules
in `EXPERIMENTS_PROTOCOL.md` section 0. Harnesses:
`evaluation/stack_attribution.py`, `evaluation/verifier_counterfactual.py`,
`evaluation/substring_gate_replay.py` (all replay-only, no API calls), plus the
pre-registered EXP-7 dispatch (`scripts/run_exp7_chaining.sh`).

Data: the 386 finalised production pairs (`experiment_id IS NULL`) in
`data/odmi.db` as of 2026-06-11, countries MT 94 / NO 143 / FR 125 / EE 16
(DE/NL/RO excluded, n of 3 or fewer). MT is read as primary throughout
(base-rate balanced per R4); NO rows come from the development sweep and may
reflect in-flight code, which is disclosed wherever NO is cited. ODMI gold can
be one cycle stale (D22), so "correct" below means "matches the published
gold".

## 1. Attribution method and headline findings

Five replay analyses, each isolating one element. Results in
`evaluation/results/stack_attribution_20260611.json`,
`verifier_counterfactual_20260611.json`, `substring_gate_replay_20260611.json`.

### A. Verifier discrimination (the verdict as a classifier)

Each Verifier judgement of a definite Researcher candidate is scored against
the gold. Pooled over 488 judgements: TPR (pass given correct) 0.56
[0.51, 0.61], TNR (fail given wrong) 0.42 [0.33, 0.52], Youden's J = -0.02.
First-attempt-only: J = -0.018. Malta J = 0.148; Norway J = 0.014 with a false
accept rate of 0.71 [0.57, 0.81]. **The Verifier's verdict carries no usable
signal about whether the candidate is right.** This independently confirms the
judgement behind the current verifier redesign work.

### B. Retry dynamics (what the loop, as distinct from the verdict, buys)

Of 212 retried pairs: 61 recovered (wrong or abstain at attempt 0, correct at
final), 15 degraded (correct at attempt 0, wrong or abstain at final), 25
converted an attempt-0 abstention into a wrong commit. 36 of the 61 recoveries
needed the full three retries, and 71 pairs stayed abstain-to-abstain, so the
loop exhausts its budget with recoveries still arriving. Of 42 pairs whose
correct first candidate the Verifier rejected, 27 ended correct anyway, 14
ended in abstention, 1 ended wrong: false rejects destroy roughly a third of
the correct answers they touch.

### C. Adjudicator value

Committed accuracy 35/51 = 0.69 [0.55, 0.80]. The flip table is the finding:
when the last Researcher candidate was correct (79 adjudicated pairs) the
Adjudicator abstained on 42 and committed wrongly on 4; when it was not
correct (47 pairs) the Adjudicator rescued only 2. **The Adjudicator is a
conservative abstention machine, not a recovery mechanism.** Its safety
contribution is real (it rarely commits errors) but it converts more correct
candidates into abstentions than it rescues wrong ones, by an order of
magnitude (42 vs 2).

### D. Snippet utilisation (the Researcher's evidence handling)

Across 302 runs with snippets and a definite answer: the cited source URL is
inside the snippet set in 99% of runs and the evidence quote is found in the
stored snippets in 89%. **Grounding is not the problem.** The constraint is
breadth: runs average only 5.1 snippets, and 24% of cited snippets sit at rank
5 or deeper, so the tail of the result list is doing real work. This
pre-registers a directional prediction for EXP-2a: the lean retrieval arm
(2 queries x 3 results) will lose accuracy, because rank-4+ results carry a
quarter of the citations.

### E. Substring gate (D34)

Recorded production rows: the gate fired on 100 gold-correct candidates vs 18
gold-wrong ones. The date split explains it: pre-D34 rows (live-fetch gate)
fail at 58%; post-D34 rows with stored snippets fail at 7%; and 49 of the 73
post-D34 fires come from rows *without* stored snippets, where the gate still
falls back to a live fetch. Replaying the snippet-path gate over all stored
(quote, snippets) pairs reproduces the recorded result exactly (301/301) and
fires on only 8% of correct candidates. Softer variants (80% token
containment, 25-token prefix) fire less but discriminate wrongness no better;
no variant has fire-precision-for-wrongness above 0.19. **The gate is an
anti-fabrication control, not an error detector, and its false-fire damage is
concentrated in the live-fetch fallback.**

### F. Researcher confidence calibration

Attempt-0 definite candidates against gold, by stated confidence: 0.90+ band
98% correct (64/65), 0.80 to 0.89 band 98% (50/51), 0.65 to 0.79 band 92%,
0.50 to 0.64 band 78%. The Researcher's own confidence is a far stronger
correctness signal than the Verifier's verdict (J of about zero). The
distribution matters as much as the calibration: 71 of 108 FR attempt-0
candidates clear 0.80 but only 1 of 14 MT candidates does, so a
high-confidence fast path is a cost lever on easy countries and a no-op on
hard ones. It cannot help recovery; it can only cut spend.

### G. Verifier counter-evidence overlap

Of 280 Verifier fails carrying counter-evidence, 134 (48% [42, 54]) cite the
same URL the Researcher cited. Half of the "independent counter-evidence" is a
re-read of the Researcher's own source with a different interpretation, which
both halves the value of feeding counter-evidence back (EXP-7) and means the
Verifier's search budget is partly duplicative.

### Counterfactual policies (what the whole loop is worth)

Replaying commit policies over stored attempts (MT primary, 73 gold-bearing
pairs): observed pipeline 44% overall accuracy (committed accuracy 82%, FP on
no-golds 5%); Researcher-solo with the same 0.65 floor 10%; solo allowing any
attempt 23%; an oracle verifier that commits exactly the gold-correct
candidates already generated 74%. On FR the ordering reverses: solo 69% beats
the observed 63%, because the loop's false rejects degrade correct answers on
an easy country. Two conclusions: **the loop is what makes hard countries
answerable (44% vs 10% on MT), and candidate selection is the single largest
headroom (+30 points on MT) since the right answer is usually already in the
candidate set.**

## 2. Hypotheses and experiments

| ID | Element | Hypothesis | Experiment | Status |
|---|---|---|---|---|
| H1 | Retry loop | Chaining evidence across retries recovers more correct answers per call at no higher false-positive rate | EXP-7 (pre-registered, `EXPERIMENTS_CHAINING.md`): paired baseline vs `--chained`, frozen Malta 40-pair draw, knobs pinned (diy, cold cache, disprove, 5 results, 3 retries) | running 2026-06-11 |
| H2 | Substring gate | Gate false-fires are a live-fetch-fallback artefact; restricting the hard fail to the snippet path removes most false rejects at no anti-fabrication cost | Offline replay over stored rows (`substring_gate_replay.py`) plus the date split | done, supported |
| H3 | Verifier verdict | The verdict adds no discrimination; the verifier's value is the retry trigger and its counter-evidence, not the pass/fail | Attribution A + counterfactual replay (`verifier_counterfactual.py`) | done, supported |
| H4 | Researcher retrieval | Snippet breadth, not snippet usage, is the researcher-side constraint; lean retrieval knobs will cost accuracy | Attribution D (rank distribution) now; confirmatory test is EXP-2a, prediction registered here before its run | replay done; EXP-2a queued |
| H5 | Adjudicator | Given the accumulated evidence corpus, the Adjudicator commits more of the correct candidates it currently abstains on, without raising the false-positive rate | Read out of EXP-7's chained arm (the corpus is the only change the Adjudicator sees); compare adjudicated-pair commit and accuracy rates across arms | pending EXP-7 |
| H6 | Commit floor | Lowering the 0.65 floor recovers too few correct answers to justify the precision loss | EXP-10 Phase B floor sweep (0.65 / 0.55 / 0.50), already run | done: keep 0.65 (0.55 and 0.50 fail the pre-set precision rule) |

## 3. Confound controls

- **One variable per arm.** EXP-7 arms differ only in `--chained`; provider
  diy explicit (never auto), cold cache, verifier-disprove, 5 results/query,
  3 retries, full prompt, default models, pinned in
  `scripts/run_exp7_chaining.sh`.
- **Paired designs.** EXP-7 runs both arms over the identical frozen 40-pair
  draw (seed 20260603); replays compare policies over the same pairs.
- **Base rates.** MT primary everywhere (30 no-golds in the EXP-7 draw); FR
  never used to support a recovery claim.
- **Contention disclosure.** A verifier-redesign harness shares the Claude
  proxy throughout 2026-06-11, so wall-clock latency endpoints are
  contention-inflated; accuracy, false-positive, and calls-per-pair endpoints
  are count/token-based and unaffected.
- **Worktree isolation.** The verifier redesign happens on another branch; the
  code under test here is the production snapshot of this worktree, so its
  in-flight changes cannot leak into these runs.
- **Stale gold.** Every `differ` cited in a conclusion deserves the D22 human
  glance; counts here treat the published gold as the reference.

## 4. Results log

- 2026-06-11: attribution A-E and the counterfactual replay run over 386
  production pairs; H2, H3, H6 resolved as above. EXP-7 dispatched (baseline
  arm first, then chained), `experiment_id = retry_chaining_mt_v1`.
- 2026-06-11 (later): the first baseline dispatch tripped the D43 DIY blocker
  at 6 of 40 finals. Root cause found and fixed: the Playwright render
  timeout was per-phase, not total. Browser launch (which balloons under
  concurrency) and the Cloudflare settle waits (4s + a networkidle wait of up
  to the full render timeout) sat outside the goto timeout, so one
  WAF-challenged URL could spend ~38s against a documented ~24s worst case
  and trip the 30s stage ceiling. `fetch_rendered_text` / `fetch_rendered_html`
  now treat `timeout_s` as a total budget (launch + goto + settle), restoring
  the D43 arithmetic (per-URL worst case httpx 8s + render 13s = 21s). Because
  child coordinators load code at spawn, continuing the run would have mixed
  fetch behaviours within and between arms; the 8 pre-fix finals were retagged
  `retry_chaining_mt_v1_aborted` (kept as audit trail, excluded from analysis)
  and both arms restarted from zero on the fixed code. This is an apparatus
  restart before any between-arm comparison existed, not a selective re-run
  (R11).
