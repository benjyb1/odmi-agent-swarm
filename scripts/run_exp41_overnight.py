"""Unattended EXP-41 runner: one dispatch per replicate, watchdog gates.

Each replicate runs as a SINGLE 156-pair dispatch, identical to replicate 1.
Checks happen at the 5% and 40% marks from a watchdog that reads the database
while the dispatch runs, and kills it if a hard check fails.

Why not staged dispatches. The obvious way to gate at 5/40/100% is three
cumulative dispatches per replicate with an audit between them. Two independent
audits found the same objection: replicate 1 already ran as one dispatch, so
staging replicates 2 and 3 would make the dispatch procedure itself differ
between arms, and three concrete asymmetries follow.

  - `--max-calls` is computed per dispatch (`run_experiments.py`), so a single
    run gets one pool of 7,070 while a staged run gets 410, then ~2,480, then
    ~4,280. Different guard, and it binds asymmetrically if the later countries
    cost more than Malta.
  - `fetch_stage_timeouts` only clears rows older than 45 s, so the tail of one
    stage can trip the next stage's systemic breaker before it spawns anything.
  - A stage that ends abnormally leaves pairs mid-flight, and
    `_find_resumable_researcher` is scoped on (experiment_id, condition_label),
    which every stage of a replicate shares. The next stage would then REPLAY
    that pair's attempt-1 evidence rather than retrieve it again. On an
    experiment whose whole estimand is whether re-retrieved evidence yields the
    same answer, replayed evidence is the one thing that must not happen.

A watchdog gets the same protection without any of that: identical dispatch,
and a hard stop the moment a check fails. The gate audit's `superseded` check
covers the replay path directly, on all three arms.

    uv run python scripts/run_exp41_overnight.py --replicates rep2 rep3
    uv run python scripts/run_exp41_overnight.py --replicates rep2 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "evaluation" / "specs"
RUNS = REPO / "evaluation" / "runs"
DB = REPO / "data" / "odmi.db"

GATE_FRACTIONS = (0.05, 0.40)          # watchdog checkpoints, as pair counts
BATTERY = 156
POLL_S = 30
# `_reset_fetch_stall_window` only drops rows older than FETCH_STALL_WINDOW_S
# (45 s), so the previous replicate's final stalls survive into the next one and
# can trip its systemic breaker before it spawns. Settle past the window.
SETTLE_S = 75


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def finalised(eid: str) -> int:
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            return c.execute(
                "SELECT COUNT(*) FROM phase2_final WHERE experiment_id=?", (eid,)
            ).fetchone()[0]
        finally:
            c.close()
    except sqlite3.Error:
        return 0


def stalls_pending() -> int:
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            return c.execute("SELECT COUNT(*) FROM fetch_stage_timeouts").fetchone()[0]
        finally:
            c.close()
    except sqlite3.Error:
        return 0


def gate(eid: str, expect: int | None = None) -> int:
    cmd = ["uv", "run", "python", "scripts/audit_exp41_gate.py", "--experiment-id", eid]
    if expect is not None:
        cmd += ["--expect", str(expect)]
    return subprocess.run(cmd, cwd=str(REPO)).returncode


def wait_for_quiet(timeout_s: int = 14400) -> bool:
    waited = 0
    while waited < timeout_s:
        if subprocess.run(["pgrep", "-f", "dispatch_subtrios.py"],
                          capture_output=True).returncode != 0:
            return True
        if waited % 300 == 0:
            log("waiting for a running dispatch to finish...")
        time.sleep(POLL_S)
        waited += POLL_S
    return False


def run_replicate(eid: str, dry: bool) -> int:
    spec = SPECS / f"{eid}.json"
    if not spec.exists():
        log(f"FATAL: {spec} missing")
        return 2

    log(f"===== {eid} =====")
    if not dry and not wait_for_quiet():
        log("FATAL: a dispatch is still running; stopping")
        return 1

    if not dry:
        log(f"settling {SETTLE_S}s so the previous run's fetch-stall window expires")
        time.sleep(SETTLE_S)
        n_stall = stalls_pending()
        if n_stall:
            log(f"WARNING: {n_stall} fetch_stage_timeouts rows remain after settling; "
                f"the systemic breaker may trip early on this replicate")

    # Archive this replicate's retrieval receipt, then empty the cache. The
    # archive path is unique per attempt so a re-run never overwrites an
    # earlier receipt.
    stamp = time.strftime("%Y%m%dT%H%M%S")
    archive = RUNS / eid / f"search_cache_pre_{stamp}.db"
    purge = ["uv", "run", "python", "scripts/purge_search_cache.py",
             "--db", str(DB), "--apply", "--archive", str(archive)]
    if dry:
        log(f"DRY-RUN would purge and archive to {archive.name}")
    else:
        if subprocess.run(purge, cwd=str(REPO)).returncode != 0:
            log("FATAL: cache purge failed; refusing to dispatch warm")
            return 1

    if dry:
        rc = subprocess.run(
            ["uv", "run", "python", "scripts/run_experiments.py", str(spec), "--dry-run"],
            cwd=str(REPO)).returncode
        return 0 if rc == 0 else 1

    logfile = RUNS / eid / "dispatch.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    log(f"dispatching {eid} as a single 156-pair run -> {logfile}")
    with logfile.open("a") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "scripts/run_experiments.py", str(spec)],
            cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT,
            start_new_session=True)

    checkpoints = [max(1, round(BATTERY * f)) for f in GATE_FRACTIONS]
    done_gates: set[int] = set()

    while proc.poll() is None:
        time.sleep(POLL_S)
        n = finalised(eid)
        for cp in checkpoints:
            if cp in done_gates or n < cp:
                continue
            done_gates.add(cp)
            log(f"watchdog: {n}/{BATTERY} reached the {cp}-pair gate; auditing")
            if gate(eid) != 0:
                log(f"GATE FAILED at {cp} pairs. Killing {eid} and halting the chain.")
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError) as exc:
                    log(f"could not signal the dispatch group ({exc}); kill it by hand")
                return 1
            log(f"watchdog: {cp}-pair gate PASSED")

    rc = proc.returncode
    log(f"{eid} dispatch exited {rc} at {finalised(eid)}/{BATTERY} pairs")
    if rc != 0:
        log("FATAL: dispatch returned non-zero; halting before the next replicate")
        return 1

    log(f"final gate for {eid}")
    if gate(eid, expect=BATTERY) != 0:
        log(f"FINAL GATE FAILED for {eid}; halting the chain")
        return 1
    log(f"{eid} complete and gated clean")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--replicates", nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for short in args.replicates:
        rc = run_replicate(f"exp41_stability_{short}", args.dry_run)
        if rc != 0:
            log("chain halted; nothing further will be dispatched")
            return rc
    log("all requested replicates complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
