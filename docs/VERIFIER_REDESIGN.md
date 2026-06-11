# Verifier redesign: proposals towards D45

Status: proposal for discussion, 2026-06-10. Nothing here is implemented.
Adoption requires a numbered SPEC decision (D45 is the next free number; D44
exists in code, `scripts/run_coordinator.py:366`, but has no SPEC entry yet)
and the pre-registered experiment in section 9. All diagnosis numbers below
were re-derived from `data/odmi.db` on 2026-06-10; the SQL is in the appendix.

## 1. The measured problem, reproduced and sharpened

The brief's Malta diagnosis reproduces. On the joined set of Malta disprove
runs with a definite Researcher answer and an ODMI gold (n = 114 of 152 rows;
the brief's 130 used a looser filter, same conclusion):

- P(pass | correct) = 0.571 (44/77) vs P(pass | wrong) = 0.432 (16/37).
  Fisher p = 0.23. The verdict does not discriminate correctness.
- P(pass | yes-claim) = 0.368 (14/38) vs P(pass | no-claim) = 0.605 (46/76).
  Fisher p = 0.028. The verdict does discriminate claim direction.
- On yes-claims alone: P(pass | correct) = 0.385 vs P(pass | wrong) = 0.333,
  p = 1.0. Zero discrimination.
- On no-claims there is weak, non-significant discrimination: 0.667 vs 0.480,
  p = 0.14. The asymmetry is harshness on yes-claims, leniency on no-claims.

Five further findings change what the right fix is.

**(a) False fails are evidence-fit complaints, not counter-evidence.** Sampled
rejection reasons on correct answers read "the quote does not address the
question", "generic EU-level text, not Malta-specific". The Verifier is
rejecting the support, not the claim. The fail verdict conflates "the claim is
false" with "the support is weak". Those need different consequences.

**(b) The Verifier's own counter-quote is never checked.** The schema requires
`counter_evidence_quote` or `counter_source_url` on every fail
(`agents/models.py:241`), but nothing verifies that quote against anything.
52 of 54 Malta fails carry a counter URL, including the evidence-fit
complaints. The field that was meant to make fails accountable forces the
model to dress up "I found nothing" as counter-evidence. The Researcher faces
a deterministic D34 gate; the Verifier faces none.

**(c) The substring gate is wrong in both directions.** The gate matches the
quote against a corpus built by joining all snippets with `"\n\n"`
(`agents/verifier.py:163`), then normalising whitespace and punctuation away
(`agents/tools/substring.py:24`). Demonstrated by construction: a quote
stitched across the junction of two snippets from different sources passes;
a legitimate elision ("A ... B" within one passage) fails. In the DB,
ellipsis-bearing quotes fail the gate at 43% (26/60) vs 33% (191/584) for
plain quotes, and 6 of the 8 substring-driven hard fails on Malta hit correct
answers.

**(d) The floor, not the Verifier, controls commits; and on no-claims it also
caps recall.** Of 94 golded Malta pairs, only 18 commit in-loop via
`accepted_by_verifier` (16 match, 2 differ); 67 are decided at or after the
Adjudicator. Researcher confidence on no-claims averages ~0.50 (wrong) and
~0.55 (correct); 24/25 wrong and 43/51 correct no-claim attempts sit below the
0.65 floor (`scripts/run_coordinator.py:857`). So absence claims rarely commit
in-loop whatever the verdict, and the verdict's main lever is retry pressure
plus what the Adjudicator sees. A verdict-only redesign moves little; the
recall lever is a trustworthy confirmation channel.

**(e) Verifier confidence has weak pass-side signal and none on fails.** Mean
`verifier_confidence`: pass-correct 0.713, pass-wrong 0.631, fail-correct
0.645, fail-wrong 0.649. D44's commit receipt already showed that trusting
confident passes is net-negative (+2/-3 on the Norway replay) because the
Verifier confidently passes wrong no-claims.

**Replay of the proposed refute gate (the key receipt).** Re-running the
proposed deterministic gate (section 3) over the 54 stored Malta fails:

| | n | substring hard-fail | verified refute | downgrade to inconclusive |
|---|---|---|---|---|
| fails on wrong answers | 21 | 2 | 8 | 11 |
| fails on correct answers | 33 | 6 | 7 | 20 |

Verified refutes hit wrong answers at 8/21 vs correct at 7/33, roughly double
the raw fail verdict's odds ratio. Of the 31 downgrades, only 4 carried
researcher confidence >= 0.65 and would now commit: 3 wrong, 1 correct. That
is the honest worst-case false-positive cost of the downgrade, against 20
correct answers released from forced retries.

One number the replay cannot give: the confirm channel's recall gain. The
stored Verifier snippets are adversarial-direction only, so corroboration
searches must be measured live (section 9).

## 2. Design principles the redesign keeps

- Honest abstention: an abstention beats a confident wrong answer (D37).
- Anti-hallucination: every claim traces to a quoted passage in a source the
  agent actually read (D34). The redesign extends this to the Verifier.
- Deny-list (D24) untouched and hard.
- The D34 substring hard gate stays, repaired (proposal 4), not removed.
- D44's Adjudicator backstop (no unsupported "no") stays.

## 3. Proposal 1 (rank 1): three-way verdict with deterministically gated extremes

**Mechanism.** Replace `verdict: pass | fail` with
`verdict: refute | inconclusive | confirm`, where the extremes need receipts
that Python checks, and the middle is the unpenalised default:

- `refute`: the Verifier claims real counter-evidence. Valid only if
  `counter_evidence_quote` passes the per-snippet substring gate (proposal 4
  matcher) against the union of the Verifier's own search snippets and the
  Researcher's snippets. An unverifiable refute is downgraded to
  `inconclusive` in code, exactly as the blind strategy's divergence override
  works today (`agents/verifier.py:591`). Consequence: hard fail. Retry with
  the counter-evidence as feedback; at budget end, adjudicate.
- `confirm`: the Verifier claims independent corroboration. Valid only if
  `corroborating_quote` passes the same per-snippet gate against the
  Verifier's own snippets AND the matched snippet's URL differs from the
  Researcher's `source_url` (otherwise it is re-reading the same page, not
  corroboration). Consequence: pass; commit per the policy in section 6.
- `inconclusive`: searched, found nothing that decides it either way.
  Consequence: pass through; the D37 floor decides, unchanged. No forced
  retry from the Verifier (a sub-floor answer still retries on the existing
  floor-feedback rule, `scripts/run_coordinator.py:1326`).

Schema and storage changes: new verdict literal set (CHECK constraint at
`scripts/setup_sqlite.py:196` needs a migration; old rows keep `pass`/`fail`);
`counter_*` fields required only for `refute` (this deletes the
forced-fabrication bug in (b)); new `corroborating_quote` and
`corroborating_url` required for `confirm`; persist per-snippet URLs on the
Verifier row (today `independent_evidence` stores "title - snippet" strings
with the URL dropped, `agents/verifier.py:467`, so confirm provenance is not
currently auditable).

**For.** It separates the two states the binary verdict conflates, which is
exactly the failure measured in (a). The extremes become auditable objects an
examiner can replay, in the same way D34 made the Researcher's quote
auditable. Its degenerate worst case (model emits only `inconclusive`) reduces
the Verifier to a no-op pass-through, which on the Malta evidence is better
than the incumbent, whose failure mode actively destroys correct answers.

**Against, and the answers.** (i) LLMs like middles; the verdict could
collapse to `inconclusive` (the D28 `other`-collapse experience). Answer: the
middle is the correct default under honest abstention; the extremes are where
the value is, and they are gated, so collapse is a measurable distribution
shift (reported in section 9), not a silent failure. (ii) Three-way adds
policy complexity on top of the floor. Answer: the commit rule stays one
inequality with a categorical offset (section 6). (iii) The downgrade lets
some wrong answers through: measured, 3 commits on the whole Malta trail.
Held against today's level by proposal 3's ceiling, and cheaper than the 20
correct answers the fail branch currently drags into retry decay.

**Expected effect.** Hard-fail discrimination roughly doubles (replay above);
false rejections of correct answers drop from 33 to 13 run-level events on the
Malta trail; in-loop recall up modestly; what reaches the Adjudicator gains
verified/unverified labels (section 7). FP change bounded at +3 on the Malta
trail before the proposal-3 ceiling, which targets exactly those cases.

**Change required.** `agents/models.py` (VerifierOutput literal + validator),
`agents/verifier.py` (gate + downgrade logic), one new strategy prompt
(`verifier-tristate`, a new `strategy_label` per the four-step recipe in
`agents/prompts/verifier.py:33`), coordinator verdict branching
(`scripts/run_coordinator.py:1291`), schema migration, dashboard verdict
rendering.

## 4. Proposal 2 (rank 2): symmetric burden, "verify the positive"

**Mechanism.** Normalise every verification to the presence proposition: the
concrete thing that would make the answer "yes" (a portal feature, an API, an
enacted instrument). The query generator already inverts direction and is
shape-aware (`agents/verifier.py:65`); what is missing is the consequence
rule, which today is the free pass written into the negation prompt: "If you
cannot find inverted evidence: verdict=pass"
(`agents/prompts/verifier.py:331`). Replace with:

- Yes-claim: check the quote supports the presence proposition in scope and
  tense (the evidence-fit checks stay, but a fit complaint now yields
  `inconclusive`, not `refute`); search for negation or supersession; a
  verified negating quote yields `refute`.
- No-claim: run a structured confirmation search FOR the presence proposition
  before any verdict: a fixed probe set of k queries (portal feature page,
  API or developer documentation, official policy register, plus a
  national-language probe; the language probe already exists in query-gen).
  Verified presence found: `refute` (the strongest possible evidence against
  a "no"). Verified explicit negative statement found: `confirm`. All probes
  dry: `inconclusive` with a machine-set `absence_corroborated = true` flag
  (set by Python from the search result count, not by the model).

This replaces "I could not disprove it" (which is what lets wrong no-claims
sail through at 0.605) with "I ran the named probes for the thing itself and
they came up dry", which is a logged, replayable event.

**Expected effect.** Discrimination on no-claims rises (the probe search is
exactly the search that finds the 12 wrong no-claims that currently pass);
correct no-claims keep a route to commit via `absence_corroborated`. Cost:
one query-gen call unchanged, search volume per no-claim roughly equal
(probes replace, not add to, the adversarial queries).

**Change required.** Query-gen prompt v3 with the probe checklist;
tristate strategy prompt direction rules; `absence_corroborated` computed in
`agents/verifier.py` and stored.

## 5. Proposal 3 (rank 3): absence-claim commit policy (receipts plus ceiling)

Absence claims ("no", "none", the bottom band) have no quotable passage, which
is FM-19's core. Three locks, none of which requires trusting prose:

1. **Researcher receipts.** For an absence answer, the Researcher's
   `evidence_quote` must cite the negative space: the authoritative page that
   would contain the feature (the API docs listing only what exists, the
   policy register page). The D34 gate applies to that quote as to any other.
   The Researcher already logs `search_queries_used` and `fetched_urls`
   (`agents/models.py:184`); the validator gains a deterministic check that an
   absence answer's logs show at least N distinct queries naming the
   country or portal, else the answer is treated as under-searched and
   retried. No new prose fields to hallucinate; the receipts are the logs the
   pipeline already writes.
2. **Verifier confirmation search** (proposal 2). An absence claim can only
   reach a commit via `confirm` (explicit negative statement, rare) or
   `inconclusive` with `absence_corroborated = true`.
3. **Confidence ceiling.** Absence claims commit at floor + 0.10 (0.75)
   unless `absence_corroborated`, in which case the standard 0.65 applies.
   Both numbers frozen before the confirmatory run (section 9), tuned only on
   the already-burned Malta replay.

The blanket alternative ("shave confidence on every inconclusive") is rejected
on data: 12 of the 16 correct in-loop Malta commits sit in [0.65, 0.75), so a
blanket -0.10 destroys most of the one channel that works (16/18 precision) to
block one wrong commit. The reduction must target the class where the FP risk
lives, which is the unsupported "no".

**Expected effect.** Wrong no-claims stop passing un-searched; correct
no-claims commit through the corroborated route; abstention rises only on
under-searched absence answers, which is the honest-abstention principle
doing its job. This also gives the D44 Adjudicator backstop an in-loop
counterpart instead of catching the problem only at adjudication.

## 6. The commit rule, in one place

Let c = the Researcher's `answer_confidence`, A = answer is absence-class
(per-question lookup derived from `allowed_answers`, committed as data, not
inferred at runtime).

- `refute` (verified or substring hard-fail): never commit. Retry with
  feedback; adjudicate at budget end.
- `confirm` (verified, independent URL): commit iff c >= 0.65 - u. Uplift
  u = 0 at first ship; u = 0.10 turned on only if measured confirm-precision
  clears the bar in section 9. The uplift is the recall lever for the
  systematically under-confident correct no-claims (mean c ~ 0.55), and it is
  the one number that can only be measured live.
- `inconclusive`: presence-class, commit iff c >= 0.65 (today's rule,
  unchanged); absence-class, commit iff c >= 0.75, or c >= 0.65 with
  `absence_corroborated`.

`_should_accept_verifier_pass` (`scripts/run_coordinator.py:878`) becomes
`_commit_decision(verdict, answer, c, flags)`, a pure function, unit-tested,
replayable over stored trails exactly as the D44 receipt was.

## 7. Proposal 4 (rank 4 by headline impact; do first, it is a bug fix): quote integrity v2

**Deterministic part.**

1. Match per snippet, not against the joined corpus. This kills the
   demonstrated junction-stitch false pass (two unrelated snippets read as
   one passage today because `"\n\n".join(...)` then whitespace-collapse
   erases the boundary).
2. Split the quote on ellipsis markers (`...`, `[...]`, `…`). Require every
   fragment to be at least 15 normalised characters (kills FM-11 short-quote
   false matches) and all fragments to match within the SAME snippet, in
   order. Same-passage stitching becomes legal and checkable; cross-source
   splicing becomes impossible.
3. Record provenance: which snippet index and URL matched. If the matched
   snippet's URL differs from the cited `source_url`, flag quote-url mismatch
   (FM-10) and treat as a gate fail with that specific note.

**LLM part (in-context relevance, FM-02).** The tristate prompt receives the
full matched snippet with the quote fragments marked, and must judge one
question: does the surrounding context change or qualify the meaning the
Researcher assigned to the quote? Recorded as a boolean plus note. It informs
the verdict but is not a hard gate (context judgement cannot be made
deterministic).

**Expected effect.** Closes fabrication-by-splicing; removes the false hard
fails on legitimate elided quotes (43% vs 33% gate-fail rates today, and 6 of
8 Malta substring hard-fails hit correct answers); FP unchanged or down.
This is independent of the verdict redesign, low-risk, and testable entirely
offline against stored rows, so it should land first.

## 8. Proposal 5 (rank 5): ordered shapes verify the figure, not the label

For `percentage_band` / `count_band` / `ordinal_magnitude` (17 questions):
the Verifier must extract the underlying figure from its verified quote;
Python maps figure to band deterministically (a pure function over the band
edges; ordinal labels via lookup). `refute` requires a verified figure
mapping to a different band, and carries `refute_margin = |band index
delta|` (a two-band miss is stronger evidence than one). `confirm` requires a
verified figure mapping into the claimed band. No verified figure means
`inconclusive`. The Verifier stops free-riding on binary verdict semantics,
and FM-06 (82% read as >90%) is caught by code, not vibes. The adjacent-band
machinery (`near_match`, D28) already scores the outcome side.

## 9. Proposal 6 (rank 6): verifier_confidence is telemetry, not policy

Decide its role: none. It gates nothing, routes nothing, shaves nothing. The
evidence: it currently has no decision path anyway (the floor reads the
Researcher's confidence, `scripts/run_coordinator.py:878`); its only signal is
a weak pass-side gap (0.713 vs 0.631) that is exactly the channel D44's
replay showed to be net-negative (+2/-3) when trusted; on fails it carries
nothing (0.645 vs 0.649). Under the redesign its job is done by categorical,
verified objects. Keep storing it for the calibration analysis in the
dissertation (FM-22), and revisit only if the EXP arms show a usable AUC.
Routing borderline cases to the Adjudicator is handled by the verdict
categories themselves (a final-attempt `refute` adjudicates; the Adjudicator
input gains the verified/unverified flag per attempt,
`agents/prompts/adjudicator.py:151`), not by a confidence threshold.

## 10. Measurement: EXP-11, on the EXP-6 apparatus

Superseded in detail by `docs/EXPERIMENTS_VERIFIER_REDESIGN.md` (2026-06-10),
the operational pre-registration and runbook for the staged programme
(stage 0 offline replays and knob freeze, stage 1 classifier ladder, stage 2
end-to-end dispatch). That file is the authority on arms, endpoints, and
adoption rules; this section stays as the design rationale. Numbered EXP-11
because EXP-10 is the Malta failure-mode audit.

The EXP-6 harness (`evaluation/verifier_strategies.py`) already implements
frozen-evidence paired arms, Youden's J, MCC, balanced accuracy, Wilson CIs,
and Holm-corrected exact McNemar (`:788`, `:864`). EXP-11 reuses it with
these amendments, pre-registered in a new `docs/EXPERIMENTS_VERIFIER_REDESIGN.md`
before any run, registry id `verifier_tristate_v1` (D27).

**Arms (paired, same candidates, frozen evidence).**

- A: `verifier-disprove` v3 (incumbent default).
- B: `verifier-tristate` with gates on (proposals 1+2+4).
- C: `verifier-tristate-ungated` (same prompt, Python gates off). Isolates
  whether the vocabulary or the deterministic gates do the work.
- D: `verifier-blind` v3 (the structural-debiasing control from D15).

**Frozen evidence, extended.** Per candidate, run both query-generation
variants once (adversarial and confirmation probes), search each query set
once on a pinned provider (`diy`, no auto-fallback, no cache, per the
EXP-6 2026-06-06 amendment and the one-variable rule), freeze the union.
Each arm sees only its own protocol's results. Substring results are computed
once per matcher version: v1 for arm A (its production behaviour), v2 for
arms B/C, both recorded for every candidate so the gate change is separable
in analysis.

**Items.** Malta natural pool (60 questions, 152 disprove rows) is the
development set: this document's diagnosis burned it, so it cannot carry a
confirmatory claim, and the EXP-6 changelog (2026-06-06) flags its
half-Maltese estate as a language confound. Confirmatory primary: the
Netherlands natural pool from the pinned-provider EXP-6 dispatch (71-question
committed set, `data/questions/exp6_question_set.json`; the NL pool currently
holds 3 questions post-purge, so the dispatch EXP-6 needs anyway is the
prerequisite). Robustness: the committed FR augmented 50%-flip set
(`data/questions/fr_augmented_eval_pairs.json`, injection removes the
ODMI-staleness confound) and the Norway natural pool (143 finals, 211
disprove rows, yes-heavy 104:9, so it tests the redesign where the base rate
flips). Note the brief asked for Malta as the EXP-6 primary; the standing
pre-registration moved the primary to NL on 2026-06-06 and this design
follows it, keeping Malta as the dev set.

**Endpoints.**

- Primary: Youden's J on the NL natural set, verdict binarised as
  refute = fail, {confirm, inconclusive} = pass. The classifier question and
  labels (`should_pass` / `should_fail` per `_MATCH_STATUS_SQL` logic) are
  unchanged from EXP-6, so A and D are directly comparable with history.
- Secondaries, tristate-native: P(refute | wrong) and P(refute | correct)
  with Wilson CIs; confirm-precision P(correct | confirm); verdict
  distribution per arm (degeneracy check); per-direction splits (the yes/no
  asymmetry becomes a tracked endpoint, target: pass-rate gap by direction
  compatible with zero); per-shape splits where n permits.
- Policy simulation: end-to-end commit replay (section 6 rule) over the
  frozen verdicts: accuracy, abstention rate, committed-wrong rate, against
  the incumbent's replay on the same candidates. Deterministic, no extra LLM
  calls, same method as the D44 receipt.
- Cost: output tokens and wall-clock per arm, paired Wilcoxon, as in EXP-6.

**Adoption rule (fixed in advance).** Adopt tristate as the production
default iff, on the NL confirmatory set: (i) J_B > J_A with exact McNemar
p < 0.05 on verdict-correctness, Holm-corrected over the three pairwise
comparisons against A; (ii) refute's false-rejection rate <= disprove's
(Wilson interval comparison); (iii) simulated committed-wrong rate <= the
incumbent's on the same candidates; (iv) the A-vs-B ranking direction holds
(point estimate) on both robustness arms. If (i) fails but (ii) to (iv) hold
and J_B >= J_A - 0.05, adopt iff the simulated abstention rate falls by at
least 5 points (the recall case). Otherwise the incumbent stays and the null
is reported (CLAUDE.md, honest evaluation). The confirm uplift u = 0.10 turns
on in a second decision, only if confirm-precision >= 0.85 on NL (today's
in-loop commit precision is 16/18 = 0.89; the uplift must not dilute it).

**Power honesty.** The NL natural pool will give roughly 71 candidates with
a minority should_fail class; the McNemar discordant-pair test and the Wilson
intervals are the honest statistics at that n, and a partial run is reported
as partial per the EXP-6 stopping rule. The robustness arms add n but never
merge into the primary.

## 11. What this package does not fix

- FM-19's hard core: questions whose gold answer is not on the open web at
  all (about half of Quality per D29/D30). No verifier redesign makes those
  answerable; the catalogue route (D30) and abstention are the answers.
- FM-21 correlated error: Researcher and tristate Verifier share model
  family, search provider, and snippets; a shared blind spot passes as
  `inconclusive` and can commit above floor. The cross-family check from
  EXP-1 (Mistral) is the template for measuring this later.
- ODMI gold staleness (D22): a verified refute can be "correct" against a
  stale gold. Unchanged; the injected-flip robustness arm controls for it in
  measurement.

## Appendix: verification SQL

All run against `data/odmi.db` on 2026-06-10. The joined base view:

```sql
CREATE TEMP VIEW joined AS
  SELECT v.*, LOWER(TRIM(r.answer)) AS r_answer, r.answer_confidence,
         CASE
           WHEN REPLACE(LOWER(TRIM(r.answer)),'_',' ')
                = REPLACE(LOWER(TRIM(gt.response)),'_',' ') THEN 1
           WHEN LOWER(TRIM(r.answer))='yes'
                AND LOWER(TRIM(gt.response)) LIKE 'yes%'
                AND EXISTS (SELECT 1 FROM questions q
                            WHERE q.question_id=v.question_id
                              AND q.answer_shape='binary') THEN 1
           ELSE 0
         END AS r_correct
  FROM phase2_verifier_runs v
  JOIN phase2_researcher_runs r ON r.id = v.researcher_run_id
  JOIN ground_truth gt ON gt.question_id = v.question_id
                       AND gt.country_code = v.country_code
  WHERE v.country_code='MT' AND v.strategy_label='verifier-disprove'
    AND LOWER(TRIM(r.answer)) IN ('yes','no')
    AND gt.response IS NOT NULL AND TRIM(gt.response) <> '';
```

- Pass rates by correctness and direction:
  `SELECT r_answer, r_correct, COUNT(*), SUM(verdict='pass') FROM joined GROUP BY 1,2;`
  (yes: 14/38 pass, 10/26 correct-pass, 4/12 wrong-pass; no: 46/76 pass,
  34/51 correct-pass, 12/25 wrong-pass). Fisher tests via scipy:
  direction p = 0.028, correctness p = 0.23, yes-only p = 1.0.
- Confidence by cell:
  `SELECT verdict, r_correct, ROUND(AVG(verifier_confidence),3) FROM joined GROUP BY 1,2;`
- Counter-evidence presence on fails:
  `SELECT r_correct, COUNT(*), SUM(counter_source_url IS NOT NULL) FROM joined WHERE verdict='fail' GROUP BY 1;`
- Researcher confidence bands on no-claims:
  `SELECT r_correct, SUM(answer_confidence<0.65), ROUND(AVG(answer_confidence),3) FROM joined WHERE r_answer='no' GROUP BY 1;`
- Terminal statuses: `phase2_final` joined to `ground_truth` for MT, grouped
  by `terminal_status` and the match CASE (94 golded pairs: verifier 16+2,
  adjudicator 19+15+7, escalated 5+16+5, failure 9).
- In-loop commit confidence: `final_answer_confidence` bands on
  `terminal_status='accepted_by_verifier'` (12 of 16 matches in [0.65,0.75)).
- Refute-gate replay and stitch demonstrations: Python over
  `counter_evidence_quote`, `independent_evidence`, `search_snippets` with
  `agents.tools.substring.contains` per snippet; junction-stitch and elision
  cases constructed directly against `substring.contains`.
- Ellipsis gate rates:
  `SELECT quote-has-ellipsis, substring_check_result, COUNT(*) FROM phase2_verifier_runs JOIN phase2_researcher_runs ... GROUP BY 1,2;`
  (ellipsis 26 fail / 34 pass; plain 191 fail / 393 pass / 6 not attempted).
- Pools: `SELECT country_code, COUNT(DISTINCT question_id) FROM phase2_researcher_runs GROUP BY 1;`
  (NO 143, FR 130, MT 60, EE 16, NL 3, DE 3, RO 2).
