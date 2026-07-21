# Defect register

Data-integrity and reproducibility defects found in the evaluation record, with
what each one damages and whether it can be repaired. Opened 2026-07-20 after a
numbers check on the §4 results draft turned up four unreconcilable figures and
the trail led to several deeper problems.

The rule for this file: a defect is only closed when the repair is verified,
and a defect that cannot be repaired stays open with the disclosure text it
needs. Nothing here is closed by being explained.

| id | defect | severity | status |
|---|---|---|---|
| D1 | Canonical DB is not the system of record | high | **fixed** 2026-07-20 |
| D2 | EXP-40 cooperative arm has no surviving rows | high | **open, unrepairable** |
| D3 | EXP-36 headline computed mid-run | high | **fixed** 2026-07-20 |
| D4 | EXP-36 dedup double-counted five pairs | medium | **fixed** 2026-07-20 |
| D5 | Dissertation abstention section built on the wrong population | high | source fixed; **docx open** |
| D6 | Held-out false-positive audit is stale | medium | **open, needs a decision** |
| D7 | Commit floor leaked to the Researcher in retry text | high | **code fixed; EXP-36 data open** |
| D8 | Three RDF adapter tests fail in a fresh venv | low | open, environmental |
| D9 | 33 agent rows carry an `unknown` model tag | low | open, already disclosed |

---

## D1. The canonical database was not the system of record

`data/odmi.db` is git-tracked and every worktree carries its own diverging
copy, so a run dispatched inside a worktree wrote its rows there and nowhere
else. Nine experiments cited in the results docs had **zero rows** in the
canonical database, including `exp34_retrieval_strategy_s46`, which is the
evidence for D64 (adopting `wide_only` in production) and the replay source for
three of EXP-40's four arms. Every one of them was a `git worktree remove` away
from deletion, which is exactly how D2 happened.

**Repair.** `scripts/rescue_orphaned_experiments.py` finds every experiment
with rows in a worktree but none in canonical and copies them, with their full
Researcher, Verifier and Adjudicator trails, into
`data/rescued_experiments.db` (36.5 MB, committed). `phase2_final.id` is a
per-database autoincrement and collides across copies, so it is never carried
over; `pair_run_id` is a UUID and is the key that stitches a pair to its trail.
The script is idempotent and read-only on every source.

Rescued: 1,134 finalised pairs, 3,839 researcher runs, 2,036 verifier runs, 594
adjudications, 1,938 subtrio rows, across `exp34_retrieval_strategy_s46` (314),
`exp18_breadth_multicountry` (284), `exp36_model_opus` (157),
`exp32_model_haiku` (156), `exp34_retrieval_strategy_s5` (69),
`exp33_model_tiered` (59), `exp38a_query_native_nl` (47),
`exp29_sonnet5_model` (44), `exp38b_query_translated_nl` (4).

**Still to decide.** The rescue file preserves the data but analysis scripts
still point at `data/odmi.db`. Run
`scripts/rescue_orphaned_experiments.py --merge-into data/odmi.db` from the
canonical checkout, with no dispatch running, to fold them in properly.

## D2. The EXP-40 cooperative arm has no surviving rows

`exp40_analysis.py` reads the cooperative arm from `phase2_final` by
experiment id. No database on the machine, canonical or worktree, holds a
single such row. The arm was the one live dispatch in the battery; the other
three are replays off EXP-34.

**What it damages.** The §4.2 primary contrast, no_adjudicator against
cooperative with McNemar p = 1.00, cannot be recomputed or checked by anyone.
It survives only as an aggregate in `evaluation/results/exp40_analysis.json`.
This fails the project's own reproducibility standard.

**Why it cannot be repaired.** Re-dispatching a live arm produces a fresh
sample on a transport and model configuration that has since moved. That is a
new experiment, not a replication of the filed null.

**Disclosure required.** Either report the null with an explicit statement that
the per-pair data did not survive and the result rests on a stored aggregate,
or demote it and lead §4.2 on the ladder, which is recomputable now that D1 has
restored EXP-34. Do not keep it as an unqualified headline.

## D3. The EXP-36 headline was computed mid-run

The committed `exp36_headline.json` was generated 2026-07-17 13:25 against an
incomplete run: 1,146 canonical pairs with Bulgaria at 142 questions rather
than 143, from 1,148 raw rows. Every downstream figure was slightly wrong.

**Repair.** Regenerated against the completed run: 1,144 pairs, 143 per
country. `RESULTS.md`, `docs/RESULTS.md` and `docs/EXPERIMENTS.md` corrected
cell by cell. Changes were small and no conclusion moved: coverage 0.558 to
0.556, commit accuracy 0.702 to 0.701, negative-gold FPR 0.258 to 0.255,
ECE 0.062 on n=628 to 0.063 on n=623, stratum commit accuracy 0.609/0.771 to
0.611/0.768, RQ3 negative-gold FP p 0.027 to 0.023.

## D4. The EXP-36 dedup double-counted five pairs

The canonical-row dedup keyed on (question, country, condition_label). Five
re-run pairs (FI PT39, FI PT40, FI Q15, MK I9, SE P9) lost their
`condition_label` on the researcher row, so each survived under both its
country label and `unlabelled` and was counted twice, giving 1,149.

**Repair.** `dedup_canonical` takes `scope_by_label`, cleared for EXP-36, which
keys on (question, country) and yields 143 per country. Every affected pair
answered identically across its copies, so no bucket moved.

## D5. The dissertation abstention section is built on the wrong population

§4.3 and Appendix B were written from `docs/ABSTENTION_TAXONOMY.md`, which
classifies the 2026-06-24 **main run** (1,657 finalised pairs, 580
non-committed) across all countries and experiments. It carried no scope
marker, so it read as authoritative. The held-out run is 508.

That produced: 580 as the held-out total; 563 as a component sum (the taxonomy
table minus codes C and Z); 537, which matches no population; a 77-pair
operational-failure group (B 51 + F3 21 + F1 5) where EXP-36 has 16; and the
§4 dimension abstention rates, which are also main-run.

**Repair, source.** A scope warning and an EXP-36 section were added to
`ABSTENTION_TAXONOMY.md`; the `146/580` citation in `REPORT_DIRECTION_MEMO.md`
was corrected to 199/508; `PROMPT_AUDIT.md` section 3 is flagged main-run only.

**Still open.** The .docx itself. Correct values: total 508; codes E 208,
G 199, I 30, D 24, Z 19, B 16, C 12, and A/F1/F3 zero; operational-failure
group 16, not 77, so repairing all of them lifts coverage from 0.556 to at most
0.570, not 0.62, and that is an upper bound because a repaired fetch still has
to satisfy the Verifier and clear the floor. Dimension abstention rates are
Quality 57.3%, Portal 47.5%, Impact 46.1%, Policy 25.8%.

## D6. The held-out false-positive audit is stale

`docs/SPEC.md` records the audit at n = 83 with a per-country split of BA 7,
BE 4, BG 6, FI 17, HR 4, ME 19, MK 16, SE 10. Recomputed on the completed run
under the same definition (committed, binary no-gold, swarm answered yes) the
count is **91**: BA 10, BE 6, BG 10, FI 14, HR 6, ME 13, MK 22, SE 10. The
per-country numbers move in both directions, so the audit ran against a
different row set, not merely a smaller one.

**What it damages.** The audit's conclusion, 0 of 83 false positives where the
swarm is right and ODMI wrong, is what licenses the claim that the D22
staleness band on held-out commit accuracy is negligible.

**Decision needed.** Re-running costs Opus judge calls over roughly 91 pairs.
The alternative is to disclose that the audit predates run completion and treat
its conclusion as indicative. Not fixable without that call.

## D7. The commit floor leaked to the Researcher

Two paths in `scripts/run_coordinator.py` built a retry message that named the
threshold: "its confidence (0.52) is below the 0.65 commit floor". The
Researcher then returned exactly 0.65, the cheapest value clearing the bar.

**Evidence.** 149 of 523 committed binary-gold answers sit at exactly 0.65.
Split by attempt, **40%** of retried commits land there against **9%** of
first-attempt commits. No versioned prompt contains the number; the leak was
only in the runtime retry text.

**What it damages.** For retried pairs the confidence is not an independent
belief but a response to being told the bar. It contaminates the 0.65 bin in
the reliability figure, and it means the D37 floor partly manufactures the
distribution it then filters on.

**Repair, forward only.** Both messages now state the requirement without the
number. This changes nothing about EXP-36's stored rows, which remain frozen
and still carry the artefact; it prevents recurrence in any future cycle.

**Disclosure required.** EXP-36's confidence distribution keeps the pile-up.
Any claim resting on the shape of that distribution near the floor should say
so.

## D8. Three RDF adapter tests fail in a fresh virtualenv

`tests/test_catalogue_adapter_rdf.py` fails three content-hash tests in a
worktree whose venv was built on Python 3.14. Confirmed pre-existing by
stashing all local changes and re-running. Almost certainly an rdflib
serialisation difference rather than a data defect, but it means the suite is
not green on a clean checkout.

## D9. 33 agent rows carry an `unknown` model tag

Already disclosed in `RESULTS.md`. A tagging gap, not model contamination: no
other model string appears in the run. Related to the missing
`condition_label` in D4, and worth a single fix to the dispatch tagging.

---

## Change log

| date | entry |
|---|---|
| 2026-07-20 | File created. D1 repaired (1,134 pairs rescued). D3, D4 repaired. D7 repaired forward-only. D5 source repaired, docx outstanding. D2 confirmed unrepairable. D6 awaiting a cost decision. |
