# EXP-10: Malta failure-mode audit and targeted recovery (pre-registration)

Pre-registered 2026-06-03, in the spirit of `EXPERIMENTS_PROTOCOL.md` (the rules
R1 to R12 in section 0). This file fixes the design before the full run, so the
failure taxonomy cannot be reverse-fitted to the data. The git commit that adds
this file is the pre-registration record; its timestamp predates the result file
it governs.

A live reconnaissance of the in-progress Malta dispatch (batch `exp6_malta`)
motivated this experiment and is treated as a **pilot, not a result**: of 13
finalised Malta pairs, 8 matched, 5 abstained, and 0 were wrong; at the Researcher
level the abstentions split 7 below the D37 confidence floor and 3 on a fetch
4xx/5xx error. The taxonomy and the recovery design below are fixed here, before
the full classification, so the pilot cannot bias the coding.

---

## 1. Question

Malta is the base-rate-balanced primary country (R4): English is an official
language, so a failure there is not a language artefact, and it carries about 30
`no`-gold binary questions, so a false positive can actually occur. The pilot
suggests Malta's losses are abstentions rather than wrong answers, which makes
this a question about recall, not precision.

- **Phase A (diagnostic).** For each Malta swarm answer that diverges from ODMI
  ground truth, what is the primary cause, and what share of the losses is fixable
  engineering versus a structural ceiling that cannot be beaten from the open web?
- **Phase B (recovery).** Of the fixable causes, which single lever recovers the
  most correct pairs without raising the false-positive rate on Malta's negative
  golds?

## 2. Phase A: the failure-mode taxonomy

Every finalised Malta pair (`phase2_final`) is joined to its `ground_truth` row
and classified `match` / `near_match` / `differ` / `abstain` / `no_gt` by the same
logic as `_MATCH_STATUS_SQL` (`dashboard/lib/db.py`). Every non-match is assigned
exactly one **primary** cause from the list below, fixed here before the full
coding. Where more than one signal is present, the cause is assigned by the
priority order shown, because the earlier item is the upstream cause (a fetch
failure that also lands below the floor is coded as the fetch failure).

| # | Cause | Class | Detection signal |
|---|---|---|---|
| 1 | Fetch failure (4xx/5xx) | fixable | `403` / `status 4xx-5xx` in Researcher notes; no usable fetched content |
| 2 | No source found (thin web) | fixable | search returned nothing usable (empty `search_snippets`, no `source_url`) |
| 3 | Substring-gate failure | fixable | evidence quote present but the Verifier substring check failed (`substring_check_result`), so the answer decayed to inconclusive |
| 4 | Below confidence floor (D37) | fixable | a definite answer was reached but `answer_confidence` < 0.65, so the swarm abstained |
| 5 | Wrong answer, false positive | error | committed an answer that differs from gold; split false-yes (said yes, gold no) and false-no |
| 6 | Near-miss band | error | adjacent band on a non-binary question (`near_match`) |
| 7 | Self-report / deny-list ceiling (D29) | structural | gold on a deny-listed domain (the `data.europa.eu` MQA) or a national self-report, so the open web cannot establish it |
| 8 | Stale ground truth (D22) | structural | swarm answer plausibly correct on its evidence but disagrees with a gold that may be one cycle old |

Language is excluded **by design**: Malta is English, so no Malta failure is a
translation artefact. This is stated as a property, not measured.

**Classification method.**

- **Deterministic first pass.** Causes 1 to 4 and the false-positive split (5) are
  assigned by rule from the DB signals (notes, `substring_check_result`,
  `answer_confidence`, `source_url` presence, gold-domain membership of the
  deny-list). This covers the unambiguous majority.
- **LLM-assisted residual.** Only the ambiguous cases, chiefly telling a genuine
  wrong answer (5) apart from stale ground truth (8), go to an Opus judge that
  reads the **frozen** evidence, the swarm answer, and the gold, and returns the
  more likely of `{genuine_error, stale_gold, unclear}`. No new search is run, so
  this step is Tavily-independent. Every judgement is written to JSONL with its
  rationale.

**Output.** A per-pair JSONL (cause, the signals used, any LLM rationale) and an
aggregate table of cause x count with Wilson 95% intervals, each cause flagged
fixable / structural / error, plus a per-dimension secondary split with achieved
counts (R3).

## 3. Phase B: targeted recovery

Phase A ranks the fixable causes by volume. Two recovery levers are
pre-registered.

**Lever 1, confidence-floor sweep (primary, free).** Re-apply the finalisation
commit rule at floors {0.65 baseline, 0.55, 0.50} to the **already-stored**
Researcher answers and confidences. No new dispatch and no API: a deterministic
replay of the commit decision, paired across floors on the same pairs. For each
floor, report:

- recovered = abstentions at 0.65 that become commits at the lower floor,
- of those, correct (match gold) and false positive (differ),
- the **precision** of the newly committed answers (correct / recovered),
- the false-positive rate on Malta's negative (`no`) golds.

**Pre-specified decision rule** (so the floor is not chosen post hoc): adopt a
lower floor only if, among the newly committed answers, precision is at least
0.80 **and** the false-positive rate on negative golds does not exceed the
baseline rate by more than 0.05. If both lower floors clear the rule, the
higher-recovery one is recommended; if neither clears it, the finding is that the
0.65 floor is correct and Malta's abstentions are not safely recoverable by the
floor.

**Lever 2, fetch-403 retry (secondary).** For the pairs coded as a fetch failure
(cause 1), re-attempt retrieval through a different path (Brave, or an altered
request) on those pairs only, and report how many move from abstain to a definite
answer and whether the new answer matches gold. This needs a small targeted
re-dispatch (search), so it runs only when non-Tavily search quota allows.

## 4. Statistics (fixed in advance)

- Proportions (cause shares; recovery precision; false-positive rate) as **Wilson
  95% intervals**; the interval, not the point, is the result.
- The floor sweep is paired on the same pairs; the recovered-versus-baseline
  commit comparison is **McNemar exact** on the commit indicator where n permits.
- One **primary comparison**: floor 0.55 vs the 0.65 baseline. Floor 0.50 and the
  per-dimension splits are secondary and Holm-corrected.
- **Stopping rule.** Fixed sample: the Malta finalised set at the stated commit. A
  larger Malta dispatch is reported as a separate, larger-n re-run, not folded in
  to move a number.

## 5. Impartiality threats and controls

| Threat | Control |
|---|---|
| Taxonomy reverse-fitted to the data | Coding scheme and priority order fixed in this commit before the full classification; the recon is declared a pilot. |
| Investigator coding bias | Causes 1 to 4 assigned deterministically from DB signals, not by judgement; only the genuine-error vs stale-gold residual uses a judge, over frozen evidence, with the rationale logged. |
| Structural ceiling mistaken for swarm failure | Causes 7 and 8 are separated out and never counted as fixable; the headline reports fixable vs structural explicitly. |
| Floor chosen to flatter recovery | The adopt-the-floor decision rule (precision and false-positive bounds) is fixed in advance; a floor that recovers pairs but adds false positives is reported as not adopted. |
| Base-rate degeneracy | Malta is the balanced country (R4), so the false-positive rate in Phase B is measurable; the same audit on France would be meaningless, which is why it is not run there. |
| Live-dispatch drift | The audit runs on a frozen snapshot of the Malta set at a stated commit; a later, larger Malta set is a separate run. |

## 6. Honest reporting

If the dominant Malta loss is structural (the self-report / deny-list ceiling),
the finding is that Malta performance cannot be lifted from the open web beyond
that ceiling, and the floor sweep is reported as no help. A null recovery ("the
0.65 floor is already right") is the result. Every per-pair code and every
floor-sweep outcome is written to JSONL so an examiner can replay it.

## 7. Registry (D27) and dependency

`experiment_id = malta_failure_audit_v1`, inserted into the `experiments` table
before the run. Harness: `evaluation/malta_failure_audit.py` (Phase A coding plus
the Phase B floor sweep), built and unit-tested before the run (R1: the analysis
exists before the data is read in anger). Result:
`evaluation/results/malta_failure_audit_*.jsonl`.

**Dependency.** Consumes the Malta finalised set produced by the `exp6_malta`
dispatch. Phase A runs incrementally on whatever exists; the floor sweep runs on
stored data with no quota. The fetch-403 retry (Lever 2) needs non-Tavily search.

## Change log

- 2026-06-03: created. Pre-registers EXP-10 (Malta failure-mode taxonomy plus the
  confidence-floor recovery sweep). Motivated by a pilot on the in-progress
  `exp6_malta` dispatch (8 match / 5 abstain / 0 wrong; abstentions 7 below-floor,
  3 fetch-4xx). No results at commit time.
