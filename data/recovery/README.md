# Recovered experiment data

## EXP-40 cooperative arm, and its EXP-34 replay seed

Recovered 2026-07-21. Both experiments were absent from the canonical
`data/odmi.db` and from all 41 worktree copies of it.

### What happened

EXP-40 ran on 2026-07-19 in a worktree that was later deleted. The run's code,
prereg and analysis JSON were committed (`5b663d9`, `8d699d2`, `5d2213f`,
`2106efd`), but the SQLite rows never were: `data/odmi.db` is Git LFS tracked,
and no commit in that sequence touched it. Deleting the worktree took the only
copy of the rows with it.

The rows survived by accident. Git LFS had already staged a snapshot of that
worktree's database into the local object store, where it sat unreferenced by
any commit. Object
`b37d933dd6f5b9b27cc5bda5d2cb0d423fbde5d898a6ae0d2af2d388f775df9c`
(plus its `-wal` and `-shm` sidecars) held the completed run.

That object was one prune away from being lost for good: `git lfs prune
--dry-run` lists 169 unreferenced objects totalling 26 GB, and this was among
them. These dumps exist so the data no longer depends on it.

### What the dumps contain

`exp40_cooperative_recovered.sql.gz` (999 rows)

| table | rows |
|---|---|
| `experiments` | 1 |
| `phase2_final` | 157 (156 distinct pairs; `PT9:MT` has an `agent_failure` row plus its retry) |
| `phase2_researcher_runs` | 433 |
| `phase2_verifier_runs` | 231 |
| `subtrio_status` | 177 |

Battery MT 60 / NL 52 / AL 44. Terminal statuses `accepted_cooperative` 63,
`abstained_cooperative` 93, `agent_failure` 1. No adjudications, as the
cooperative pipeline has no Adjudicator by design. Model `claude-sonnet-4-6`
throughout.

`exp34_retrieval_strategy_recovered.sql.gz` (1,172 rows) carries
`exp34_retrieval_strategy_s46` and `_s5`: 314 finals and 856 researcher runs.
EXP-40's trio / no_adjudicator / researcher_only arms are replays off the
`wide_only` condition of that run, so the analysis needs it present.

### Verification

Restoring both dumps into a copy of the canonical database and re-running
`evaluation/exp40_analysis.py` reproduces the committed
`evaluation/results/exp40_analysis.json` byte for byte: all four arms, and the
primary McNemar contrast at 8-vs-8, p = 1.00. The published numbers in
`docs/RESULTS.md` stand on recovered data, not on a re-run.

### Restoring

The canonical database predates EXP-40's CHECK constraints, so migrate first or
every `phase2_final` insert fails:

```bash
uv run python scripts/migrate_corroborate_strategy_label.py --db data/odmi.db
gunzip -c data/recovery/exp34_retrieval_strategy_recovered.sql.gz | sqlite3 data/odmi.db
gunzip -c data/recovery/exp40_cooperative_recovered.sql.gz | sqlite3 data/odmi.db
uv run python evaluation/exp40_analysis.py --db data/odmi.db \
    --out evaluation/results/exp40_analysis.json
```

Inserts are `INSERT OR REPLACE`, so re-running is safe. Run this against the
canonical checkout, never a worktree copy.

### Why not just re-run it

A re-run costs about £8.71 and 1.5 hours, which is affordable, but it would
produce different numbers. The swarm is not deterministic, so a fresh run
cannot reproduce the figures already published in `docs/RESULTS.md` and in the
`2106efd` commit message. Recovering the original rows keeps the paper trail
intact; re-running would mean restating the result.

### The general lesson

An experiment is not finished when its analysis JSON is committed. It is
finished when its rows are in the canonical database and that database is
committed. Between those two points the data lives only in a worktree, and
worktrees get deleted.
