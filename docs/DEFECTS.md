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
| D2 | EXP-40 cooperative arm has no surviving rows | high | **fixed** 2026-07-21 (LFS recovery) |
| D3 | EXP-36 headline computed mid-run | high | **fixed** 2026-07-20 |
| D4 | EXP-36 dedup double-counted five pairs | medium | **fixed** 2026-07-20 |
| D5 | Dissertation abstention section built on the wrong population | high | source fixed; **docx open** |
| D6 | Held-out FP audit stale and wrongly scoped | medium | **fixed** 2026-07-21 |
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
`data/rescued_experiments.db` (36.5 MB, committed). Superseded on 2026-07-21 by `5dc7127`, which restored 22 recovered experiments straight into canonical `data/odmi.db`; the standalone file is now a redundant belt-and-braces copy and can be dropped once the canonical restore has been relied on for a while. `phase2_final.id` is a
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

**Why re-dispatching was not the answer.** A fresh live arm produces a new
sample on a transport and model configuration that has since moved. That is a
new experiment, not a replication of the filed null, and it would have forced
§4.2 to be restated rather than reproduced.

**Repair, 2026-07-21.** The rows were recovered from an orphaned Git LFS
object. Git LFS had staged a snapshot of the deleted worktree's database into
the local object store, where it sat unreferenced by any commit
(`b37d933dd6f5b9b27cc5bda5d2cb0d423fbde5d898a6ae0d2af2d388f775df9c`, plus its
`-wal` and `-shm` sidecars). `git lfs prune --dry-run` listed 169 unreferenced
objects totalling 26 GB, and this was among them, so the arm was one prune from
permanent loss. Both EXP-40 and its EXP-34 replay source are now committed as
SQL dumps under `data/recovery/`, which no longer depend on the object store.

**Verified twice, independently.** Restoring both dumps into a copy of the
canonical database and re-running `evaluation/exp40_analysis.py` reproduces
`evaluation/results/exp40_analysis.json` byte for byte: all four arms, and the
primary contrast at n = 154, 8 versus 8, p = 1.00. Checked once by the
recovering session and once again from the EXP-41 pre-registration session
against a fresh scratch copy.

**No disclosure required on the result.** §4.2's numbers stand on recovered
per-pair rows, not on a stored aggregate. What does warrant a line in the
methods is that the recovery happened at all: the arm was retrieved from an
unreferenced object rather than from the versioned record, which is the D1
lesson restated. Never run `git lfs prune` while any experiment is
unaccounted for.

**Downstream, also closed.** `5dc7127` restored the 22 recovered experiments
into canonical `data/odmi.db` and migrated the CHECK constraint. Verified:
`evaluation/exp40_analysis.py --db data/odmi.db` now reproduces
`evaluation/results/exp40_analysis.json` byte for byte, all four arms, n = 154
at 8 versus 8, p = 1.00. The documented reproduction path works from the
canonical database with no recovery step.

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

## D6. The held-out false-positive audit was stale and wrongly scoped

Two problems, not one.

**Stale.** Filed at n = 83; 91 on the completed run, with per-country counts
moving in both directions (FI 17 to 14, ME 19 to 13 down; BA 7 to 10, BG 6 to
10, MK 16 to 22 up), so it ran against a mid-run snapshot rather than simply a
smaller one.

**Wrongly scoped.** `load_fps` filtered for a false positive *first* and took
the latest such row *second*, with no experiment filter, so a pair whose EXP-36
answer is fine still entered the audit on the strength of an older superseded
run. That pulled in 28 extra pairs, 24% of a 119-pair population: 24 from
`expC_held_neg_licence` and 4 from `exp21_frozen_headline`. The audit exists to
bound the staleness band on EXP-36, so those pairs do not belong in it.

**Repair.** `load_fps` now takes an `experiment_id`, defaulting to
`exp36_frozen_headline`, and yields exactly 91. The audit was re-run over all
119 with the judge pinned to `claude-opus-4-6` to stay comparable with the NL
audit, then scored on the correctly scoped 91.

**Result, EXP-36 only, n = 91.** Charitable: definitional gap 69, genuine error
16 (18%), defensible or stale gold 6. Adversarial: swarm over-read 68,
ambiguous 23, **gold_wrong 0**.

**The conclusion holds.** Zero of 91 held-out false positives have the swarm
right and ODMI wrong, matching the filed 0 of 83 and the NL audit's 0 of 22.
The D22 staleness band on held-out commit accuracy stays negligible, match /
differ remains a fair headline metric, and RESULTS.md section 2.9 stands. The
re-run is cleaner than the original, which produced one `gold_wrong` (SE I27)
that had to be rejected by hand; this one produces none outright. For contrast,
the 28 contaminating pairs carry a 32% genuine-error rate against the held-out
set's 18%, which is why leaving them in mattered.

Artefacts: `evaluation/results/heldout_fp_audit_rerun20260721.jsonl` and its
summary; the original `heldout_fp_audit.jsonl` is kept as the filed record.

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
| 2026-07-21 | **D2 repaired and closed**, overturning the 2026-07-20 "unrepairable" verdict: the rows were recovered from an orphaned Git LFS object and committed as SQL dumps under `data/recovery/`, verified to reproduce `exp40_analysis.json` byte for byte. §4.2 needs no re-run and no aggregate-only disclosure. Downstream action also closed the same day by `5dc7127`: canonical `data/odmi.db` restored and CHECK migrated, verified to reproduce the published table from the canonical DB alone. D7's forward-only fix has a consequence for EXP-41 (D65): `exp34_retrieval_strategy_s46/wide_only` carries the floor-leak artefact (0.65 on 9.4% of first-attempt commits against 32.7% of retried ones, the D7 signature), so it cannot serve as a replicate alongside runs dispatched after the fix. |
| 2026-07-21 | D6 repaired: audit rescoped to `exp36_frozen_headline` and re-run. 0 of 91 held-out false positives have the swarm right and ODMI wrong, so the staleness band stays negligible and section 2.9 stands. The six EXP-36 figures were copied into `docs/figures`. D1's standalone rescue file is superseded by the canonical restore in `5dc7127`. |
