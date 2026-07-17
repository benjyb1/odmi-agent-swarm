"""Regression test for the assert_freeze.py porcelain-parsing bug.

_git() used to do (stdout + stderr).strip() before line-splitting. A blanket
strip() eats the leading space off an unstaged-modified first porcelain line
(" M path" -> "M path"), shifting the fixed-column line[3:] parse left by one
and breaking the data/odmi.db* exception the whole script exists to grant.
Reproduced live during EXP-36 dispatch: a legitimate DB write was reported
NOT FROZEN. Fixed by rstrip("\n") instead of strip().
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.assert_freeze as af


def _fake_run(porcelain_stdout: str):
    """Build a subprocess.run stand-in: rev-parse calls succeed and agree,
    status --porcelain returns the given output."""

    class _Result:
        def __init__(self, returncode, stdout, stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _run(cmd, capture_output=True, text=True):
        if cmd[1:3] == ["rev-parse", "--verify"]:
            return _Result(0, "abc123def456\n")
        if cmd[1:] == ["rev-parse", "HEAD"]:
            return _Result(0, "abc123def456\n")
        if cmd[1:3] == ["status", "--porcelain"]:
            return _Result(0, porcelain_stdout)
        raise AssertionError(f"unexpected git call: {cmd}")

    return _run


def test_unstaged_db_modification_is_excepted_as_first_line():
    """The exact tonight's-incident case: data/odmi.db is the only, first,
    unstaged-modified porcelain line. Must report FROZEN (exit 0)."""
    porcelain = " M data/odmi.db\n"
    with patch("subprocess.run", side_effect=_fake_run(porcelain)):
        with patch.object(sys, "argv", ["assert_freeze.py"]):
            assert af.main() == 0


def test_db_modification_plus_untracked_backup_is_excepted():
    porcelain = " M data/odmi.db\n?? data/odmi.db.prerun-backup\n"
    with patch("subprocess.run", side_effect=_fake_run(porcelain)):
        with patch.object(sys, "argv", ["assert_freeze.py"]):
            assert af.main() == 0


def test_genuine_stray_edit_still_fails_frozen_check():
    """A real, non-DB dirty file must still be caught."""
    porcelain = " M scripts/dispatch_subtrios.py\n"
    with patch("subprocess.run", side_effect=_fake_run(porcelain)):
        with patch.object(sys, "argv", ["assert_freeze.py"]):
            assert af.main() == 1


def test_clean_tree_passes():
    with patch("subprocess.run", side_effect=_fake_run("")):
        with patch.object(sys, "argv", ["assert_freeze.py"]):
            assert af.main() == 0
