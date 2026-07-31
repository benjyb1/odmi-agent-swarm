"""Keep the overnight review alive until it finishes.

The supervisor can die in ways it cannot report: an OOM kill, a SIGKILL to the
process group, the machine suspending mid-call. A background process that has
been killed sends no notification, so liveness has to be inferred from outside.
This watches the heartbeat file and relaunches with --resume when it goes stale.

Relaunching is safe because the supervisor records state after each unit and
skips completed work on resume.

Runs under caffeinate so the machine stays awake for the whole run.

Usage:
    python3 scripts/overnight_watchdog.py --out build/overnight
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHECK_SECONDS = 45
STALE_SECONDS = 420        # heartbeat older than this means wedged or dead
MAX_RESTARTS = 12
GRACE_SECONDS = 90         # allow this long for the first heartbeat to appear


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Watchdog:
    def __init__(self, out):
        self.out = os.path.abspath(out)
        os.makedirs(self.out, exist_ok=True)
        self.log_path = os.path.join(self.out, "watchdog.log")
        self.heartbeat = os.path.join(self.out, "heartbeat.json")
        self.state = os.path.join(self.out, "state.json")
        self.status_path = os.path.join(self.out, "watchdog_status.json")
        self.proc = None
        self.restarts = 0

    def log(self, msg):
        line = f"[{now()}] watchdog: {msg}"
        print(line, flush=True)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")

    def write_status(self, note):
        payload = {
            "ts": now(),
            "epoch": time.time(),
            "watchdog_pid": os.getpid(),
            "supervisor_pid": self.proc.pid if self.proc else None,
            "restarts": self.restarts,
            "note": note,
            "phase": self.read_phase(),
            "heartbeat_age": self.heartbeat_age(),
        }
        tmp = self.status_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=1)
        os.replace(tmp, self.status_path)

    def read_phase(self):
        try:
            with open(self.state) as f:
                return json.load(f).get("phase")
        except (OSError, json.JSONDecodeError):
            return None

    def heartbeat_age(self):
        try:
            with open(self.heartbeat) as f:
                beat = json.load(f)
            return round(time.time() - float(beat.get("epoch", 0)))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def launch(self, resume):
        cmd = [sys.executable, "scripts/overnight_review.py", "--out", self.out]
        if resume:
            cmd.append("--resume")
        logf = open(os.path.join(self.out, "supervisor.stdout"), "a")
        # New session, so a signal aimed at the watchdog does not take the
        # supervisor with it.
        self.proc = subprocess.Popen(
            cmd, cwd=HERE, stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.log(f"launched supervisor pid {self.proc.pid} (resume={resume})")

    def supervisor_alive(self):
        return self.proc is not None and self.proc.poll() is None

    def kill_supervisor(self):
        if not self.supervisor_alive():
            return
        self.log(f"killing wedged supervisor {self.proc.pid}")
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            time.sleep(10)
            if self.proc.poll() is None:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError) as exc:
            self.log(f"kill failed, assuming already gone: {exc!r}")

    def run(self):
        self.log("=" * 50)
        self.log(f"starting, pid {os.getpid()}, out {self.out}")
        resume = os.path.exists(self.state)
        self.launch(resume)
        started = time.time()
        self.write_status("launched")

        while True:
            time.sleep(CHECK_SECONDS)
            phase = self.read_phase()

            if phase == "complete":
                self.log("supervisor reports complete")
                self.write_status("complete")
                return 0

            alive = self.supervisor_alive()
            age = self.heartbeat_age()

            if alive and age is not None and age <= STALE_SECONDS:
                self.write_status(f"healthy, heartbeat {age}s old")
                continue

            if alive and age is None and time.time() - started < GRACE_SECONDS:
                self.write_status("waiting for first heartbeat")
                continue

            # Something is wrong. Decide which.
            if not alive:
                rc = self.proc.poll() if self.proc else "?"
                reason = f"supervisor exited rc={rc}"
            else:
                reason = f"heartbeat stale ({age}s)"
                self.kill_supervisor()

            self.restarts += 1
            if self.restarts > MAX_RESTARTS:
                self.log(f"{reason}; restart budget exhausted, giving up")
                self.write_status("gave up")
                return 1

            self.log(f"{reason}; restarting ({self.restarts}/{MAX_RESTARTS})")
            self.write_status(f"restarting after: {reason}")
            time.sleep(15)
            self.launch(resume=True)
            started = time.time()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/overnight")
    args = ap.parse_args()
    sys.exit(Watchdog(args.out).run())


if __name__ == "__main__":
    main()
