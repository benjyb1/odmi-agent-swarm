"""The suite must be incapable of writing to the canonical data/odmi.db.

Background: a full ``uv run pytest`` used to mutate the git-tracked
database. The dispatch tests called ``dispatch_subtrios._reset_fetch_stall_window``,
which opens the default connection and runs CREATE TABLE / DELETE, so the
file's sha256 drifted from the committed LFS oid on every run. An
unnoticed ``git add -A`` would then have committed a mutated database over
the frozen EXP-36 rows.

These tests pin both halves of the fix in conftest.py: the sqlite3 guard
that refuses the canonical path, and the redirect that points the module
constants at a scratch copy.
"""

from __future__ import annotations

import sqlite3

import pytest

import conftest as root_conftest
from conftest import CANONICAL_DB, CanonicalDatabaseAccess

# ============================================================
# The guard
# ============================================================

def test_canonical_path_is_the_tracked_database():
    """The guard defends data/odmi.db in this checkout, not some other copy."""
    assert CANONICAL_DB.name == "odmi.db"
    assert CANONICAL_DB.parent.name == "data"
    assert CANONICAL_DB.parent.parent == root_conftest.REPO_ROOT


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(CANONICAL_DB, id="path"),
        pytest.param(str(CANONICAL_DB), id="str"),
        pytest.param("data/odmi.db", id="relative"),
        pytest.param(f"file:{CANONICAL_DB}", id="uri"),
        pytest.param(f"file:{CANONICAL_DB}?mode=ro", id="uri-readonly"),
    ],
)
def test_opening_the_canonical_db_raises(target):
    """Every spelling of the canonical path is refused, read-only included."""
    kwargs = {"uri": True} if str(target).startswith("file:") else {}
    with pytest.raises(CanonicalDatabaseAccess):
        sqlite3.connect(target, **kwargs)


def test_guard_message_names_the_file_and_the_way_out():
    with pytest.raises(CanonicalDatabaseAccess) as excinfo:
        sqlite3.connect(CANONICAL_DB)
    message = str(excinfo.value)
    assert str(CANONICAL_DB) in message
    assert "odmi_test_db" in message


@pytest.mark.parametrize("target", [":memory:", "file::memory:?cache=shared"])
def test_in_memory_databases_are_untouched(target):
    kwargs = {"uri": True} if target.startswith("file:") else {}
    conn = sqlite3.connect(target, **kwargs)
    conn.close()


def test_other_paths_still_open(tmp_path):
    conn = sqlite3.connect(tmp_path / "scratch.db")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.close()


# ============================================================
# The redirect
# ============================================================

def test_module_constants_point_at_the_scratch_copy(odmi_test_db):
    from agents.tools import db, llm, search_cache

    assert db.DB_PATH == odmi_test_db
    assert search_cache._DB_PATH == odmi_test_db
    assert llm._DB_PATH == odmi_test_db


def test_default_connection_lands_in_the_scratch_copy(odmi_test_db):
    """connect() with no argument resolves DB_PATH at call time.

    The old signature bound the canonical path as a default argument, so
    redirecting the module constant missed every default caller.
    """
    from agents.tools.db import connect

    with connect() as conn:
        opened = conn.execute("PRAGMA database_list").fetchone()[2]
    assert opened == str(odmi_test_db)


def test_the_dispatch_stall_window_no_longer_writes_to_the_tracked_db(odmi_test_db):
    """The specific caller that used to dirty data/odmi.db on every run."""
    from scripts import dispatch_subtrios

    dispatch_subtrios._reset_fetch_stall_window()

    conn = sqlite3.connect(odmi_test_db)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    assert "fetch_stage_timeouts" in tables


def test_writes_through_the_default_path_never_reach_the_canonical_file(odmi_test_db):
    """A write via the default connection is invisible to the real file."""
    from agents.tools.db import connect

    with connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS _guard_probe (x INTEGER)")
        conn.execute("INSERT INTO _guard_probe VALUES (1)")
        conn.commit()

    if not CANONICAL_DB.exists():
        pytest.skip("no canonical database in this checkout")

    # The real file is off limits to sqlite3, so check it the way git does:
    # size and modification time. A committed write would move both.
    before = CANONICAL_DB.stat()
    with connect() as conn:
        conn.execute("INSERT INTO _guard_probe VALUES (2)")
        conn.commit()
    after = CANONICAL_DB.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
