"""Repo-wide pytest configuration: keep the test suite off the canonical DB.

``data/odmi.db`` is the primary data store. It is tracked in git (via LFS)
and holds every experiment's rows, including the frozen EXP-36 headline. A
test that opens it read-write silently dirties the working tree, and a
later ``git add -A`` would commit a mutated database over the frozen one.
That has happened, so convention is not enough.

Two layers, installed for every pytest run in this repo:

1. **Redirect.** A session-scoped scratch copy of ``data/odmi.db`` is made
   once, and before each test every module constant that points at the
   canonical file (``DB_PATH``, ``_DB_PATH`` and friends) is rebound to
   that copy. Tests that legitimately read real rows keep working; their
   writes land in the scratch file and are thrown away.

2. **Guard.** ``sqlite3.connect`` is wrapped so that opening the canonical
   path raises :class:`CanonicalDatabaseAccess`. Anything the redirect
   misses (a path bound as a default argument, a hard-coded literal, a new
   module) fails loudly and names the offending call, rather than writing
   to the real file.

Production code is unaffected: both layers live in this file and only ever
run under pytest.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pytest

REPO_ROOT = Path(__file__).resolve().parent
CANONICAL_DB = (REPO_ROOT / "data" / "odmi.db").resolve()

# Module-level constants across agents/, scripts/, dashboard/ and evaluation/
# that hold the path to the primary store. Rebinding these covers the vast
# majority of call sites; the sqlite3 guard covers the rest.
_DB_PATH_ATTRS = ("DB_PATH", "_DB_PATH", "DB", "DEFAULT_DB", "_DEFAULT_DB")

_MESSAGE = (
    "Test tried to open the canonical database at {path}.\n"
    "data/odmi.db is git-tracked and holds the frozen experiment rows, so "
    "the suite is not allowed to touch it.\n"
    "Point the code under test at a scratch database instead: request the "
    "`odmi_test_db` fixture, or pass an explicit tmp_path. If the path came "
    "from a module constant, make sure that constant is read at call time "
    "so conftest.py can redirect it."
)


class CanonicalDatabaseAccess(RuntimeError):
    """Raised when a test tries to open the git-tracked data/odmi.db."""


# ============================================================
# Layer 2: the sqlite3 guard
# ============================================================

_real_connect = sqlite3.connect


def _as_path(database: Any, uri: bool) -> Path | None:
    """Best-effort resolution of a sqlite3 target to a filesystem path.

    Returns None for anything that cannot name the canonical file:
    in-memory databases, file descriptors, unparseable targets.
    """
    if isinstance(database, int):  # a file descriptor, not a path
        return None
    try:
        raw = os.fspath(database)
    except TypeError:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode(sys.getfilesystemencoding(), "replace")
    if not raw or raw == ":memory:":
        return None
    if uri or raw.startswith("file:"):
        parsed = urlparse(raw)
        raw = unquote(parsed.path)
        if not raw:  # file:?mode=memory&cache=shared
            return None
    try:
        return Path(raw).resolve()
    except OSError:
        return None


def _is_canonical(database: Any, uri: bool = False) -> bool:
    path = _as_path(database, uri)
    return path is not None and path == CANONICAL_DB


def _guarded_connect(database: Any, *args: Any, **kwargs: Any):
    if _is_canonical(database, bool(kwargs.get("uri", False))):
        raise CanonicalDatabaseAccess(_MESSAGE.format(path=CANONICAL_DB))
    return _real_connect(database, *args, **kwargs)


# Installed at import time, not in a fixture, so it also covers module-level
# code that runs during collection.
sqlite3.connect = _guarded_connect  # type: ignore[assignment]
sqlite3.dbapi2.connect = _guarded_connect  # type: ignore[assignment]


# ============================================================
# Layer 1: the scratch copy and the redirect
# ============================================================


def _clone(src: Path, dst: Path) -> None:
    """Copy the database, preferring an APFS clone over a byte copy.

    ``data/odmi.db`` is ~330 MB. On macOS ``cp -c`` makes a
    copy-on-write clone, which costs nothing; elsewhere this falls back
    to a plain copy.
    """
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["cp", "-c", str(src), str(dst)],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                return
        except OSError:
            pass
    shutil.copyfile(src, dst)


@pytest.fixture(scope="session")
def odmi_test_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A scratch copy of the canonical database, shared by the session.

    Tests may write to it freely. If the canonical file is missing or is
    still an unsmudged LFS pointer, the copy is whatever is there and the
    tests that need real rows skip themselves, exactly as they do on a
    fresh worktree.
    """
    target = tmp_path_factory.mktemp("odmi-db") / "odmi.db"
    if CANONICAL_DB.exists():
        _clone(CANONICAL_DB, target)
        for suffix in ("-wal", "-shm"):
            side = CANONICAL_DB.with_name(CANONICAL_DB.name + suffix)
            if side.exists():
                _clone(side, target.with_name(target.name + suffix))
    return target


# Modules that own a canonical-DB constant. The per-test scan only sees
# what is already imported, so these are pulled in once up front; a module
# first imported inside a test body is left to the sqlite3 guard.
_DB_OWNING_MODULES = (
    "agents.tools.db",
    "agents.tools.llm",
    "agents.tools.search_cache",
    "scripts.dispatch_subtrios",
    "scripts.harness",
)


@pytest.fixture(scope="session", autouse=True)
def _import_db_owning_modules() -> None:
    import importlib

    for name in _DB_OWNING_MODULES:
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - an unimportable module is the guard's problem
            pass


def _canonical_constants():
    """Yield (module, attribute) pairs in this repo that name the real DB."""
    root = str(REPO_ROOT)
    for module in list(sys.modules.values()):
        origin = getattr(module, "__file__", None)
        if not origin or not origin.startswith(root):
            continue
        for attr in _DB_PATH_ATTRS:
            value = getattr(module, attr, None)
            if isinstance(value, (str, Path)) and _is_canonical(value):
                yield module, attr, value


@pytest.fixture(autouse=True)
def _redirect_canonical_db(odmi_test_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repoint every canonical-DB constant at the scratch copy.

    Runs before each test so modules imported during collection, or by an
    earlier test, are covered. A test's own monkeypatching still wins:
    it is recorded after this one and undone first.
    """
    for module, attr, value in _canonical_constants():
        replacement = str(odmi_test_db) if isinstance(value, str) else odmi_test_db
        monkeypatch.setattr(module, attr, replacement, raising=False)
