"""Guard the install of an edited master.

Re-hashes the master immediately before the copy and aborts if it changed since
the edit was computed. Concurrent windows write to this file, and a stale
install silently destroys whatever the other window did.

Prints the command to run. Does not copy anything itself, so the copy stays a
single plain cp.

Usage:
    python3 scripts/install_edit.py <master> <expected_sha> <candidate>
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    master, expected, candidate = sys.argv[1], sys.argv[2], sys.argv[3]

    now = sha(master)
    if now != expected:
        raise SystemExit(
            f"ABORT: master changed since the edit was computed.\n"
            f"  expected {expected}\n  found    {now}\n"
            f"Re-run the edit against the current file.")

    # The candidate must at least open as a docx before it replaces anything.
    with zipfile.ZipFile(candidate) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit(f"ABORT: candidate zip corrupt at {bad}")
        if "word/document.xml" not in z.namelist():
            raise SystemExit("ABORT: candidate has no word/document.xml")

    print(f"master unchanged ({now[:16]})")
    print(f"candidate ok, {os.path.getsize(candidate):,} bytes")
    print("SAFE TO INSTALL")


if __name__ == "__main__":
    main()
