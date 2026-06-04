"""Unit tests for the orphan reaper in scripts/cleanup_subtrios.py.

Focus is the PID-identity guard: a stale row's process_pid may have been
recycled by an unrelated process, so the reaper must only SIGTERM a PID
that still looks like the coordinator that started this subtrio. The ps
check is mocked so no real process is ever signalled in CI.
"""

from __future__ import annotations

import contextlib
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import cleanup_subtrios


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE subtrio_status (
            subtrio_id TEXT PRIMARY KEY,
            question_id TEXT, country_code TEXT, stage TEXT,
            updated_at TEXT, process_pid INTEGER,
            final_verdict TEXT, ended_at TEXT, last_message TEXT,
            final_failure_reason TEXT
        );
        """
    )
    # One stale active row, last updated long ago, with a recorded PID.
    conn.execute(
        "INSERT INTO subtrio_status (subtrio_id, question_id, country_code, "
        "stage, updated_at, process_pid) "
        "VALUES ('A', 'P1', 'FR', 'researching', '2000-01-01T00:00:00Z', 4242)"
    )
    conn.commit()
    conn.close()


def _patch_connect(monkeypatch, db_path: Path) -> None:
    @contextlib.contextmanager
    def _fake_connect(*_a, **_k):
        conn = sqlite3.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(cleanup_subtrios, "connect", _fake_connect)


def test_reap_kills_pid_when_it_is_the_coordinator(tmp_path, monkeypatch):
    db_path = tmp_path / "odmi.db"
    _build_db(db_path)
    _patch_connect(monkeypatch, db_path)

    killed: list[int] = []
    monkeypatch.setattr(cleanup_subtrios, "_pid_is_coordinator",
                        lambda pid, sid: True)
    monkeypatch.setattr(cleanup_subtrios.os, "kill",
                        lambda pid, sig: killed.append(pid))

    rows = cleanup_subtrios.reap(age_minutes=10)

    assert len(rows) == 1
    # The PID was confirmed as the coordinator, so it was signalled.
    assert killed == [4242]
    with sqlite3.connect(db_path) as conn:
        stage = conn.execute(
            "SELECT stage FROM subtrio_status WHERE subtrio_id = 'A'"
        ).fetchone()[0]
    assert stage == "orphaned"


def test_reap_skips_kill_when_pid_is_recycled(tmp_path, monkeypatch):
    db_path = tmp_path / "odmi.db"
    _build_db(db_path)
    _patch_connect(monkeypatch, db_path)

    killed: list[int] = []
    # The recorded PID no longer belongs to this coordinator.
    monkeypatch.setattr(cleanup_subtrios, "_pid_is_coordinator",
                        lambda pid, sid: False)
    monkeypatch.setattr(cleanup_subtrios.os, "kill",
                        lambda pid, sig: killed.append(pid))

    rows = cleanup_subtrios.reap(age_minutes=10)

    # Row is still reaped, but nothing was signalled.
    assert len(rows) == 1
    assert killed == []
    with sqlite3.connect(db_path) as conn:
        stage = conn.execute(
            "SELECT stage FROM subtrio_status WHERE subtrio_id = 'A'"
        ).fetchone()[0]
    assert stage == "orphaned"


def test_dry_run_never_kills(tmp_path, monkeypatch):
    db_path = tmp_path / "odmi.db"
    _build_db(db_path)
    _patch_connect(monkeypatch, db_path)

    monkeypatch.setattr(cleanup_subtrios, "_pid_is_coordinator",
                        lambda pid, sid: True)

    def _boom(*_a, **_k):
        raise AssertionError("dry-run must not signal any PID")

    monkeypatch.setattr(cleanup_subtrios.os, "kill", _boom)

    rows = cleanup_subtrios.reap(age_minutes=10, dry_run=True)

    assert len(rows) == 1
    with sqlite3.connect(db_path) as conn:
        stage = conn.execute(
            "SELECT stage FROM subtrio_status WHERE subtrio_id = 'A'"
        ).fetchone()[0]
    # Dry run leaves the row in place.
    assert stage == "researching"


def test_pid_is_coordinator_matches_only_on_marker_and_subtrio(monkeypatch):
    class _Done:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    cmdline = "python scripts/run_coordinator.py P1 FR --subtrio-id A"
    monkeypatch.setattr(cleanup_subtrios.subprocess, "run",
                        lambda *a, **k: _Done(cmdline))
    assert cleanup_subtrios._pid_is_coordinator(4242, "A") is True
    # Right process, wrong subtrio: not a match.
    assert cleanup_subtrios._pid_is_coordinator(4242, "B") is False

    # An unrelated recycled process.
    monkeypatch.setattr(cleanup_subtrios.subprocess, "run",
                        lambda *a, **k: _Done("some-other-daemon --flag"))
    assert cleanup_subtrios._pid_is_coordinator(4242, "A") is False
