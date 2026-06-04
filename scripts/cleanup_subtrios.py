"""Reap orphan subtrios.

Finds subtrio_status rows that are still in an active stage but haven't
been updated in 10 minutes (configurable). Marks them `orphaned` and
attempts to kill the PID if it's still alive.

Usage:
    uv run python scripts/cleanup_subtrios.py
    uv run python scripts/cleanup_subtrios.py --age-minutes 2 --dry-run
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.tools.db import connect


ACTIVE_STAGES = (
    "queued", "researching", "verifying", "adjudicating",
)


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds") + "Z"
    )


def _pid_is_coordinator(pid: int, subtrio_id: str) -> bool:
    """Confirm `pid` is the coordinator process for this subtrio.

    Guards against PID reuse: between the status row being written and the
    reaper running, the recorded PID could have been recycled by an
    unrelated process. We only signal a process whose command line is the
    coordinator running this exact subtrio. `-ww` stops `ps` truncating the
    command, so the subtrio UUID is always visible. Mirrors the same check
    in dashboard/lib/db.py.
    """
    try:
        out = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception:  # noqa: BLE001
        return False
    return "run_coordinator" in out and subtrio_id in out


def reap(age_minutes: int = 10, *, dry_run: bool = False) -> list[dict]:
    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(minutes=age_minutes)
    ).isoformat(timespec="seconds") + "Z"

    with connect() as conn:
        conn.row_factory = lambda c, r: dict(
            zip([col[0] for col in c.description], r)
        )
        rows = conn.execute(
            f"""SELECT subtrio_id, question_id, country_code, stage,
                       updated_at, process_pid
                FROM subtrio_status
                WHERE stage IN ({','.join('?' * len(ACTIVE_STAGES))})
                  AND (updated_at IS NULL OR updated_at < ?)""",
            (*ACTIVE_STAGES, cutoff),
        ).fetchall()

    if not rows:
        return []

    if dry_run:
        return rows

    now = _now_iso()
    with connect() as conn:
        for r in rows:
            # Best-effort PID kill. Only signal a PID that still looks like
            # the coordinator this row started; a recycled PID belonging to
            # an unrelated process must not be touched.
            pid = r.get("process_pid")
            if pid and _pid_is_coordinator(pid, r["subtrio_id"]):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass  # Already gone.
                except PermissionError:
                    pass
            conn.execute(
                """UPDATE subtrio_status
                   SET stage = 'orphaned',
                       final_verdict = 'orphaned',
                       ended_at = ?, updated_at = ?,
                       last_message = ?,
                       final_failure_reason = 'orphan_reaped'
                   WHERE subtrio_id = ?""",
                (now, now, f"reaped (stale > {age_minutes}m)", r["subtrio_id"]),
            )
        conn.commit()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--age-minutes", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = reap(age_minutes=args.age_minutes, dry_run=args.dry_run)
    action = "Would reap" if args.dry_run else "Reaped"
    print(f"{action} {len(rows)} subtrio(s) stale > {args.age_minutes}m:")
    for r in rows:
        print(f"  {r['subtrio_id'][:8]} {r['question_id']}/{r['country_code']} "
              f"stage={r['stage']} pid={r.get('process_pid')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
