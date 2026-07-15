# EXP-36 dispatch runbook

## TL;DR — how to run it

Everything is prepared. From this worktree
(`.claude/worktrees/exp36-pre-dispatch-audit-f39206`, HEAD at the
`exp36-config-freeze` tag), one command runs the whole thing:

```bash
bash scripts/run_exp36.sh
```

It runs every gate in order (freeze check, .env, auth preflight, stages the
purged + registered dispatch DB, held-out cache re-scan, dry-run), then prompts
with a 15s countdown before the real dispatch. It is resume-safe: if the run is
interrupted, the same command resumes it. The manual steps below are the same
gates spelled out, for when something needs doing by hand.

Nothing else is required first. Merging PR #26 to main and purging the canonical
DB are optional hygiene, not preconditions: the run dispatches from the prepared
`data/odmi.exp36-dispatch.db`, which is already clean and registered.

---

Operational steps for the single frozen headline run. Design and rationale are
in `docs/EXPERIMENTS_EXP36_PREREG.md`; this file is the checklist for the
person at the keyboard. Every step is on the **dispatch DB**, a fresh copy of
the canonical DB, never a worktree copy and never the live canonical DB itself.

The run reads the held-out eight (BA MK ME BG FI HR SE BE) exactly once. A wrong
config or a contaminated DB compromises the one reported number and cannot be
re-read cleanly. Do not skip the verification lines.

## 0. Preconditions

- On `main` at the merge that carries the B1/B2 fixes, `wide_only`, and the
  purge/register scripts.
- CLIProxyAPI up on `localhost:8317`, cloak ON (D62), Claude Max authenticated
  on `claude-sonnet-4-6` (a real 4.6 call succeeds, not a 401/503). Verify at
  the dispatch concurrency with `uv run python scripts/loadtest_proxy.py`.
- **The dispatch checkout must contain `.env`.** `llm.py` auto-loads `.env`
  from the checkout root; it is git-ignored, so a fresh worktree has none and
  every call fails auth (the rehearsal caught this: 0 finals, orphaned at
  `query_gen_start`). Dispatch from the canonical checkout, or `cp` the canonical
  `.env` into the dispatch checkout first.
- `git tag -l` shows no EXP-36 freeze tag yet (it is applied last, step 7).

**Rehearsed (2026-07-14).** The frozen config was rehearsed end-to-end on dev
countries (`exp36_rehearsal`: NL 10 + AL 6, `no_cache`, `parallel=3`) with a
mid-run `SIGKILL` and resume. Result: 16/16 finalised, zero duplicates, the
three pre-kill pairs finalised exactly once (resume is clean); NL 10/10 committed;
AL abstained 4/6 with zero `agent_failure` (thin-web coverage will be lower on
stratum A, but honest). An arm that comes back with 0 finals (e.g. an auth
outage) trips the orchestrator health gate, which pauses and prints "re-run the
same spec to resume" rather than pressing on.

## 1. Build the dispatch DB (fresh, purged, registered)

The canonical `data/odmi.db` still carries held-out cache (892 fetch + 112 SERP
+ 202 snippet as of 2026-07-14) and is git-tracked. Work on a copy.

```bash
# from a clean checkout root
cp data/odmi.db /tmp/odmi.exp36-dispatch.db

# purge held-out cache; must print VERIFIED CLEAN (0 residual, all three layers)
uv run python scripts/purge_heldout_cache.py --db /tmp/odmi.exp36-dispatch.db --apply

# register the experiment (R1); preflight hard-fails without this row
uv run python scripts/register_exp36.py --db /tmp/odmi.exp36-dispatch.db

# confirm model_defaults are 4.6 for all three roles; set them if not
uv run python scripts/set_default_model.py --model claude-sonnet-4-6 --db /tmp/odmi.exp36-dispatch.db
```

Then make this copy the DB the dispatch reads. The code resolves `data/odmi.db`
relative to the checkout root (`agents/tools/db.py`), so either dispatch from a
dedicated checkout whose `data/odmi.db` **is** this file, or swap it in:

```bash
cp data/odmi.db data/odmi.db.canonical-backup    # keep the untouched canonical
cp /tmp/odmi.exp36-dispatch.db data/odmi.db       # dispatch DB in place
```

Do not `git add` / commit `data/odmi.db` at any point in this run.

## 2. Pre-dispatch audits (must be clean)

```bash
# deny-list / finalised-URL leakage audit
uv run python scripts/check_data_leakage.py

# held-out cache re-scan: the purge script in dry-run must report 0 identified
uv run python scripts/purge_heldout_cache.py --db data/odmi.db
```

`check_data_leakage.py` clean and the purge dry-run reporting
`fetch=0 serp=0 snippet=0` are the go/no-go gate.

## 3. Disable auto-publish

`dispatch_subtrios.py::publish_to_main` commits and pushes `data/odmi.db` to
`origin/main` after each batch when on `main`. That would commit the disposable,
freshly-cache-contaminated dispatch DB. Disable it for the whole run:

```bash
export ODMI_SKIP_AUTO_PUBLISH=1
```

## 4. Dispatch (via the orchestrator, resume-safe)

```bash
# freeze gate: HEAD must be the tagged commit and the tree clean (step 7 tag).
uv run python scripts/assert_freeze.py    # exits non-zero unless frozen

# dry-run first: 8 arms, 1,144 pairs, no_cache=True on every arm, budget 55000.
# For a headline spec the preflight now also hard-fails if the dispatch DB still
# carries any held-out cache row, so this doubles as the purge gate.
uv run python scripts/run_experiments.py evaluation/specs/exp36_frozen_headline.json --dry-run

# real run
uv run python scripts/run_experiments.py evaluation/specs/exp36_frozen_headline.json
```

Order is stratum B first (FI SE BE HR) then stratum A (BA MK ME BG). Watch the
first arm (FI) finalise before trusting the rest: check its abstention rate and
`agent_failure` count are in a sane band (a spike means a transport or config
fault, not a real result).

## 5. Resume after any interruption

Re-run the identical command. `run_experiments.py` skips pairs already finalised
for each arm, and the coordinator resumes only clean, committed Researcher rows
(`_find_resumable_researcher`). One frozen config across every resume: same spec,
same pinned models, same `model_defaults`. A resume under any changed knob voids
the run and it is re-read from scratch.

## 6. Preserve the finals (receipts)

The dispatch DB is disposable, so export the reported rows to a committed
artefact before discarding it:

```bash
mkdir -p evaluation/runs/exp36_frozen_headline
sqlite3 -header -csv data/odmi.db \
  "SELECT * FROM phase2_final WHERE experiment_id='exp36_frozen_headline';" \
  > evaluation/runs/exp36_frozen_headline/finals.csv
# and the full agent trail for replay
uv run python evaluation/_trail_dump.py --experiment exp36_frozen_headline \
  > evaluation/runs/exp36_frozen_headline/trail.jsonl   # confirm this script's flags
```

Commit the exported artefacts (text, not the binary DB). If the finals are also
wanted in the public dashboard, merge only the `exp36_frozen_headline` rows into
the canonical DB deliberately, on `main`, in a named commit.

## 7. Post-run and freeze tag

- Re-run `check_data_leakage.py` and the purge dry-run: still clean.
- FM-14 fingerprint audit over the committed evidence.
- Only now apply the `ARCHITECTURE.md` freeze tag: it certifies the config the
  headline actually ran under, so it is the last step, after the finals exist.
- Restore the untouched canonical DB if you swapped it in step 1
  (`cp data/odmi.db.canonical-backup data/odmi.db`), or discard the dispatch copy.
