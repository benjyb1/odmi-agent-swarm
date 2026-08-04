"""Strip the colour sentinels once every span has been triaged.

Run only after every @@CL@@/@@CC@@ span has been read and classified.
The 2026-08-04 triage read all 1,454 spans and found no surviving
instruction-note: every span is content and renders black. The two
red passages carrying internal identifiers (data/odmi.db and the
exp34 arm name in the appendix provenance notes) are carried verbatim
and flagged in the port report for the author.

Replacement is the empty string, not a space: coloured-channel
boundaries can fall mid-token (the docx colours ".6" of one "3.6"
separately), and a space would split the number.

Usage: python3 strip_sentinels.py latex_dir
"""

import sys
from pathlib import Path

SENTINELS = ("@@CL@@", "@@/CL@@", "@@CC@@", "@@/CC@@")


def main() -> None:
    total = 0
    for path in sorted(Path(sys.argv[1], "chapters").glob("*.tex")):
        text = path.read_text(encoding="utf-8")
        n = sum(text.count(s) for s in SENTINELS)
        for s in SENTINELS:
            text = text.replace(s, "")
        path.write_text(text, encoding="utf-8")
        total += n
        print(f"{path.name}: {n} sentinel markers removed")
    print(f"total markers removed: {total}")


if __name__ == "__main__":
    main()
