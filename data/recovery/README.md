# Recovered experiment data

Twenty-two experiments were missing from the canonical `data/odmi.db`, or
present there only in part. All 22 were recovered on 2026-07-21 and merged back
in. This directory holds the dumps so the recovery does not depend on sources
that are one `git lfs prune` from deletion.

## What happened

`data/odmi.db` is Git LFS tracked. An experiment dispatched from a worktree
writes its rows to that worktree's copy, and lands on main only if someone
commits the database. Repeatedly, the code, prereg and analysis JSON were
committed while the database was not, and deleting the worktree took the rows
with it.

EXP-40 is the clearest case. Its four commits (`5b663d9`, `8d699d2`, `5d2213f`,
`2106efd`) carry the cooperative arm's implementation, its pre-registration and
its published result, and not one of them touches `data/odmi.db`.

`evaluation/results/model_landscape_rows.sql` shows the same failure caught
halfway: someone exported the exp32/exp36 rows and wrote "migrate into canonical
with sqlite3 data/odmi.db < model_landscape_rows.sql" at the top of the file.
Nobody ran it. Both experiments were still absent a week later.

## Where the rows survived

Two places, neither of them durable.

**Unreferenced Git LFS objects.** LFS had staged snapshots of deleted worktrees'
databases into `.git/lfs/objects/`, unreferenced by any commit. EXP-40 came back
from `b37d933d` (with its `-wal` sidecar), `d50_neg_licence_confirm` from
`7fde9393`, `exp28_arch_ablation` from `7fbc8f7e`. At the time of recovery
`git lfs prune --dry-run` listed 169 such objects totalling 26 GB, so this was
one routine cleanup away from being unrecoverable.

**Other worktrees.** `exp36-run`, `beef-ai-lesswrong-feedback-f15c91`,
`nice-hermann-e2609b`, `vibrant-chaum-e1e17c`, `stupefied-dubinsky-9beec8` and
`language-accuracy-experiment-a40577` each still held rows nothing else had.

For every experiment the richest available source was used, which is why some
dumps come from a worktree and others from an LFS object.

## What came back

Twenty-two experiments, 2,141 `phase2_final` rows and 15,623 rows in total.

Sixteen were missing outright, including `exp40_cooperative_contrast` (157),
`exp34_retrieval_strategy_s46` (314, the replay seed EXP-40's other three arms
are computed from), `d50_neg_licence_confirm` (194), `exp32_model_haiku` (156)
and `exp36_model_opus` (157).

Six more were in canonical but **incomplete**, which is the worse failure: they
looked present and were not. `exp28_arch_ablation` held 99 of its 460 rows,
`exp20_chaining_committing` 212 of 316, `exp23_narrow_then_widen_nl` 58 of 131,
`exp19_verifier_search_multicountry` 275 of 318.

That partial data explains a standing defect. Before the restore, canonical
failed `PRAGMA foreign_key_check` with 1,592 violations: verifier rows whose
researcher row had never arrived. Restoring the missing researcher rows brought
that to **0**.

## Verification

`evaluation/exp40_analysis.py` run against the restored canonical database
reproduces the committed `evaluation/results/exp40_analysis.json` byte for byte
across all four arms, McNemar 8-vs-8 at p = 1.00 included. The numbers in
`docs/RESULTS.md` therefore rest on the original rows, not on a re-run.

`exp36_frozen_headline` is unchanged at 1,151 rows, and no table lost a row.

## Restoring

**Do not pipe these dumps into sqlite3.** Their INTEGER PRIMARY KEYs belong to
the database they came from; replaying them with `INSERT OR REPLACE` overwrites
whichever canonical rows happen to share those ids. Tried on a scratch copy,
that silently destroyed 831 rows of `exp36_frozen_headline`.

Use the merge script, which strips the ids, rewrites
`phase2_verifier_runs.researcher_run_id` through an old-to-new map, matches
prompts on `(prompt_name, version)` rather than id, and skips rows already
present:

```bash
# once: canonical's CHECK constraints predate EXP-40's terminal statuses
uv run python scripts/migrate_corroborate_strategy_label.py --db data/odmi.db

uv run python scripts/merge_recovered_experiment.py \
    --db data/odmi.db \
    --dump data/recovery/exp40_cooperative_contrast_recovered.sql.gz
```

`--dry-run` reports what would be inserted and rolls back. The merge is
idempotent, so re-running it is safe. Run it against the canonical checkout,
never a worktree copy.

## Two traps in this data

`exp29_sonnet5_model` ran on **claude-sonnet-4-6**, not Sonnet 5, whatever its
name says. `exp34_retrieval_strategy_s5` really is Sonnet 5, as is
`exp28_arch_ablation`. Check `model_version` before using any of these as a
baseline rather than trusting the experiment id.

## The rule this cost us

An experiment is not finished when its analysis JSON is committed. It is
finished when its rows are in the canonical database and that database is
committed. Between those two points the data exists only inside a worktree, and
worktrees get deleted.
