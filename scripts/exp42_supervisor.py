#!/usr/bin/env python3
"""Keep the EXP-42 full-battery dispatch alive, and sweep up operational failures.

The dispatch died silently once already: it was launched as a child of the CLI
session, so when that restarted the run vanished with no traceback, no PAUSE and
no exit message. Nothing noticed for an hour. This supervisor exists so that
cannot recur.

Two jobs:

1. **Heartbeat.** Every HEARTBEAT_S it appends a line to the heartbeat log with
   the wall clock, whether the orchestrator process is alive, and how many pairs
   have finalised. A stalled or dead run is then visible from the log alone,
   without needing this process, the CLI session, or the agent to be watching.

2. **Resume sweeps.** The orchestrator is resume-safe per pair: re-running the
   same spec re-dispatches only pairs with no `phase2_final` row. So a pair lost
   to an agent crash, a fetch timeout, a WAF block or a rate-limit interruption
   is recovered simply by invoking it again. When the orchestrator exits with
   pairs still missing, this relaunches it, up to MAX_SWEEPS times, and stops
   early if a sweep recovers nothing (which means the remainder are hard
   failures, not transient ones, and a human should look).

Run detached, so it outlives any session:

    nohup uv run python scripts/exp42_supervisor.py > /dev/null 2>&1 < /dev/null &
    disown

Stop it by deleting the STOP sentinel path, or `kill` the pid in PIDFILE.
"""
from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "evaluation" / "specs" / "exp42_stance_heldout.json"
DB = REPO / "data" / "odmi.db"
RUN_DIR = REPO / "evaluation" / "runs" / "exp42_stance_heldout"
HEARTBEAT = RUN_DIR / "supervisor_heartbeat.log"
DISPATCH_LOG = RUN_DIR / "supervisor_dispatch.log"
PIDFILE = RUN_DIR / "supervisor.pid"
STOP = RUN_DIR / "SUPERVISOR_STOP"

EXPERIMENT_ID = "exp42_stance_heldout"
TARGET_PAIRS = 1144
HEARTBEAT_S = 60
MAX_SWEEPS = 6
# After the orchestrator exits, give in-flight coordinator children a moment to
# write their final rows before counting, or a sweep looks emptier than it is.
SETTLE_S = 45


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    with HEARTBEAT.open("a") as f:
        f.write(f"{now()} {msg}\n")


def finalised() -> int:
    """Pairs with a terminal row. Read-only; never blocks the writer."""
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
        try:
            return c.execute(
                "SELECT COUNT(*) FROM phase2_final WHERE experiment_id=?",
                (EXPERIMENT_ID,),
            ).fetchone()[0]
        finally:
            c.close()
    except Exception as exc:  # a locked or busy DB is not a reason to die
        log(f"WARN could not read progress: {exc}")
        return -1


def orchestrator_pids() -> list[int]:
    """PIDs of run_experiments processes for this spec, excluding ourselves."""
    # Regex, not a literal: the spec reaches the command line as a path
    # ("evaluation/specs/exp42_stance_heldout.json") whether it was launched by
    # hand or by launch() below, so matching on the bare filename finds nothing.
    try:
        out = subprocess.run(
            ["pgrep", "-f", r"run_experiments\.py.*exp42_stance_heldout"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return []
    pids = []
    for line in out.split():
        try:
            pid = int(line)
        except ValueError:
            continue
        if pid != os.getpid():
            pids.append(pid)
    return pids


def coordinators_running() -> int:
    try:
        out = subprocess.run(
            ["pgrep", "-cf", "run_coordinator.py"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return int(out or 0)
    except Exception:
        return 0


def launch() -> None:
    """Start the orchestrator fully detached (own session, reparented to init)."""
    env = dict(os.environ, ODMI_SKIP_AUTO_PUBLISH="1")
    with DISPATCH_LOG.open("a") as out:
        out.write(f"\n===== supervisor launch {now()} =====\n")
        out.flush()
        subprocess.Popen(
            ["uv", "run", "python", "scripts/run_experiments.py", str(SPEC)],
            cwd=str(REPO), env=env,
            stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,      # detach: no controlling terminal
        )


def main() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    if STOP.exists():
        STOP.unlink()

    stopping = False

    def handle(_sig, _frm):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

    sweeps = 0
    last_sweep_count = -1
    log(f"SUPERVISOR START pid={os.getpid()} target={TARGET_PAIRS} "
        f"max_sweeps={MAX_SWEEPS}")

    while not stopping:
        if STOP.exists():
            log("STOP sentinel present; supervisor exiting")
            break

        pids = orchestrator_pids()
        n = finalised()
        coords = coordinators_running()

        if pids:
            log(f"HEARTBEAT alive pid={pids[0]} finalised={n}/{TARGET_PAIRS} "
                f"coordinators={coords}")
        else:
            # Orchestrator is gone. Either we are done, or it died / exited with
            # pairs still missing.
            if n >= TARGET_PAIRS:
                log(f"COMPLETE finalised={n}/{TARGET_PAIRS}; supervisor exiting")
                break

            if coords > 0:
                log(f"HEARTBEAT orchestrator gone but {coords} coordinator(s) "
                    f"still finishing; waiting before sweep "
                    f"(finalised={n}/{TARGET_PAIRS})")
                time.sleep(HEARTBEAT_S)
                continue

            time.sleep(SETTLE_S)

            # Re-check before relaunching. A transient pgrep miss (the process
            # table is busy, uv is re-execing) would otherwise start a SECOND
            # orchestrator over the same pairs, and two writers on one battery
            # is far worse than a late sweep.
            if orchestrator_pids():
                log("HEARTBEAT orchestrator reappeared on re-check; "
                    "no relaunch (double-dispatch guard)")
                continue

            n = finalised()
            if n >= TARGET_PAIRS:
                log(f"COMPLETE finalised={n}/{TARGET_PAIRS}; supervisor exiting")
                break

            if sweeps >= MAX_SWEEPS:
                log(f"STOP max sweeps ({MAX_SWEEPS}) reached at "
                    f"finalised={n}/{TARGET_PAIRS}; {TARGET_PAIRS - n} pairs "
                    f"unrecovered. Human review needed.")
                break

            if sweeps > 0 and n == last_sweep_count:
                log(f"STOP sweep {sweeps} recovered 0 pairs at "
                    f"finalised={n}/{TARGET_PAIRS}; remaining failures are not "
                    f"transient. Human review needed.")
                break

            last_sweep_count = n
            sweeps += 1
            log(f"RELAUNCH sweep={sweeps} finalised={n}/{TARGET_PAIRS} "
                f"missing={TARGET_PAIRS - n}")
            launch()
            time.sleep(20)   # let it claim the process name before re-checking

        time.sleep(HEARTBEAT_S)

    log(f"SUPERVISOR EXIT pid={os.getpid()}")
    # Only clear the pidfile if it is still ours. A replacement supervisor may
    # already have claimed it while this one was finishing its sleep, and
    # deleting that would orphan the live supervisor from its own pidfile.
    try:
        if PIDFILE.read_text().strip() == str(os.getpid()):
            PIDFILE.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
